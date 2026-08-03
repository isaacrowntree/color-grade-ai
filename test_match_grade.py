#!/usr/bin/env python3
"""test_match_grade.py — Tests for shot matching.

Unlike solve_grade.py, the target here is another image rather than a fixed set
of ideals. The test is therefore: take a known-good frame, damage a copy, and
check that matching moves the copy back toward the original.

Run: python3 test_match_grade.py
"""

import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import eval_scenes
import match_grade


def pair(case):
    base = eval_scenes.pristine()
    return base, eval_scenes.degrade(base, **eval_scenes.CASES[case])


class TestDescriptor(unittest.TestCase):

    def test_identical_frames_have_zero_distance(self):
        base = eval_scenes.pristine()
        d = match_grade.descriptor(base)
        self.assertAlmostEqual(match_grade.distance(d, d), 0.0, places=9)

    def test_distance_grows_with_damage(self):
        base = eval_scenes.pristine()
        ref = match_grade.descriptor(base)
        mild = match_grade.descriptor(
            eval_scenes.degrade(base, gains=(1.05, 1.0, 0.97)))
        severe = match_grade.descriptor(
            eval_scenes.degrade(base, gains=(1.30, 1.0, 0.72)))
        self.assertLess(match_grade.distance(ref, mild),
                        match_grade.distance(ref, severe))

    def test_descriptor_is_vectorised(self):
        """The old implementation looped colorsys per pixel; a 4K-sized frame
        must stay comfortably fast."""
        import time
        big = np.random.default_rng(0).uniform(0, 1, (2160, 3840, 3))
        start = time.perf_counter()
        match_grade.descriptor(big)
        self.assertLess(time.perf_counter() - start, 10.0)


class TestMatching(unittest.TestCase):

    def assert_closes_gap(self, case, factor=0.5):
        base, damaged = pair(case)
        plan = match_grade.match(base, damaged)
        ref = match_grade.descriptor(base)

        before = match_grade.distance(ref, match_grade.descriptor(damaged))
        after = match_grade.distance(
            ref, match_grade.descriptor(plan.apply(damaged)))

        self.assertLess(after, before * factor,
                        f'{case}: {before:.4f} -> {after:.4f}')
        return before, after

    def test_matches_a_warm_cast(self):
        self.assert_closes_gap('warm_tungsten')

    def test_matches_a_cool_cast(self):
        self.assert_closes_gap('cool_daylight')

    def test_matches_an_exposure_difference(self):
        self.assert_closes_gap('underexposed')

    def test_matches_a_combined_defect(self):
        self.assert_closes_gap('warm_and_dark')

    def test_matches_a_washed_out_shot(self):
        self.assert_closes_gap('washed_out')

    def test_matches_an_oversaturated_shot(self):
        self.assert_closes_gap('oversaturated')

    def test_saturation_is_matched_explicitly(self):
        """Two shots can agree on channel means and still differ in vividness."""
        base, washed = pair('washed_out')
        plan = match_grade.match(base, washed)
        self.assertIn('matched_saturation', [s['preset'] for s in plan.chain])

    def test_matching_a_frame_to_itself_does_nothing(self):
        base = eval_scenes.pristine()
        plan = match_grade.match(base, base)
        self.assertEqual(plan.chain, [])

    def test_emits_a_usable_lut(self):
        from lut_apply import CubeLUT

        base, damaged = pair('warm_and_dark')
        plan = match_grade.match(base, damaged)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'match.cube')
            plan.write_cube(path)
            graded = CubeLUT.load(path).apply(damaged)

        ref = match_grade.descriptor(base)
        before = match_grade.distance(ref, match_grade.descriptor(damaged))
        after = match_grade.distance(ref, match_grade.descriptor(graded))
        self.assertLess(after, before * 0.6)


class TestTransferAwareness(unittest.TestCase):
    """Matching log against Rec.709 is a missing conversion LUT, not a grade."""

    def test_mismatched_transfer_is_flagged(self):
        base = eval_scenes.pristine()
        log = eval_scenes.as_log(base)
        plan = match_grade.match(base, log)
        self.assertTrue(plan.mismatched_transfer)

    def test_matching_two_display_frames_is_not_flagged(self):
        base, damaged = pair('warm_tungsten')
        plan = match_grade.match(base, damaged)
        self.assertFalse(plan.mismatched_transfer)

    def test_tone_stages_are_held_back_on_log(self):
        log_ref = eval_scenes.as_log(eval_scenes.pristine())
        log_out = eval_scenes.as_log(
            eval_scenes.degrade(eval_scenes.pristine(), gains=(1.2, 1.0, 0.8)))
        plan = match_grade.match(log_ref, log_out)
        names = [s['preset'] for s in plan.chain]
        self.assertNotIn('matched_exposure', names)
        self.assertNotIn('matched_black_level', names)

    def test_white_balance_still_matches_on_log(self):
        log_ref = eval_scenes.as_log(eval_scenes.pristine())
        log_out = eval_scenes.as_log(
            eval_scenes.degrade(eval_scenes.pristine(), gains=(1.25, 1.0, 0.78)))
        plan = match_grade.match(log_ref, log_out)
        self.assertIn('matched_white_balance',
                      [s['preset'] for s in plan.chain])

    def test_stating_the_transfer_permits_tone_matching(self):
        log_ref = eval_scenes.as_log(eval_scenes.pristine())
        log_out = eval_scenes.as_log(
            eval_scenes.degrade(eval_scenes.pristine(), gamma=1.4))
        plan = match_grade.match(log_ref, log_out, transfer='display')
        self.assertIn('matched_exposure', [s['preset'] for s in plan.chain])


if __name__ == '__main__':
    unittest.main(verbosity=2)

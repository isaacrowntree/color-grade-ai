#!/usr/bin/env python3
"""test_footage_type.py — Tests for log vs display-referred detection.

Correction LUTs are built for display-referred Rec.709, applied after a
conversion LUT. Handed log footage, the tool will happily "fix" the lifted
blacks and flat contrast that are supposed to be there, and produce a
confidently wrong grade with no complaint. That is the worst failure mode this
tool has, so detection has to be reliable and the distinction has to be stated
out loud.

The hard cases are display-referred frames that superficially resemble log:
milky blacks look lifted, an overexposed frame has a raised floor, and a flat
scene has low contrast. None of those should be misread as log.

Run: python3 test_footage_type.py
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import eval_scenes
import footage_type


class TestLogEncoding(unittest.TestCase):
    """The fixture itself must behave like real log before it can test anything."""

    def test_slog3_lifts_black(self):
        self.assertGreater(eval_scenes.slog3(0.0), 0.08)

    def test_slog3_rolls_highlights(self):
        self.assertLess(eval_scenes.slog3(1.0), 0.80)

    def test_slog3_is_monotonic(self):
        values = eval_scenes.slog3(np.linspace(0, 1, 256))
        self.assertTrue(np.all(np.diff(values) > 0))

    def test_log_scene_is_flatter_than_its_source(self):
        base = eval_scenes.pristine()
        log = eval_scenes.as_log(base)
        self.assertLess(log.std(), base.std())


class TestDetectsLog(unittest.TestCase):

    def test_log_scene_is_detected(self):
        log = eval_scenes.as_log(eval_scenes.pristine())
        self.assertEqual(footage_type.detect(log).kind, 'log')

    def test_log_detection_survives_a_colour_cast(self):
        base = eval_scenes.pristine()
        for case in ('warm_tungsten', 'cool_daylight', 'green_led'):
            with self.subTest(case=case):
                degraded = eval_scenes.degrade(base, **eval_scenes.CASES[case])
                self.assertEqual(footage_type.detect(
                    eval_scenes.as_log(degraded)).kind, 'log')

    def test_reports_evidence(self):
        log = eval_scenes.as_log(eval_scenes.pristine())
        result = footage_type.detect(log)
        self.assertTrue(result.evidence)
        self.assertTrue(any('black' in e.lower() for e in result.evidence))

    def test_is_confident_about_clear_log(self):
        log = eval_scenes.as_log(eval_scenes.pristine())
        self.assertGreaterEqual(footage_type.detect(log).confidence, 0.75)


class TestDetectsDisplay(unittest.TestCase):

    def test_pristine_scene_is_display_referred(self):
        self.assertEqual(footage_type.detect(eval_scenes.pristine()).kind,
                         'display')

    def test_no_degraded_case_is_mistaken_for_log(self):
        """Every defect in the evaluation set is display-referred."""
        for case in eval_scenes.CASES:
            with self.subTest(case=case):
                _, degraded = eval_scenes.build(case)
                result = footage_type.detect(degraded)
                self.assertEqual(result.kind, 'display',
                                 f'{case} misread as {result.kind}: '
                                 f'{result.evidence}')

    def test_milky_blacks_are_not_log(self):
        """Lifted blacks alone are not log — highlights and range still reach."""
        _, milky = eval_scenes.build('milky_blacks')
        self.assertEqual(footage_type.detect(milky).kind, 'display')

    def test_a_flat_low_contrast_grade_is_not_called_log(self):
        """It measures like log, so it must not be *asserted* to be display
        either — the honest answer is that shape cannot tell them apart."""
        base = eval_scenes.pristine()
        flat = 0.25 + base * 0.5
        self.assertEqual(footage_type.detect(flat).kind, 'ambiguous')


class TestAmbiguity(unittest.TestCase):
    """Where the measurements genuinely cannot decide, say so."""

    @staticmethod
    def flat_grade():
        return 0.25 + eval_scenes.pristine() * 0.5

    def test_ambiguous_holds_back_tone_fitting(self):
        self.assertFalse(footage_type.detect(self.flat_grade()).tone_targets_apply)

    def test_ambiguous_asks_the_user_to_choose(self):
        warnings = footage_type.detect(self.flat_grade()).warnings
        joined = ' '.join(warnings).lower()
        self.assertIn('--transfer', joined)

    def test_ambiguous_is_flagged_for_confirmation(self):
        self.assertTrue(footage_type.detect(self.flat_grade()).needs_confirmation)
        self.assertFalse(footage_type.detect(eval_scenes.pristine()).needs_confirmation)

    def test_stating_the_transfer_resolves_it(self):
        for assume in ('log', 'display'):
            with self.subTest(assume=assume):
                result = footage_type.detect(self.flat_grade(), assume=assume)
                self.assertEqual(result.kind, assume)
                self.assertFalse(result.needs_confirmation)

    def test_underexposed_log_is_at_least_not_called_display(self):
        """Underexposed log loses the midpoint signature, so it lands in
        ambiguous rather than being waved through as display-referred."""
        dark_log = eval_scenes.as_log(
            eval_scenes.degrade(eval_scenes.pristine(), gamma=1.5))
        self.assertIn(footage_type.detect(dark_log).kind, ('log', 'ambiguous'))

    def test_midpoint_position_is_invariant_under_a_linear_remap(self):
        base = eval_scenes.pristine()
        a = footage_type.measure(base)['midpoint_position']
        b = footage_type.measure(0.25 + base * 0.5)['midpoint_position']
        self.assertAlmostEqual(a, b, places=2)

    def test_midpoint_position_moves_under_a_log_curve(self):
        base = eval_scenes.pristine()
        a = footage_type.measure(base)['midpoint_position']
        b = footage_type.measure(eval_scenes.as_log(base))['midpoint_position']
        self.assertGreater(b - a, 0.08)


class TestBehaviourOnLog(unittest.TestCase):
    """Detection is only useful if it changes what the tool does."""

    def setUp(self):
        self.log = eval_scenes.as_log(eval_scenes.pristine())
        self.display = eval_scenes.pristine()

    def test_log_blocks_tone_fitting(self):
        """Black level and exposure targets are meaningless on log."""
        self.assertFalse(footage_type.detect(self.log).tone_targets_apply)
        self.assertTrue(footage_type.detect(self.display).tone_targets_apply)

    def test_log_produces_a_warning_naming_the_conversion_step(self):
        warnings = footage_type.detect(self.log).warnings
        self.assertTrue(warnings)
        joined = ' '.join(warnings).lower()
        self.assertIn('conversion', joined)

    def test_display_produces_no_warnings(self):
        self.assertEqual(footage_type.detect(self.display).warnings, [])

    def test_describe_states_the_kind_explicitly(self):
        self.assertIn('LOG', footage_type.detect(self.log).describe())
        self.assertIn('display-referred',
                      footage_type.detect(self.display).describe())


class TestOverride(unittest.TestCase):
    """Detection is a default, not a verdict — the user knows their footage."""

    def test_can_be_forced_to_display(self):
        log = eval_scenes.as_log(eval_scenes.pristine())
        result = footage_type.detect(log, assume='display')
        self.assertEqual(result.kind, 'display')
        self.assertTrue(result.tone_targets_apply)
        self.assertTrue(result.overridden)

    def test_can_be_forced_to_log(self):
        result = footage_type.detect(eval_scenes.pristine(), assume='log')
        self.assertEqual(result.kind, 'log')
        self.assertFalse(result.tone_targets_apply)

    def test_rejects_an_unknown_override(self):
        with self.assertRaises(ValueError):
            footage_type.detect(eval_scenes.pristine(), assume='rec2020')

    def test_auto_is_the_default(self):
        result = footage_type.detect(eval_scenes.pristine(), assume='auto')
        self.assertFalse(result.overridden)


class TestRealFootageShape(unittest.TestCase):
    """Regression cases from real S-Log3 frames.

    The frames themselves are not committed (they are client footage), but
    their measured shape is, so the behaviour they exposed stays covered.
    """

    # Measured with footage_type.measure() from two real S-Log3 frames.
    C1640 = {'black_point': 0.1849, 'white_point': 0.6241, 'range': 0.4392,
             'median': 0.4641, 'midpoint_position': 0.6358, 'purity': 0.0592}
    C1645 = {'black_point': 0.1594, 'white_point': 0.6157, 'range': 0.4563,
             'median': 0.3848, 'midpoint_position': 0.4941, 'purity': 0.0818}

    def test_clear_real_log_is_detected(self):
        self.assertEqual(footage_type.classify(self.C1640).kind, 'log')

    def test_borderline_real_log_is_not_waved_through_as_display(self):
        """c1645 is genuinely log, but its median sits at 0.494 — below the
        threshold that separates a log curve from a rescaled display image.
        Shape alone cannot confirm it, so the honest answer is ambiguous, and
        the user is asked rather than silently given a wrong grade."""
        self.assertEqual(footage_type.classify(self.C1645).kind, 'ambiguous')

    def test_neither_real_frame_permits_tone_fitting(self):
        for stats in (self.C1640, self.C1645):
            with self.subTest(stats=stats['median']):
                self.assertFalse(footage_type.classify(stats).tone_targets_apply)

    def test_both_real_frames_warn(self):
        for stats in (self.C1640, self.C1645):
            with self.subTest(stats=stats['median']):
                self.assertTrue(footage_type.classify(stats).warnings)

    def test_stating_the_transfer_resolves_the_borderline_frame(self):
        result = footage_type.classify(self.C1645, assume='log')
        self.assertEqual(result.kind, 'log')
        self.assertTrue(result.overridden)


if __name__ == '__main__':
    unittest.main(verbosity=2)

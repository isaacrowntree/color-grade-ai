#!/usr/bin/env python3
"""test_eval.py — Evaluation set for closed-loop grading.

Every case takes a pristine scene, applies a known defect, asks the grader to
fix it, and measures how much of the defect actually went away. This is the
suite that makes "the analyzer got better" a measurable claim rather than an
impression.

Run: python3 test_eval.py
"""

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import eval_scenes
import grade_metrics
import solve_grade

HERE = os.path.dirname(os.path.abspath(__file__))


def graded(case):
    """Run the full closed loop for a case and return the three scenes."""
    base, degraded = eval_scenes.build(case)
    plan = solve_grade.solve(degraded)
    return base, degraded, plan.apply(degraded), plan


class TestMetrics(unittest.TestCase):
    """The measurements the optimiser minimises must themselves be sane."""

    def test_pristine_scene_scores_near_zero(self):
        base = eval_scenes.pristine()
        self.assertLess(grade_metrics.total_error(base), 0.05)

    def test_every_defect_raises_the_score(self):
        base = eval_scenes.pristine()
        clean = grade_metrics.total_error(base)
        for case in eval_scenes.CASES:
            with self.subTest(case=case):
                _, degraded = eval_scenes.build(case)
                self.assertGreater(grade_metrics.total_error(degraded), clean,
                                   f'{case} did not register as a defect')

    def test_white_balance_error_tracks_the_cast(self):
        base = eval_scenes.pristine()
        neutral = grade_metrics.white_balance_error(base)
        warm = grade_metrics.white_balance_error(
            eval_scenes.degrade(base, gains=(1.25, 1.0, 0.78)))
        self.assertLess(neutral, 0.03)
        self.assertGreater(warm, 0.10)

    def test_exposure_error_is_signed(self):
        base = eval_scenes.pristine()
        dark = grade_metrics.exposure_error(eval_scenes.degrade(base, gamma=1.6))
        bright = grade_metrics.exposure_error(eval_scenes.degrade(base, gamma=0.6))
        self.assertLess(dark, 0.0, 'a dark frame should read negative')
        self.assertGreater(bright, 0.0, 'a bright frame should read positive')

    def test_error_is_stable_under_reseeding(self):
        """Noise must not move the score meaningfully."""
        a = grade_metrics.total_error(eval_scenes.pristine(seed=1))
        b = grade_metrics.total_error(eval_scenes.pristine(seed=2))
        self.assertLess(abs(a - b), 0.02)


class TestSolverImproves(unittest.TestCase):
    """The headline claim: grading moves each scene toward its pristine form."""

    def test_every_case_improves(self):
        for case in eval_scenes.CASES:
            with self.subTest(case=case):
                base, degraded, result, _ = graded(case)
                before = grade_metrics.total_error(degraded)
                after = grade_metrics.total_error(result)
                self.assertLess(after, before,
                                f'{case}: {before:.3f} -> {after:.3f}')

    def test_every_case_recovers_most_of_the_defect(self):
        for case in eval_scenes.CASES:
            with self.subTest(case=case):
                base, degraded, result, _ = graded(case)
                before = grade_metrics.total_error(degraded)
                after = grade_metrics.total_error(result)
                recovered = (before - after) / before
                self.assertGreater(recovered, 0.40,
                                   f'{case}: recovered only {recovered:.0%}')

    def test_colour_casts_are_substantially_neutralised(self):
        for case in ('warm_tungsten', 'cool_daylight', 'green_led'):
            with self.subTest(case=case):
                _, degraded, result, _ = graded(case)
                before = grade_metrics.white_balance_error(degraded)
                after = grade_metrics.white_balance_error(result)
                self.assertLess(after, before * 0.6,
                                f'{case}: WB {before:.3f} -> {after:.3f}')

    def test_grading_a_clean_scene_does_little(self):
        base = eval_scenes.pristine()
        plan = solve_grade.solve(base)
        result = plan.apply(base)
        self.assertLess(np.abs(result - base).max(), 0.10,
                        'a correct scene should be left broadly alone')


class TestSolverBehaviour(unittest.TestCase):

    def test_plan_names_a_relevant_correction(self):
        expected = {
            'warm_tungsten': 'fitted_cool_shift',
            'cool_daylight': 'fitted_warm_shift',
            'green_led': 'fitted_green_fix',
            'magenta_stage': 'fitted_magenta_fix',
            'milky_blacks': 'fitted_black_crush',
            'underexposed': 'fitted_exposure_lift',
            'overexposed': 'fitted_exposure_pull',
        }
        for case, correction in expected.items():
            with self.subTest(case=case):
                *_, plan = graded(case)
                names = [s['preset'] for s in plan.chain]
                self.assertIn(correction, names, f'{case} chose {names}')

    def test_strengths_are_in_range(self):
        for case in eval_scenes.CASES:
            with self.subTest(case=case):
                *_, plan = graded(case)
                for step in plan.chain:
                    self.assertGreater(step['strength'], 0.0)
                    self.assertLessEqual(step['strength'], 1.5)

    def test_solved_strength_beats_the_old_heuristic(self):
        """Solving must actually outperform the magic constants it replaces."""
        wins = 0
        for case in eval_scenes.CASES:
            _, degraded = eval_scenes.build(case)
            solved = solve_grade.solve(degraded)
            heuristic = solve_grade.solve(degraded, optimise=False)
            if (grade_metrics.total_error(solved.apply(degraded)) <=
                    grade_metrics.total_error(heuristic.apply(degraded)) + 1e-9):
                wins += 1
        self.assertGreaterEqual(wins, len(eval_scenes.CASES) - 1,
                                f'solved beat heuristic in only {wins} cases')

    def test_solver_is_deterministic(self):
        _, degraded = eval_scenes.build('warm_and_dark')
        a = solve_grade.solve(degraded)
        b = solve_grade.solve(degraded)
        self.assertEqual([(s['preset'], s['strength']) for s in a.chain],
                         [(s['preset'], s['strength']) for s in b.chain])

    def test_plan_exports_a_usable_lut(self):
        import tempfile
        from lut_apply import CubeLUT

        _, degraded = eval_scenes.build('warm_tungsten')
        plan = solve_grade.solve(degraded)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'out.cube')
            plan.write_cube(path)
            self.assertTrue(os.path.exists(path))
            baked = CubeLUT.load(path).apply(degraded)

        # The exported LUT must match what the plan previewed.
        self.assertLess(np.abs(baked - plan.apply(degraded)).max(), 0.06)


class TestSkinDetection(unittest.TestCase):
    """Skin drives the most consequential correction, so it must be precise."""

    def test_finds_skin_in_the_evaluation_scene(self):
        base = eval_scenes.pristine()
        mask = grade_metrics.skin_mask(base)
        self.assertGreater(mask.mean(), 0.02, 'no skin found in a scene full of it')

    def test_rejects_wood_and_terracotta(self):
        """Warm non-skin surfaces are the classic false positive."""
        false_friends = [
            (0.55, 0.34, 0.16),   # varnished wood
            (0.70, 0.35, 0.22),   # terracotta
            (0.85, 0.62, 0.10),   # amber practical light
        ]
        for colour in false_friends:
            with self.subTest(colour=colour):
                patch = np.tile(np.array(colour), (64, 64, 1))
                mask = grade_metrics.skin_mask(patch)
                self.assertLess(mask.mean(), 0.5,
                                f'{colour} was classified as skin')

    def test_accepts_the_full_range_of_skin_tones(self):
        for tone in eval_scenes.SKIN_TONES:
            with self.subTest(tone=tone):
                patch = np.tile(np.array(tone), (64, 64, 1))
                mask = grade_metrics.skin_mask(patch)
                self.assertGreater(mask.mean(), 0.5,
                                   f'{tone} was not recognised as skin')

    def test_reports_confidence(self):
        base = eval_scenes.pristine()
        blue = np.tile(np.array((0.15, 0.2, 0.6)), (64, 64, 1))
        self.assertGreater(grade_metrics.skin_confidence(base),
                           grade_metrics.skin_confidence(blue))


class TestSparseSkinDoesNotDominate(unittest.TestCase):
    """Regression from real footage.

    On c1645_raw.png, 1,763 skin pixels — 0.021% of the frame — contributed 58%
    of the total error, while the solver skips skin fitting below 1%. The score
    was dominated by a term the optimiser was forbidden to touch, which is why
    real-footage recovery was 23% against 79% on synthetic scenes.
    """

    @staticmethod
    def scene_with_skin_fraction(fraction):
        """A neutral frame with a controlled patch of very red skin."""
        scene = np.full((200, 200, 3), 0.45)
        pixels = int(200 * 200 * fraction)
        if pixels:
            side = max(1, int(np.sqrt(pixels)))
            scene[:side, :side] = (0.60, 0.41, 0.39)  # red skin, hue ~6 deg
        return scene

    def test_a_handful_of_skin_pixels_is_ignored(self):
        sparse = self.scene_with_skin_fraction(0.0005)
        self.assertEqual(grade_metrics.skin_hue_error(sparse), 0.0,
                         'skin hue reported from a negligible sample')

    def test_the_reporting_and_fitting_thresholds_agree(self):
        """One constant, so the metric can never penalise what the solver is
        not allowed to correct."""
        just_under = self.scene_with_skin_fraction(
            grade_metrics.MIN_SKIN_FRACTION * 0.5)
        self.assertEqual(grade_metrics.skin_hue_error(just_under), 0.0)
        self.assertEqual(solve_grade.fit_skin(just_under), None)

    def test_ample_skin_is_still_measured_and_fitted(self):
        ample = self.scene_with_skin_fraction(0.25)
        self.assertGreater(grade_metrics.skin_hue_error(ample), 3.0)
        self.assertIsNotNone(solve_grade.fit_skin(ample))

    def test_sparse_skin_cannot_dominate_the_score(self):
        sparse = self.scene_with_skin_fraction(0.002)
        total = grade_metrics.total_error(sparse)
        skin_share = (grade_metrics.WEIGHTS['skin_hue'] *
                      grade_metrics.skin_hue_error(sparse) / 30.0)
        self.assertLess(skin_share, total * 0.25,
                        'a sliver of skin still dominates the score')

    def test_skin_contribution_scales_with_confidence(self):
        """Between the threshold and a solid sample, influence ramps rather
        than switching on at full weight."""
        marginal = grade_metrics.skin_term(self.scene_with_skin_fraction(0.012))
        ample = grade_metrics.skin_term(self.scene_with_skin_fraction(0.25))
        self.assertLess(marginal, ample)


class TestLogAwareSolving(unittest.TestCase):
    """Tone targets describe a graded Rec.709 image, not a log container."""

    def setUp(self):
        self.display = eval_scenes.pristine()
        self.log = eval_scenes.as_log(
            eval_scenes.degrade(self.display, gains=(1.22, 1.0, 0.78)))

    def test_log_footage_is_not_tone_fitted(self):
        plan = solve_grade.solve(self.log)
        fitted = [s['preset'] for s in plan.chain]
        for forbidden in ('fitted_exposure_lift', 'fitted_exposure_pull',
                          'fitted_black_crush'):
            self.assertNotIn(forbidden, fitted,
                             f'{forbidden} fitted against log footage')

    def test_log_plan_carries_the_warning(self):
        plan = solve_grade.solve(self.log)
        self.assertTrue(plan.warnings)
        self.assertIn('conversion', ' '.join(plan.warnings).lower())

    def test_log_plan_records_the_footage_type(self):
        plan = solve_grade.solve(self.log)
        self.assertEqual(plan.footage.kind, 'log')

    def test_display_footage_is_tone_fitted_normally(self):
        _, degraded = eval_scenes.build('warm_and_dark')
        plan = solve_grade.solve(degraded)
        fitted = [s['preset'] for s in plan.chain]
        self.assertTrue(any(f.startswith('fitted_exposure') for f in fitted))
        self.assertEqual(plan.warnings, [])

    def test_overriding_the_transfer_re_enables_tone_fitting(self):
        plan = solve_grade.solve(self.log, transfer='display')
        fitted = [s['preset'] for s in plan.chain]
        self.assertTrue(any(f.startswith('fitted_exposure') for f in fitted),
                        'explicit --transfer display should permit tone fitting')

    def test_white_balance_is_still_fitted_on_log(self):
        """A colour cast is a cast whatever the transfer curve."""
        plan = solve_grade.solve(self.log)
        self.assertTrue(any(s['preset'].startswith('fitted_') and 'shift' in s['preset']
                            or 'white_balance' in s['preset'] for s in plan.chain),
                        f'no white balance step in {[s["preset"] for s in plan.chain]}')

    def test_ambiguous_footage_is_held_back_too(self):
        flat = 0.25 + self.display * 0.5
        plan = solve_grade.solve(flat)
        fitted = [s['preset'] for s in plan.chain]
        self.assertNotIn('fitted_black_crush', fitted)
        self.assertTrue(plan.warnings)


if __name__ == '__main__':
    unittest.main(verbosity=2)

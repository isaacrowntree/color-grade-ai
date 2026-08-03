#!/usr/bin/env python3
"""test_auto_grade.py — Test suite for auto_grade.py frame analysis.

Uses synthetic frames with known color casts to verify that the analyzer
recommends the preset that moves the image *toward* neutral, not away.

Run: python3 test_auto_grade.py
"""

import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import auto_grade

HERE = os.path.dirname(os.path.abspath(__file__))


def synthetic_frame(r_gain=1.0, g_gain=1.0, b_gain=1.0, seed=0, size=(240, 320)):
    """Build a frame with a known multiplicative cast over a neutral base."""
    rng = np.random.default_rng(seed)
    base = rng.uniform(0.15, 0.75, size)
    img = np.stack([
        np.clip(base * r_gain, 0, 1),
        np.clip(base * g_gain, 0, 1),
        np.clip(base * b_gain, 0, 1),
    ], axis=-1)
    return (img * 255).astype('uint8')


def analyze_synthetic(**kwargs):
    """Write a synthetic frame to disk and run the full analyzer on it."""
    arr = synthetic_frame(**kwargs)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'frame.png')
        Image.fromarray(arr).save(path)
        return auto_grade.analyze_frame(path)


# Casts the analyzer must recognise. Each is defined by what is *wrong* with
# the scene; the expected preset is the one that corrects it.
WARM_SCENE = dict(r_gain=1.25, b_gain=0.72)     # red-heavy, blue-poor
COOL_SCENE = dict(r_gain=0.75, b_gain=1.25)     # blue-heavy, red-poor
GREEN_SCENE = dict(g_gain=1.20)                 # green-heavy (cheap LED)
MAGENTA_SCENE = dict(r_gain=1.12, b_gain=1.12)  # green-poor (pink stage light)
NEUTRAL_SCENE = dict()


class TestWhiteBalanceDirection(unittest.TestCase):
    """Node 3 must recommend the preset that neutralises the cast."""

    def test_warm_scene_recommends_cool_shift(self):
        wb = analyze_synthetic(**WARM_SCENE)['node3_white_balance']
        self.assertEqual(wb['preset_recommendation'], 'cool_shift')

    def test_cool_scene_recommends_warm_shift(self):
        wb = analyze_synthetic(**COOL_SCENE)['node3_white_balance']
        self.assertEqual(wb['preset_recommendation'], 'warm_shift')

    def test_green_scene_recommends_led_green_fix(self):
        wb = analyze_synthetic(**GREEN_SCENE)['node3_white_balance']
        self.assertEqual(wb['preset_recommendation'], 'led_green_fix')

    def test_magenta_scene_does_not_recommend_led_green_fix(self):
        """A magenta cast is the opposite of a green tint."""
        wb = analyze_synthetic(**MAGENTA_SCENE)['node3_white_balance']
        self.assertNotEqual(wb['preset_recommendation'], 'led_green_fix')

    def test_magenta_scene_recommends_pink_cast_fix(self):
        wb = analyze_synthetic(**MAGENTA_SCENE)['node3_white_balance']
        self.assertEqual(wb['preset_recommendation'], 'pink_cast_fix')

    def test_neutral_scene_recommends_nothing(self):
        wb = analyze_synthetic(**NEUTRAL_SCENE)['node3_white_balance']
        self.assertEqual(wb['preset_recommendation'], 'none')
        self.assertEqual(wb['recommended_strength'], 0)

    def test_gain_convention_is_corrective(self):
        """gain < 1 means that channel is in excess and must be reduced."""
        wb = analyze_synthetic(**WARM_SCENE)['node3_white_balance']
        gains = wb['blended_gains']
        self.assertLess(gains['r'], 1.0, "warm scene has excess red → r gain < 1")
        self.assertGreater(gains['b'], 1.0, "warm scene lacks blue → b gain > 1")

    def test_direction_text_agrees_with_preset(self):
        """The human-readable direction must not contradict the preset."""
        for label, scene, preset in [
            ('warm', WARM_SCENE, 'cool_shift'),
            ('cool', COOL_SCENE, 'warm_shift'),
            ('green', GREEN_SCENE, 'led_green_fix'),
            ('magenta', MAGENTA_SCENE, 'pink_cast_fix'),
        ]:
            with self.subTest(scene=label):
                wb = analyze_synthetic(**scene)['node3_white_balance']
                self.assertIn(preset, wb['direction'],
                              f"direction {wb['direction']!r} should name {preset}")


class TestSummaryContract(unittest.TestCase):
    """The summary loop reads a fixed set of keys from every node."""

    REQUIRED_KEYS = ('assessment', 'preset_recommendation', 'recommended_strength')
    NODE_KEYS = ('node2_contrast', 'node3_white_balance', 'node4_skin',
                 'node5_saturation', 'node6_black_level')

    def test_every_node_exposes_the_summary_keys(self):
        for scene in (WARM_SCENE, COOL_SCENE, GREEN_SCENE, NEUTRAL_SCENE):
            results = analyze_synthetic(**scene)
            for node in self.NODE_KEYS:
                for key in self.REQUIRED_KEYS:
                    with self.subTest(node=node, key=key):
                        self.assertIn(key, results[node])

    def test_analyze_does_not_crash_on_a_colour_cast(self):
        """Regression: the summary loop used to KeyError on node3."""
        for label, scene in [('warm', WARM_SCENE), ('cool', COOL_SCENE),
                             ('green', GREEN_SCENE), ('magenta', MAGENTA_SCENE)]:
            with self.subTest(scene=label):
                results = analyze_synthetic(**scene)
                self.assertIn('summary', results)

    def test_cast_scene_produces_a_chain_entry(self):
        results = analyze_synthetic(**WARM_SCENE)
        nodes = [s['node'] for s in results['summary']['recommended_chain']]
        self.assertIn('White Balance', nodes)

    def test_print_report_renders_a_cast_scene(self):
        """print_report indexes the same keys — it must not crash either."""
        import contextlib
        import io
        results = analyze_synthetic(**WARM_SCENE)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            auto_grade.print_report(results)
        self.assertIn('WHITE BALANCE', buf.getvalue())


class TestRecommendationsResolve(unittest.TestCase):
    """Every preset the analyzer can name must exist in presets.yml."""

    @staticmethod
    def preset_names():
        path = os.path.join(HERE, 'presets.yml')
        names = set()
        with open(path, encoding='utf-8') as f:
            for line in f:
                if line[:1].isalpha() and line.rstrip('\r\n').endswith(':'):
                    names.add(line.split(':')[0].strip())
        return names

    def test_presets_yml_parses(self):
        self.assertGreater(len(self.preset_names()), 10)

    def test_recommended_presets_exist(self):
        available = self.preset_names()
        for scene in (WARM_SCENE, COOL_SCENE, GREEN_SCENE, MAGENTA_SCENE,
                      NEUTRAL_SCENE):
            results = analyze_synthetic(**scene)
            for node, data in results.items():
                if node == 'summary':
                    continue
                preset = data['preset_recommendation']
                if preset == 'none':
                    continue
                with self.subTest(node=node, preset=preset):
                    self.assertIn(preset, available)


class TestHsvConversion(unittest.TestCase):
    """rgb_to_hsv underpins skin detection — verify against known values."""

    def test_primaries(self):
        cases = [
            ((1.0, 0.0, 0.0), 0.0),
            ((0.0, 1.0, 0.0), 120.0),
            ((0.0, 0.0, 1.0), 240.0),
            ((1.0, 1.0, 0.0), 60.0),
            ((0.0, 1.0, 1.0), 180.0),
            ((1.0, 0.0, 1.0), 300.0),
        ]
        for (rgb, expected_h) in cases:
            with self.subTest(rgb=rgb):
                r, g, b = (np.array([[v]]) for v in rgb)
                h, s, v = auto_grade.rgb_to_hsv(r, g, b)
                self.assertAlmostEqual(float(h[0, 0]), expected_h, places=4)
                self.assertAlmostEqual(float(s[0, 0]), 1.0, places=4)

    def test_grey_has_zero_saturation(self):
        r = g = b = np.array([[0.5]])
        h, s, v = auto_grade.rgb_to_hsv(r, g, b)
        self.assertAlmostEqual(float(s[0, 0]), 0.0, places=6)
        self.assertAlmostEqual(float(v[0, 0]), 0.5, places=6)

    def test_hue_is_never_negative(self):
        arr = synthetic_frame(r_gain=1.1, b_gain=0.9, seed=3) / 255.0
        h, s, v = auto_grade.rgb_to_hsv(arr[:, :, 0], arr[:, :, 1], arr[:, :, 2])
        self.assertGreaterEqual(float(h.min()), 0.0)
        self.assertLess(float(h.max()), 360.0)


class TestSkinAnalysis(unittest.TestCase):

    @staticmethod
    def skin_frame(hue_deg):
        """A frame filled with a mid-tone patch at a given hue."""
        import colorsys
        r, g, b = colorsys.hsv_to_rgb(hue_deg / 360.0, 0.35, 0.6)
        arr = np.zeros((240, 320, 3))
        arr[:, :, 0], arr[:, :, 1], arr[:, :, 2] = r, g, b
        # Add mild noise so percentile maths has a distribution to work with.
        rng = np.random.default_rng(1)
        arr = np.clip(arr + rng.normal(0, 0.02, arr.shape), 0, 1)
        return (arr * 255).astype('uint8')

    def analyze_skin(self, hue_deg):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'skin.png')
            Image.fromarray(self.skin_frame(hue_deg)).save(path)
            return auto_grade.analyze_frame(path)['node4_skin']

    def test_red_skin_is_flagged(self):
        node = self.analyze_skin(5)
        self.assertEqual(node['preset_recommendation'], 'red_skin_fix')

    def test_natural_skin_needs_no_fix(self):
        node = self.analyze_skin(20)
        self.assertEqual(node['preset_recommendation'], 'none')

    def test_no_skin_pixels_is_handled(self):
        """A pure blue frame has no skin — must not raise."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'blue.png')
            Image.fromarray(synthetic_frame(r_gain=0.1, g_gain=0.1)).save(path)
            node = auto_grade.analyze_frame(path)['node4_skin']
        self.assertEqual(node['preset_recommendation'], 'none')
        self.assertIn('assessment', node)


class TestExposureAnalysis(unittest.TestCase):

    def analyze_at(self, scale):
        rng = np.random.default_rng(7)
        base = np.clip(rng.uniform(0.1, 0.9, (240, 320)) * scale, 0, 1)
        arr = (np.stack([base] * 3, axis=-1) * 255).astype('uint8')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'exp.png')
            Image.fromarray(arr).save(path)
            return auto_grade.analyze_frame(path)['node2_contrast']

    def test_dark_frame_reads_as_underexposed(self):
        node = self.analyze_at(0.35)
        self.assertEqual(node['assessment'], 'underexposed')
        self.assertEqual(node['preset_recommendation'], 'underexposure_fix')

    def test_bright_frame_reads_as_overexposed(self):
        node = self.analyze_at(1.6)
        self.assertIn(node['assessment'], ('slightly bright', 'overexposed'))

    def test_gamma_below_one_brightens(self):
        """gamma is applied as out = in**gamma, so a dark frame needs < 1."""
        node = self.analyze_at(0.35)
        self.assertLess(node['gamma_recommendation'], 1.0)


class TestSkinDetectorIsShared(unittest.TestCase):
    """Node 4 must use the YCbCr locus detector, not its own HSV box.

    Two detectors would mean the reported skin hue and the fitted skin
    correction could disagree about which pixels are skin.
    """

    @staticmethod
    def patch(rgb):
        return (np.tile(np.array(rgb), (96, 96, 1)) * 255).astype('uint8')

    def analyze_patch(self, rgb):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'p.png')
            Image.fromarray(self.patch(rgb)).save(path)
            return auto_grade.analyze_frame(path)

    def test_wood_is_not_reported_as_skin(self):
        node = self.analyze_patch((0.55, 0.34, 0.16))['node4_skin']
        self.assertLess(node['skin_pixels_pct'], 50.0,
                        'varnished wood classified as skin')

    def test_amber_practical_is_not_reported_as_skin(self):
        node = self.analyze_patch((0.85, 0.62, 0.10))['node4_skin']
        self.assertLess(node['skin_pixels_pct'], 50.0)

    def test_real_skin_is_reported(self):
        node = self.analyze_patch((0.72, 0.53, 0.43))['node4_skin']
        self.assertGreater(node['skin_pixels_pct'], 50.0)

    def test_khaki_is_not_reported_as_skin(self):
        """Khaki sits inside the old HSV box (H=49, S=0.38, V=0.45) but well
        off the YCbCr skin locus, so it only passes with the shared detector."""
        node = self.analyze_patch((0.45, 0.42, 0.28))['node4_skin']
        self.assertLess(node['skin_pixels_pct'], 50.0,
                        'khaki classified as skin')

    def test_agrees_with_grade_metrics(self):
        import grade_metrics
        for rgb in [(0.72, 0.53, 0.43), (0.55, 0.34, 0.16), (0.36, 0.24, 0.18),
                    (0.45, 0.42, 0.28), (0.86, 0.68, 0.58)]:
            with self.subTest(rgb=rgb):
                arr = self.patch(rgb)
                reported = self.analyze_patch(rgb)['node4_skin']['skin_pixels_pct']
                shared = grade_metrics.skin_confidence(arr) * 100
                self.assertAlmostEqual(reported, shared, delta=1.0)


class TestSaturationAgreesWithTheSolver(unittest.TestCase):
    """The report and the solver must not disagree about saturation.

    Node 5 used a fixed target of 45, which told a correct scene measuring 63.8
    to desaturate — the exact judgement the solver was redesigned to avoid.
    """

    def analyze_scene(self, scene):
        import eval_scenes
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'scene.png')
            Image.fromarray(eval_scenes.as_uint8(scene)).save(path)
            return auto_grade.analyze_frame(path)['node5_saturation']

    def test_a_correct_scene_is_not_told_to_desaturate(self):
        import eval_scenes
        node = self.analyze_scene(eval_scenes.pristine())
        self.assertEqual(node['preset_recommendation'], 'none',
                         f"correct scene told to {node['preset_recommendation']}")

    def test_a_washed_out_scene_is_told_to_boost(self):
        import eval_scenes
        _, washed = eval_scenes.build('washed_out')
        self.assertEqual(self.analyze_scene(washed)['preset_recommendation'],
                         'sat_boost')

    def test_an_oversaturated_scene_is_told_to_reduce(self):
        import eval_scenes
        _, hot = eval_scenes.build('oversaturated')
        self.assertEqual(self.analyze_scene(hot)['preset_recommendation'],
                         'sat_reduce')

    def test_it_reports_the_shared_band(self):
        import eval_scenes
        import grade_metrics
        node = self.analyze_scene(eval_scenes.pristine())
        self.assertEqual(tuple(node['plausible_band']),
                         grade_metrics.SATURATION_BAND)


class TestEmitIntegration(unittest.TestCase):
    """`--emit` must close the loop: frame in, working LUT out."""

    def setUp(self):
        import eval_scenes
        self.base, self.degraded = eval_scenes.build('warm_and_dark')

    def test_emit_writes_a_lut_that_improves_the_frame(self):
        import grade_metrics
        from lut_apply import CubeLUT

        with tempfile.TemporaryDirectory() as tmp:
            frame = os.path.join(tmp, 'frame.png')
            out = os.path.join(tmp, 'fix.cube')
            Image.fromarray(
                (self.degraded * 255).astype('uint8')).save(frame)

            rc = auto_grade.main([frame, '--emit', out])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.exists(out))

            graded = CubeLUT.load(out).apply(self.degraded)

        before = grade_metrics.total_error(self.degraded)
        after = grade_metrics.total_error(graded)
        self.assertLess(after, before * 0.6,
                        f'emitted LUT barely helped: {before:.3f} -> {after:.3f}')

    def test_emitted_lut_is_a_valid_cube(self):
        with tempfile.TemporaryDirectory() as tmp:
            frame = os.path.join(tmp, 'frame.png')
            out = os.path.join(tmp, 'fix.cube')
            Image.fromarray((self.degraded * 255).astype('uint8')).save(frame)
            auto_grade.main([frame, '--emit', out])

            with open(out) as f:
                content = f.read()

        self.assertIn('LUT_3D_SIZE', content)
        data_lines = [l for l in content.splitlines() if l[:1].isdigit()]
        self.assertEqual(len(data_lines), 33 ** 3)

    def test_analysis_still_prints_without_emit(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            frame = os.path.join(tmp, 'frame.png')
            Image.fromarray((self.degraded * 255).astype('uint8')).save(frame)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = auto_grade.main([frame])
        self.assertEqual(rc, 0)
        self.assertIn('WHITE BALANCE', buf.getvalue())


if __name__ == '__main__':
    unittest.main(verbosity=2)

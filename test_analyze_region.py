#!/usr/bin/env python3
"""test_analyze_region.py — Tests for region sampling.

This tool had no tests and was broken: a Pillow deprecation warning landed on
the same stream as its JSON output and the whole thing failed to parse, while
still exiting 0. These cover the measurements and the wrapper contract.

Run: python3 test_analyze_region.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import analyze_region

HERE = os.path.dirname(os.path.abspath(__file__))


def solid(rgb, size=(80, 120)):
    arr = np.zeros((size[0], size[1], 3))
    arr[:, :] = rgb
    return arr


class TestMeasurements(unittest.TestCase):

    def test_average_rgb_of_a_flat_patch(self):
        result = analyze_region.analyze(solid((0.5, 0.25, 0.75)),
                                        (0, 0, 120, 80))
        self.assertAlmostEqual(result['avg_rgb']['r'], 127.5, delta=0.6)
        self.assertAlmostEqual(result['avg_rgb']['g'], 63.8, delta=0.6)
        self.assertAlmostEqual(result['avg_rgb']['b'], 191.2, delta=0.6)

    def test_pixel_count_matches_the_region(self):
        result = analyze_region.analyze(solid((0.4, 0.4, 0.4)), (10, 10, 40, 30))
        self.assertEqual(result['pixel_count'], (40 - 10) * (30 - 10))

    def test_known_hues(self):
        for rgb, hue in [((1, 0, 0), 0), ((0, 1, 0), 120), ((0, 0, 1), 240)]:
            with self.subTest(rgb=rgb):
                result = analyze_region.analyze(solid(rgb), (0, 0, 120, 80))
                self.assertAlmostEqual(result['avg_hsv']['h'], hue, delta=0.5)

    def test_reports_skin_fraction(self):
        skin = analyze_region.analyze(solid((0.72, 0.53, 0.43)), (0, 0, 120, 80))
        wood = analyze_region.analyze(solid((0.55, 0.34, 0.16)), (0, 0, 120, 80))
        self.assertGreater(skin['skin_fraction'], 0.9)
        self.assertLess(wood['skin_fraction'], 0.1)


class TestHueWrapping(unittest.TestCase):
    """Reds straddle 0/360, and reds are most of what this tool looks at."""

    def test_mean_hue_of_reds_does_not_land_on_cyan(self):
        arr = np.zeros((40, 40, 3))
        arr[:20] = (1.0, 0.06, 0.0)    # hue ~3
        arr[20:] = (1.0, 0.0, 0.06)    # hue ~357
        result = analyze_region.analyze(arr, (0, 0, 40, 40))
        mean = result['hue']['mean']
        self.assertTrue(mean < 10 or mean > 350,
                        f'mean hue of reds came out at {mean}')

    def test_spread_is_small_for_a_consistent_hue(self):
        result = analyze_region.analyze(solid((0.8, 0.4, 0.2)), (0, 0, 120, 80))
        self.assertLess(result['hue']['spread'], 1.0)

    def test_a_perfectly_uniform_hue_does_not_produce_nan(self):
        """The resultant length rounds just above 1, and sqrt(-2*log(1+eps))
        is NaN — which serialises as bare `NaN` and is not valid JSON."""
        result = analyze_region.analyze(solid((0.6, 0.4, 0.3)), (0, 0, 120, 80))
        self.assertFalse(np.isnan(result['hue']['spread']))
        json.dumps(result)  # would raise on a NaN under allow_nan=False
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False))
                         ['hue']['spread'], result['hue']['spread'])

    def test_spread_is_large_for_mixed_hues(self):
        arr = np.zeros((40, 40, 3))
        arr[:20] = (1.0, 0.0, 0.0)
        arr[20:] = (0.0, 0.0, 1.0)
        result = analyze_region.analyze(arr, (0, 0, 40, 40))
        self.assertGreater(result['hue']['spread'], 30.0)


class TestRegionHandling(unittest.TestCase):

    def test_region_is_clamped_to_the_image(self):
        result = analyze_region.analyze(solid((0.5, 0.5, 0.5)),
                                        (-50, -50, 5000, 5000))
        self.assertEqual(result['region'], [0, 0, 120, 80])

    def test_reversed_coordinates_are_normalised(self):
        forward = analyze_region.analyze(solid((0.3, 0.6, 0.9)), (10, 10, 40, 30))
        reversed_ = analyze_region.analyze(solid((0.3, 0.6, 0.9)), (40, 30, 10, 10))
        self.assertEqual(forward['region'], reversed_['region'])

    def test_an_empty_region_raises(self):
        with self.assertRaises(ValueError):
            analyze_region.analyze(solid((0.5, 0.5, 0.5)), (10, 10, 10, 10))


class TestCliContract(unittest.TestCase):
    """stdout must carry JSON and nothing else — the bug that broke this tool."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.frame = os.path.join(self.tmp.name, 'frame.png')
        Image.fromarray(
            (solid((0.6, 0.4, 0.3)) * 255).astype('uint8')).save(self.frame)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stdout_is_parseable_json(self):
        result = subprocess.run(
            [sys.executable, 'analyze_region.py', self.frame, '0,0,60,40', 'x'],
            capture_output=True, text=True, cwd=HERE)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['label'], 'x')

    def test_a_bad_region_fails_loudly(self):
        result = subprocess.run(
            [sys.executable, 'analyze_region.py', self.frame, 'nonsense'],
            capture_output=True, text=True, cwd=HERE)
        self.assertNotEqual(result.returncode, 0)

    def test_the_ruby_wrapper_runs(self):
        result = subprocess.run(
            ['ruby', 'analyze_frame.rb', self.frame, '0,0,60,40', 'patch'],
            capture_output=True, text=True, cwd=HERE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('=== PATCH ===', result.stdout)
        self.assertIn('Skin:', result.stdout)

    def test_the_ruby_wrapper_survives_a_python_warning(self):
        """A warning on stderr must not corrupt the JSON parse."""
        env = dict(os.environ, PYTHONWARNINGS='always')
        result = subprocess.run(
            ['ruby', 'analyze_frame.rb', self.frame, '0,0,60,40'],
            capture_output=True, text=True, cwd=HERE, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('=== SAMPLE ===', result.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)

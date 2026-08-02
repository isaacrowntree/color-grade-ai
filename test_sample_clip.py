#!/usr/bin/env python3
"""test_sample_clip.py — Tests for clip-level sampling and aggregation.

Grading from a single arbitrary frame assumes the whole clip looks like that
frame. These tests build real video files with ffmpeg and check that sampling
across a clip behaves sensibly, including when the clip contains a cut.

Skipped automatically when ffmpeg is unavailable.

Run: python3 test_sample_clip.py
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import eval_scenes
import grade_metrics
import sample_clip

HAS_FFMPEG = shutil.which('ffmpeg') is not None


def encode(frames, path, fps=24):
    """Encode a list of float arrays to a lossless video file."""
    with tempfile.TemporaryDirectory() as tmp:
        for i, frame in enumerate(frames):
            Image.fromarray(eval_scenes.as_uint8(frame)).save(
                os.path.join(tmp, f'{i:05d}.png'))
        subprocess.run(
            ['ffmpeg', '-y', '-loglevel', 'error', '-framerate', str(fps),
             '-i', os.path.join(tmp, '%05d.png'),
             '-c:v', 'ffv1', '-pix_fmt', 'gbrp', path],
            check=True, capture_output=True,
        )
    return path


@unittest.skipUnless(HAS_FFMPEG, 'ffmpeg not available')
class TestSampling(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base, degraded = eval_scenes.build('warm_tungsten')
        cls.base = base
        cls.degraded = degraded

        # A uniform clip: 48 identical frames of the same degraded scene.
        cls.uniform = encode([degraded] * 48,
                             os.path.join(cls.tmp.name, 'uniform.mkv'))

        # A two-shot clip: warm first half, cool second half.
        _, cool = eval_scenes.build('cool_daylight')
        cls.two_shot = encode([degraded] * 24 + [cool] * 24,
                              os.path.join(cls.tmp.name, 'two_shot.mkv'))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_samples_the_requested_number_of_frames(self):
        frames = sample_clip.sample_frames(self.uniform, count=8)
        self.assertEqual(len(frames), 8)

    def test_samples_span_the_clip(self):
        """Samples must be spread out, not all taken from the head."""
        stamps = sample_clip.sample_timestamps(self.uniform, count=6)
        self.assertEqual(len(stamps), 6)
        self.assertGreater(stamps[-1] - stamps[0], 0.5)
        self.assertTrue(all(b > a for a, b in zip(stamps, stamps[1:])),
                        'timestamps must increase')

    def test_never_samples_more_frames_than_exist(self):
        frames = sample_clip.sample_frames(self.uniform, count=500)
        self.assertLessEqual(len(frames), 48)
        self.assertGreater(len(frames), 0)

    def test_frames_round_trip_through_the_codec(self):
        frames = sample_clip.sample_frames(self.uniform, count=3)
        for frame in frames:
            self.assertEqual(frame.shape, self.degraded.shape)
            self.assertLess(np.abs(frame - self.degraded).mean(), 0.02)


@unittest.skipUnless(HAS_FFMPEG, 'ffmpeg not available')
class TestAggregation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        _, cls.degraded = eval_scenes.build('warm_tungsten')
        cls.uniform = encode([cls.degraded] * 36,
                             os.path.join(cls.tmp.name, 'uniform.mkv'))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_uniform_clip_matches_its_single_frame(self):
        clip = sample_clip.analyze_clip(self.uniform, count=6)
        single = grade_metrics.measure(self.degraded)
        for key in ('white_balance', 'exposure', 'black_level'):
            with self.subTest(key=key):
                self.assertAlmostEqual(clip['aggregate'][key], single[key],
                                       delta=0.03)

    def test_reports_per_frame_measurements(self):
        clip = sample_clip.analyze_clip(self.uniform, count=5)
        self.assertEqual(len(clip['frames']), 5)
        for entry in clip['frames']:
            self.assertIn('white_balance', entry)
            self.assertIn('timestamp', entry)

    def test_uniform_clip_reports_low_variation(self):
        clip = sample_clip.analyze_clip(self.uniform, count=6)
        self.assertLess(clip['variation']['white_balance'], 0.02)
        self.assertFalse(clip['inconsistent'])

    def test_aggregate_uses_the_median_not_the_mean(self):
        """One blown frame must not drag the whole clip's grade."""
        values = [0.10, 0.11, 0.10, 0.12, 0.95]
        self.assertAlmostEqual(sample_clip.aggregate_value(values), 0.11,
                               delta=0.02)


@unittest.skipUnless(HAS_FFMPEG, 'ffmpeg not available')
class TestSceneChange(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        _, warm = eval_scenes.build('warm_tungsten')
        _, cool = eval_scenes.build('cool_daylight')
        cls.two_shot = encode([warm] * 24 + [cool] * 24,
                              os.path.join(cls.tmp.name, 'two_shot.mkv'))
        cls.uniform = encode([warm] * 48,
                             os.path.join(cls.tmp.name, 'uniform.mkv'))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_flags_a_clip_with_two_different_looks(self):
        clip = sample_clip.analyze_clip(self.two_shot, count=8)
        self.assertTrue(clip['inconsistent'],
                        'a two-shot clip should be flagged as inconsistent')

    def test_does_not_flag_a_consistent_clip(self):
        clip = sample_clip.analyze_clip(self.uniform, count=8)
        self.assertFalse(clip['inconsistent'])

    def test_warns_in_the_report(self):
        clip = sample_clip.analyze_clip(self.two_shot, count=8)
        self.assertTrue(clip['warnings'])
        self.assertIn('varies', ' '.join(clip['warnings']).lower())


@unittest.skipUnless(HAS_FFMPEG, 'ffmpeg not available')
class TestClipGrading(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        _, cls.degraded = eval_scenes.build('warm_and_dark')
        cls.clip = encode([cls.degraded] * 30,
                          os.path.join(cls.tmp.name, 'clip.mkv'))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_solves_a_grade_for_the_whole_clip(self):
        from lut_apply import CubeLUT

        out = os.path.join(self.tmp.name, 'clip.cube')
        plan = sample_clip.solve_clip(self.clip, count=5)
        plan.write_cube(out)

        graded = CubeLUT.load(out).apply(self.degraded)
        before = grade_metrics.total_error(self.degraded)
        after = grade_metrics.total_error(graded)
        self.assertLess(after, before * 0.6,
                        f'clip grade barely helped: {before:.3f} -> {after:.3f}')

    def test_clip_grade_is_close_to_single_frame_grade_when_uniform(self):
        import solve_grade
        clip_plan = sample_clip.solve_clip(self.clip, count=5)
        frame_plan = solve_grade.solve(self.degraded)
        self.assertEqual([s['preset'] for s in clip_plan.chain],
                         [s['preset'] for s in frame_plan.chain])


class TestWithoutFfmpeg(unittest.TestCase):

    def test_missing_file_raises_a_clear_error(self):
        with self.assertRaises(FileNotFoundError):
            sample_clip.sample_timestamps('/nonexistent/clip.mov', count=4)


if __name__ == '__main__':
    unittest.main(verbosity=2)

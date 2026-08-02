#!/usr/bin/env python3
"""test_lut_apply.py — Tests for the Python .cube reader/applier.

The strongest available check is cross-language parity: generate a LUT with the
Ruby pipeline, apply it here, and compare against running the Ruby pipeline
directly on the same values. If the two ever disagree, the closed-loop grading
built on top of this module is optimising against the wrong image.

Run: python3 test_lut_apply.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lut_apply

HERE = os.path.dirname(os.path.abspath(__file__))


def ruby_pipeline(preset, rgb_values, strength=1.0, legacy=False):
    """Run the Ruby pipeline directly on a list of [r, g, b] triples."""
    # Note the symbol literal: "'.to_sym" on ":linear" yields :":linear", which
    # silently falls through to the legacy handlers.
    model = ':hsl' if legacy else ':linear'
    script = f"""
    require 'json'
    require_relative 'generate_lut'
    preset = load_presets['{preset}']
    vals = JSON.parse(STDIN.read)
    out = vals.map {{ |r, g, b| apply_pipeline(r, g, b, preset['pipeline'], {strength}, color_model: {model}) }}
    puts JSON.generate(out)
    """
    result = subprocess.run(
        ['ruby', '-rjson', '-e', script],
        input=json.dumps(rgb_values), capture_output=True, text=True, cwd=HERE,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return np.array(json.loads(result.stdout.strip().splitlines()[-1]))


def generate_cube(preset, path, strength=1.0, size=33):
    subprocess.run(
        ['ruby', 'generate_lut.rb', preset, path, f'--strength={strength}',
         f'--size={size}'],
        check=True, capture_output=True, cwd=HERE,
    )


class TestCubeParsing(unittest.TestCase):

    def test_parses_size_and_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'black_crush.cube')
            generate_cube('black_crush', path)
            lut = lut_apply.CubeLUT.load(path)
        self.assertEqual(lut.size, 33)
        self.assertEqual(lut.table.shape, (33 * 33 * 33, 3))

    def test_ignores_comments_and_title(self):
        content = "# a comment\nTITLE \"x\"\nLUT_3D_SIZE 2\n\n"
        content += "\n".join("0.0 0.0 0.0" for _ in range(8))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'tiny.cube')
            with open(path, 'w') as f:
                f.write(content)
            lut = lut_apply.CubeLUT.load(path)
        self.assertEqual(lut.size, 2)
        self.assertEqual(len(lut.table), 8)

    def test_rejects_truncated_table(self):
        content = "LUT_3D_SIZE 2\n" + "\n".join("0.0 0.0 0.0" for _ in range(5))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'bad.cube')
            with open(path, 'w') as f:
                f.write(content)
            with self.assertRaises(ValueError):
                lut_apply.CubeLUT.load(path)


class TestIdentity(unittest.TestCase):

    def test_identity_lut_is_a_no_op(self):
        lut = lut_apply.CubeLUT.identity(17)
        rng = np.random.default_rng(0)
        img = rng.uniform(0, 1, (32, 32, 3))
        out = lut.apply(img)
        self.assertLess(np.abs(out - img).max(), 1e-6)

    def test_identity_preserves_uint8_images(self):
        lut = lut_apply.CubeLUT.identity(33)
        rng = np.random.default_rng(1)
        img = rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
        out = lut.apply(img)
        self.assertEqual(out.dtype, np.uint8)
        self.assertLessEqual(np.abs(out.astype(int) - img.astype(int)).max(), 1)


class TestRubyParity(unittest.TestCase):
    """A LUT applied here must match the pipeline that generated it."""

    # Values are chosen off the LUT grid so interpolation is exercised.
    SAMPLES = [
        [0.13, 0.47, 0.81], [0.62, 0.29, 0.35], [0.05, 0.05, 0.05],
        [0.94, 0.88, 0.71], [0.5, 0.5, 0.5], [0.31, 0.66, 0.22],
    ]

    def check(self, preset, tolerance, size=65, strength=1.0):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, f'{preset}.cube')
            generate_cube(preset, path, strength=strength, size=size)
            lut = lut_apply.CubeLUT.load(path)

            img = np.array(self.SAMPLES, dtype=np.float64).reshape(1, -1, 3)
            got = lut.apply(img).reshape(-1, 3)

        expected = ruby_pipeline(preset, self.SAMPLES, strength=strength)
        max_err = np.abs(got - expected).max()
        self.assertLess(max_err, tolerance,
                        f"{preset}: max error {max_err:.5f}")
        return max_err

    def test_black_crush_matches_ruby(self):
        self.check('black_crush', 0.01)

    def test_studio_punch_matches_ruby(self):
        self.check('studio_punch', 0.01)

    def test_red_skin_fix_matches_ruby(self):
        # Hue-targeted presets have sharp transitions; a coarse grid cannot
        # represent them exactly, so allow more headroom.
        self.check('red_skin_fix', 0.03)

    def test_sat_boost_matches_ruby(self):
        self.check('sat_boost', 0.01)

    def test_accuracy_improves_with_grid_size(self):
        coarse = self.check('film_contrast', 0.05, size=17)
        fine = self.check('film_contrast', 0.05, size=65)
        self.assertLess(fine, coarse + 1e-9,
                        "a finer LUT should not be less accurate")


class TestChaining(unittest.TestCase):

    def test_applying_two_luts_matches_a_baked_chain(self):
        rng = np.random.default_rng(2)
        img = rng.uniform(0.05, 0.95, (24, 24, 3))

        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, 'a.cube')
            b = os.path.join(tmp, 'b.cube')
            baked = os.path.join(tmp, 'baked.cube')
            generate_cube('studio_punch', a, size=65)
            generate_cube('sat_boost', b, size=65)
            subprocess.run(
                ['ruby', 'generate_chain_lut.rb', baked,
                 'studio_punch@1.0', 'sat_boost@1.0'],
                check=True, capture_output=True, cwd=HERE,
            )
            stepwise = lut_apply.CubeLUT.load(b).apply(
                lut_apply.CubeLUT.load(a).apply(img))
            single = lut_apply.CubeLUT.load(baked).apply(img)

        # Not identical — the baked chain interpolates once, the pair twice —
        # but they must describe the same grade.
        self.assertLess(np.abs(stepwise - single).max(), 0.05)


class TestStrengthSemantics(unittest.TestCase):
    """Strength must interpolate parameters, matching the CLI, not results."""

    def test_strength_matches_cli_not_a_result_lerp(self):
        samples = TestRubyParity.SAMPLES
        with tempfile.TemporaryDirectory() as tmp:
            half = os.path.join(tmp, 'half.cube')
            generate_cube('studio_punch', half, strength=0.5, size=65)
            img = np.array(samples, dtype=np.float64).reshape(1, -1, 3)
            got = lut_apply.CubeLUT.load(half).apply(img).reshape(-1, 3)

        expected = ruby_pipeline('studio_punch', samples, strength=0.5)
        self.assertLess(np.abs(got - expected).max(), 0.01)

    def test_result_lerp_is_not_equivalent_to_parameter_interpolation(self):
        """The mistake preview.html currently makes, quantified.

        Swept over the whole cube, not a neutral ramp: on greys the two agree to
        within ~0.04, but on saturated colours they diverge by a quarter of the
        range. A preview that only ever showed greys would look fine.
        """
        axis = [i / 8.0 for i in range(9)]
        cube = [[r, g, b] for r in axis for g in axis for b in axis]

        half = ruby_pipeline('studio_punch', cube, strength=0.5)
        full = ruby_pipeline('studio_punch', cube, strength=1.0)
        naive = np.array(cube) + (full - np.array(cube)) * 0.5

        per_sample = np.abs(naive - half).max(axis=1)
        divergence = per_sample.max()
        self.assertGreater(divergence, 0.05,
                           f'expected a material gap, got {divergence:.4f}')

        # Neutrals are where it looks harmless — record that contrast so the
        # test documents why this was easy to miss.
        neutral_idx = [i for i, c in enumerate(cube) if c[0] == c[1] == c[2]]
        neutral_gap = per_sample[neutral_idx].max()
        self.assertLess(neutral_gap, divergence / 2,
                        'expected greys to diverge far less than colours')


if __name__ == '__main__':
    unittest.main(verbosity=2)

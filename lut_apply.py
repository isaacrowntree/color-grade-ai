#!/usr/bin/env python3
"""lut_apply.py — Read and apply .cube 3D LUTs in Python.

Closing the grading loop needs the ability to apply a candidate LUT to a frame
and re-measure it, which means the analyzer side needs its own LUT engine.
Trilinear interpolation, matching what Resolve, Premiere and ffmpeg do closely
enough for measurement purposes.

Usage as a module:

    from lut_apply import CubeLUT
    graded = CubeLUT.load('fix.cube').apply(frame)

Usage from the shell:

    python3 lut_apply.py frame.png fix.cube graded.png
"""

import sys

import numpy as np


class CubeLUT:
    """A 3D lookup table parsed from an Adobe .cube file."""

    __slots__ = ('size', 'table', 'domain_min', 'domain_max')

    def __init__(self, size, table, domain_min=None, domain_max=None):
        self.size = size
        self.table = table
        self.domain_min = np.zeros(3) if domain_min is None else np.asarray(domain_min)
        self.domain_max = np.ones(3) if domain_max is None else np.asarray(domain_max)

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def load(cls, path):
        size = None
        domain_min = None
        domain_max = None
        rows = []

        with open(path, encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                if s.startswith('TITLE'):
                    continue
                if s.startswith('LUT_3D_SIZE'):
                    size = int(s.split()[1])
                    continue
                if s.startswith('LUT_1D_SIZE'):
                    raise ValueError(f'{path}: 1D LUTs are not supported')
                if s.startswith('DOMAIN_MIN'):
                    domain_min = [float(v) for v in s.split()[1:4]]
                    continue
                if s.startswith('DOMAIN_MAX'):
                    domain_max = [float(v) for v in s.split()[1:4]]
                    continue
                parts = s.split()
                if len(parts) >= 3:
                    try:
                        rows.append([float(parts[0]), float(parts[1]), float(parts[2])])
                    except ValueError:
                        continue

        if size is None:
            raise ValueError(f'{path}: missing LUT_3D_SIZE')
        expected = size ** 3
        if len(rows) != expected:
            raise ValueError(
                f'{path}: expected {expected} entries for size {size}, got {len(rows)}')

        return cls(size, np.asarray(rows, dtype=np.float64), domain_min, domain_max)

    @classmethod
    def identity(cls, size=33):
        """The LUT that changes nothing — useful as an optimiser baseline."""
        axis = np.linspace(0.0, 1.0, size)
        # .cube order is red fastest, then green, then blue.
        b, g, r = np.meshgrid(axis, axis, axis, indexing='ij')
        table = np.stack([r.ravel(), g.ravel(), b.ravel()], axis=-1)
        return cls(size, table)

    # ── Application ───────────────────────────────────────────────────

    def apply(self, image):
        """Apply the LUT to an image.

        Accepts float arrays in 0-1 or uint8 arrays in 0-255, and returns the
        same kind. Any shape ending in a 3-channel axis works.
        """
        arr = np.asarray(image)
        was_uint8 = arr.dtype == np.uint8
        shape = arr.shape

        values = arr.reshape(-1, 3).astype(np.float64)
        if was_uint8:
            values /= 255.0

        span = np.where(self.domain_max - self.domain_min == 0, 1.0,
                        self.domain_max - self.domain_min)
        normalised = np.clip((values - self.domain_min) / span, 0.0, 1.0)

        out = self._interpolate(normalised)

        if was_uint8:
            return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8).reshape(shape)
        return out.reshape(shape)

    def _interpolate(self, values):
        """Trilinear interpolation over the lattice."""
        n = self.size
        last = n - 1

        scaled = values * last
        base = np.floor(scaled).astype(np.int64)
        np.clip(base, 0, last - 1, out=base)
        frac = scaled - base

        r0, g0, b0 = base[:, 0], base[:, 1], base[:, 2]
        rf = frac[:, 0:1], frac[:, 1:2], frac[:, 2:3]
        rf, gf, bf = rf

        def corner(dr, dg, db):
            idx = (b0 + db) * n * n + (g0 + dg) * n + (r0 + dr)
            return self.table[idx]

        c00 = corner(0, 0, 0) * (1 - rf) + corner(1, 0, 0) * rf
        c10 = corner(0, 1, 0) * (1 - rf) + corner(1, 1, 0) * rf
        c01 = corner(0, 0, 1) * (1 - rf) + corner(1, 0, 1) * rf
        c11 = corner(0, 1, 1) * (1 - rf) + corner(1, 1, 1) * rf

        c0 = c00 * (1 - gf) + c10 * gf
        c1 = c01 * (1 - gf) + c11 * gf

        return np.clip(c0 * (1 - bf) + c1 * bf, 0.0, 1.0)


def main(argv):
    if len(argv) < 4:
        print('Usage: python3 lut_apply.py <frame.png> <lut.cube> <output.png>')
        return 1

    from PIL import Image

    frame_path, lut_path, out_path = argv[1], argv[2], argv[3]
    img = np.array(Image.open(frame_path).convert('RGB'))
    graded = CubeLUT.load(lut_path).apply(img)
    Image.fromarray(graded).save(out_path)
    print(f'Wrote {out_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

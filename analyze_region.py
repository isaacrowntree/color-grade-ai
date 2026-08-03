#!/usr/bin/env python3
"""analyze_region.py — Colour statistics for a rectangular region of a frame.

Used to build a colour profile by sampling: run it over the skin, the wall, the
costume, and read off where each sits in hue and saturation before choosing a
correction.

This was previously a Python script embedded inside analyze_frame.rb as a
heredoc, written to a tempfile and run with `2>&1`. Pillow's deprecation of
`Image.getdata()` then emitted a warning onto the same stream the JSON was
parsed from, which broke the tool outright. Living in a real file means it can
be imported, tested, and kept vectorised.

    python3 analyze_region.py frame.png 400,200,600,350 skin
"""

import argparse
import json
import sys

import numpy as np
from PIL import Image

import grade_metrics


def rgb_to_hsv(arr):
    """Vectorised RGB (0-1) to HSV (H: 0-360, S: 0-1, V: 0-1)."""
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc

    s = np.where(maxc > 0, delta / np.maximum(maxc, 1e-12), 0.0)
    safe = np.where(delta > 0, delta, 1.0)

    h = np.where(maxc == r, ((g - b) / safe) % 6,
                 np.where(maxc == g, (b - r) / safe + 2,
                          (r - g) / safe + 4)) * 60.0
    h = np.where(delta > 0, h, 0.0)
    return h, s, maxc


def circular_hue_stats(hues, weights=None):
    """Mean and spread of hue, handled on the circle.

    A naive mean puts the average of 359 and 1 degrees at 180 — the opposite
    colour. Reds straddle the wrap point, and reds are what this tool spends
    most of its time looking at.
    """
    radians = np.deg2rad(hues)
    sin_mean = np.average(np.sin(radians), weights=weights)
    cos_mean = np.average(np.cos(radians), weights=weights)

    mean = float(np.rad2deg(np.arctan2(sin_mean, cos_mean)) % 360.0)

    # Clamp before the log: for a perfectly uniform hue the resultant length is
    # 1.0 up to float error, and 1.0 + 1e-16 makes log positive, -2*log
    # negative, and the sqrt NaN. That NaN then serialises as bare `NaN`, which
    # is not valid JSON, so the Ruby wrapper fails to parse its own output.
    resultant = float(np.clip(np.hypot(sin_mean, cos_mean), 1e-12, 1.0))

    # Circular standard deviation, in degrees.
    spread = float(np.rad2deg(np.sqrt(-2.0 * np.log(resultant))))
    return mean, spread


def analyze(image, region, label='sample'):
    """Statistics for one region. `region` is (x1, y1, x2, y2)."""
    arr = np.asarray(image)
    if arr.dtype == np.uint8:
        arr = arr.astype(np.float64) / 255.0

    height, width = arr.shape[:2]
    x1, y1, x2, y2 = region
    x1, x2 = sorted((max(0, x1), min(width, x2)))
    y1, y2 = sorted((max(0, y1), min(height, y2)))

    if x2 <= x1 or y2 <= y1:
        raise ValueError(f'empty region {region} for a {width}x{height} image')

    crop = arr[y1:y2, x1:x2]
    flat = crop.reshape(-1, 3)

    h, s, v = rgb_to_hsv(crop)
    h_flat, s_flat, v_flat = h.ravel(), s.ravel(), v.ravel()

    # Weight hue by saturation: the hue of a near-grey pixel is noise.
    mean_hue, hue_spread = circular_hue_stats(h_flat, weights=s_flat + 1e-6)

    mean_rgb = flat.mean(axis=0)
    mean_h, mean_s, mean_v = rgb_to_hsv(mean_rgb.reshape(1, 1, 3))

    return {
        'label': label,
        'region': [x1, y1, x2, y2],
        'pixel_count': int(flat.shape[0]),
        'avg_rgb': {k: round(float(mean_rgb[i] * 255), 1)
                    for i, k in enumerate('rgb')},
        'avg_hsv': {'h': round(float(mean_h.ravel()[0]), 1),
                    's': round(float(mean_s.ravel()[0]), 3),
                    'v': round(float(mean_v.ravel()[0]), 3)},
        'hue': {'mean': round(mean_hue, 1),
                'spread': round(hue_spread, 1),
                'min': round(float(h_flat.min()), 1),
                'max': round(float(h_flat.max()), 1)},
        's_range': {'min': round(float(s_flat.min()), 3),
                    'max': round(float(s_flat.max()), 3),
                    'mean': round(float(s_flat.mean()), 3)},
        'v_range': {'min': round(float(v_flat.min()), 3),
                    'max': round(float(v_flat.max()), 3),
                    'mean': round(float(v_flat.mean()), 3)},
        'luminance': round(float(grade_metrics.luminance(crop).mean()), 4),
        # Whether this region reads as skin, by the same detector the solver
        # uses — the usual reason for sampling a region in the first place.
        'skin_fraction': round(grade_metrics.skin_confidence(crop), 4),
    }


def parse_region(text):
    parts = text.split(',')
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            f'region must be x1,y1,x2,y2 — got {text!r}')
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f'region coordinates must be integers — got {text!r}')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Colour statistics for a region of a frame.')
    parser.add_argument('image')
    parser.add_argument('region', type=parse_region, help='x1,y1,x2,y2')
    parser.add_argument('label', nargs='?', default='sample')
    args = parser.parse_args(argv)

    image = Image.open(args.image).convert('RGB')
    # stdout carries JSON and nothing else, so a caller can parse it safely.
    print(json.dumps(analyze(image, args.region, args.label), indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())

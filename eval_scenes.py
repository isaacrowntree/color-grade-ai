#!/usr/bin/env python3
"""eval_scenes.py — Deterministic synthetic scenes for evaluating grades.

Real footage cannot be committed to the repo, so the evaluation set is built
procedurally instead. Each scene is generated twice: a pristine version that
represents a correct grade, and a degraded version with a known, deliberate
error applied. That gives the grader something objective to be scored against —
how much of the known error did it actually remove?

The scenes are not photorealistic. They exist to exercise the measurements the
analyzer makes: neutral patches for white balance and black level, skin patches
across a range of tones, saturated patches that must not be dragged around, and
a luminance ramp for exposure.

Run directly to write PNGs for inspection:
    python3 eval_scenes.py out_dir/
"""

import colorsys
import sys

import numpy as np

HEIGHT, WIDTH = 180, 240

# Skin reflectances across a range of tones, as Rec.709 code values under
# neutral light. Hues sit in the 15-25 degree band the analyzer targets.
SKIN_TONES = [
    (0.86, 0.68, 0.58),
    (0.72, 0.53, 0.43),
    (0.55, 0.38, 0.29),
    (0.36, 0.24, 0.18),
    (0.22, 0.15, 0.12),
]

# Saturated objects that a good grade should leave broadly alone.
PROPS = [
    (0.72, 0.16, 0.18),   # red fabric
    (0.18, 0.42, 0.68),   # blue denim
    (0.24, 0.52, 0.26),   # green foliage
    (0.78, 0.62, 0.18),   # brass
]

# A full step wedge including near-black and near-white. The dark end sets the
# black point the analyzer measures; the bright end anchors white balance,
# because a p=6 Minkowski norm is dominated by the brightest content in frame.
NEUTRALS = [0.02, 0.14, 0.28, 0.42, 0.58, 0.72, 0.86, 0.96]


def _patch(canvas, y, x, h, w, colour, rng, noise=0.006):
    block = np.empty((h, w, 3))
    for c in range(3):
        block[:, :, c] = colour[c]
    block += rng.normal(0.0, noise, block.shape)
    canvas[y:y + h, x:x + w] = np.clip(block, 0.0, 1.0)


def pristine(seed=0):
    """A correctly graded scene: neutral whites, natural skin, solid blacks."""
    rng = np.random.default_rng(seed)
    canvas = np.zeros((HEIGHT, WIDTH, 3))

    # Background: a neutral, correctly exposed wall. Sitting at the target
    # median is what makes this scene a definition of "well exposed" rather
    # than merely a plausible picture.
    ramp = np.linspace(0.40, 0.50, WIDTH)
    for c in range(3):
        canvas[:, :, c] = ramp
    canvas += rng.normal(0.0, 0.004, canvas.shape)

    # Neutral step wedge across the top.
    for i, level in enumerate(NEUTRALS):
        _patch(canvas, 6, 4 + i * 29, 32, 26, (level, level, level), rng)

    # Skin patches through the middle — the majority of the frame's interest.
    for i, tone in enumerate(SKIN_TONES):
        _patch(canvas, 56, 8 + i * 46, 54, 40, tone, rng)

    # Saturated props along the bottom.
    for i, prop in enumerate(PROPS):
        _patch(canvas, 124, 12 + i * 56, 42, 48, prop, rng)

    return np.clip(canvas, 0.0, 1.0)


def degrade(scene, gains=(1.0, 1.0, 1.0), gamma=1.0, black_lift=0.0,
            highlight_gain=1.0, saturation=1.0):
    """Apply a known, invertible-in-principle error to a pristine scene.

    gains          per-channel multiplier (a colour cast)
    gamma          out = in ** gamma (>1 darkens, <1 brightens)
    black_lift     raises the floor, the classic milky-blacks look
    highlight_gain scales the top end, for blown highlights
    saturation     scales distance from luminance (<1 washes out, >1 overcooks)
    """
    out = np.asarray(scene, dtype=np.float64).copy()

    for c in range(3):
        out[:, :, c] *= gains[c]

    if saturation != 1.0:
        lum = (0.2126 * out[:, :, 0] + 0.7152 * out[:, :, 1] +
               0.0722 * out[:, :, 2])[:, :, None]
        out = lum + (out - lum) * saturation

    if gamma != 1.0:
        out = np.clip(out, 0.0, None) ** gamma

    if black_lift:
        out = black_lift + out * (1.0 - black_lift)

    if highlight_gain != 1.0:
        out *= highlight_gain

    return np.clip(out, 0.0, 1.0)


def as_uint8(scene):
    return np.clip(scene * 255.0 + 0.5, 0, 255).astype(np.uint8)


# ── Log encoding ─────────────────────────────────────────────────────
#
# Correction LUTs are meant to be applied to display-referred Rec.709, after a
# conversion LUT. Feeding them log footage produces a confidently wrong grade,
# so the evaluation set needs genuine log scenes to detect against.

DISPLAY_GAMMA = 2.4


def to_linear(scene):
    """Decode display-referred Rec.709 (BT.1886) to linear light."""
    return np.clip(scene, 0.0, 1.0) ** DISPLAY_GAMMA


def slog3(linear):
    """Sony S-Log3 encoding curve (SonyRAW white paper)."""
    x = np.asarray(linear, dtype=np.float64)
    high = (420.0 + np.log10((np.maximum(x, 0.0) + 0.01) / 0.19) * 261.5) / 1023.0
    low = (x * (171.2102946929 - 95.0) / 0.01125000 + 95.0) / 1023.0
    return np.clip(np.where(x >= 0.01125000, high, low), 0.0, 1.0)


def as_log(scene):
    """Re-encode a display-referred scene as S-Log3, as a camera would deliver."""
    return slog3(to_linear(scene))


# The evaluation set. Each case names the defect it introduces so a failure
# report says what broke, not just that something did.
CASES = {
    'warm_tungsten': dict(gains=(1.22, 1.0, 0.78)),
    'cool_daylight': dict(gains=(0.80, 1.0, 1.20)),
    'green_led': dict(gains=(0.93, 1.12, 0.94)),
    'magenta_stage': dict(gains=(1.14, 0.88, 1.10)),
    'underexposed': dict(gamma=1.55),
    'overexposed': dict(gamma=0.62, highlight_gain=1.08),
    'milky_blacks': dict(black_lift=0.16),
    'warm_and_dark': dict(gains=(1.18, 1.0, 0.82), gamma=1.40),
    'cool_and_milky': dict(gains=(0.86, 1.0, 1.14), black_lift=0.12),
    'washed_out': dict(saturation=0.32),
    'oversaturated': dict(saturation=1.95),
}


def build(case_name, seed=0):
    """Return (pristine, degraded) as float arrays in 0-1."""
    if case_name not in CASES:
        raise KeyError(f'unknown case: {case_name}')
    base = pristine(seed)
    return base, degrade(base, **CASES[case_name])


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1

    import os
    from PIL import Image

    out_dir = argv[1]
    os.makedirs(out_dir, exist_ok=True)

    Image.fromarray(as_uint8(pristine())).save(
        os.path.join(out_dir, 'pristine.png'))
    for name in CASES:
        _, degraded = build(name)
        Image.fromarray(as_uint8(degraded)).save(
            os.path.join(out_dir, f'{name}.png'))
    print(f'Wrote {len(CASES) + 1} scenes to {out_dir}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

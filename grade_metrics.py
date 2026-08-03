#!/usr/bin/env python3
"""grade_metrics.py — Reference-free measurements of how wrong a frame is.

These are the quantities the solver minimises. Every one is computable from a
single frame with no reference image, because that is the situation the tool is
actually used in.

Kept separate from auto_grade.py because the solver evaluates them hundreds of
times per frame and needs them to be cheap, array-in / float-out, and free of
reporting concerns.
"""

import numpy as np

# ── Targets ──────────────────────────────────────────────────────────
#
# What a correctly graded interior frame is expected to measure. These are the
# same targets auto_grade.py reports against.

TARGET_MEDIAN_LUMA = 0.45
TARGET_BLACK_POINT = 0.02
TARGET_SKIN_HUE = 20.0      # degrees, the "I-line" toward which skin sits

# Weights for the composite score. White balance dominates because a cast is
# the most visible defect and the one viewers notice without a reference.
WEIGHTS = {
    'white_balance': 1.0,
    'exposure': 0.8,
    'black_level': 0.6,
    'skin_hue': 0.5,
    # Lowest weight of the four: it only fires when saturation has left any
    # plausible range, and it is the most scene-dependent judgement here.
    'saturation': 0.4,
}


def _as_float(image):
    arr = np.asarray(image)
    if arr.dtype == np.uint8:
        return arr.astype(np.float64) / 255.0
    return arr.astype(np.float64)


def luminance(image):
    arr = _as_float(image)
    return 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]


# ── Skin detection ───────────────────────────────────────────────────
#
# An axis-aligned HSV box (the previous approach) also selects wood, terracotta
# and amber practicals, because "warm and mid-bright" is not a description of
# skin. In YCbCr, human skin of every tone falls on a narrow, almost linear
# locus: as a subject gets darker, Cb rises and Cr falls together toward the
# neutral point. Warm non-skin surfaces sit off that line.
#
# So the test is an ellipse aligned to the locus: generous along it, tight
# across it.

SKIN_CENTRE = (112.0, 149.0)     # (Cb, Cr)
SKIN_ALONG = 17.0                # semi-axis along the locus

# The across-axis tolerance is deliberately asymmetric. Flushed, sunburnt or
# warm-lit skin sits to the positive side of the locus — and that is precisely
# what red_skin_fix exists to correct, so the detector must still see it as
# skin. Wood, khaki and amber practicals sit to the negative side, where the
# tolerance stays tight.
SKIN_ACROSS_POS = 8.0
SKIN_ACROSS_NEG = 4.5

SKIN_LUMA_RANGE = (0.10, 0.96)   # very dark or clipped pixels carry no chroma


def ycbcr(image):
    """BT.601 YCbCr in 0-255, the space the skin locus is defined in."""
    arr = _as_float(image) * 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    cb = 128.0 - 0.168736 * r - 0.331264 * g + 0.5 * b
    cr = 128.0 + 0.5 * r - 0.418688 * g - 0.081312 * b
    return y, cb, cr


def skin_score(image):
    """Continuous skin likelihood: <= 1 inside the locus ellipse."""
    _, cb, cr = ycbcr(image)
    dcb = cb - SKIN_CENTRE[0]
    dcr = cr - SKIN_CENTRE[1]

    # The locus runs anti-diagonally, so rotate into along/across coordinates.
    root2 = np.sqrt(2.0)
    along = (dcb - dcr) / root2
    across = (dcb + dcr) / root2

    across_limit = np.where(across >= 0, SKIN_ACROSS_POS, SKIN_ACROSS_NEG)
    return (along / SKIN_ALONG) ** 2 + (across / across_limit) ** 2


def skin_mask(image):
    lum = luminance(image)
    within_luma = (lum >= SKIN_LUMA_RANGE[0]) & (lum <= SKIN_LUMA_RANGE[1])
    return (skin_score(image) <= 1.0) & within_luma


def skin_confidence(image):
    """Fraction of the frame that reads as skin."""
    return float(skin_mask(image).mean())


# A single threshold for "is there enough skin to act on", shared by the
# measurement and the solver. They used to disagree — skin_hue() reported from
# 64 pixels while the solver required 1% of the frame — so on real footage a
# sliver of skin could contribute most of the error score while the optimiser
# was forbidden to correct it.
MIN_SKIN_FRACTION = 0.01

# Confidence at which the skin term carries its full weight. Between the
# threshold and here its influence ramps, so a marginal sample nudges the
# score rather than steering it.
FULL_SKIN_CONFIDENCE = 0.06


def skin_hue(image):
    """Mean skin hue in degrees, or None when there is too little to measure."""
    mask = skin_mask(image)
    if mask.mean() < MIN_SKIN_FRACTION:
        return None

    arr = _as_float(image)
    pixels = arr[mask]
    r, g, b = pixels[:, 0], pixels[:, 1], pixels[:, 2]

    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc
    safe = np.where(delta > 0, delta, 1.0)

    h = np.where(maxc == r, ((g - b) / safe) % 6,
                 np.where(maxc == g, (b - r) / safe + 2, (r - g) / safe + 4)) * 60.0
    h = np.where(delta > 0, h, 0.0)
    h = np.where(h > 180.0, h - 360.0, h)   # unwrap reds through zero

    return float(np.mean(h[delta > 0])) if np.any(delta > 0) else None


# ── Individual measurements ──────────────────────────────────────────

MIN_ILLUMINANT_PIXELS = 256


def illuminant_mask(image):
    """Pixels worth estimating the illuminant from.

    Shades-of-Gray assumes the scene averages to neutral. Two things reliably
    break that assumption in the footage this tool targets:

      - A face filling the frame. Skin is warm by reflectance, not by lighting,
        so including it makes every portrait look blue once corrected.
      - Saturated props. A red dress is not evidence of a red light.

    Excluding both leaves the surfaces that actually carry illuminant
    information: walls, clothing, neutral objects.
    """
    arr = _as_float(image)
    maxc = arr.max(axis=-1)
    minc = arr.min(axis=-1)
    purity = np.where(maxc > 1e-6, 1.0 - minc / np.maximum(maxc, 1e-6), 0.0)

    lum = luminance(image)
    usable = (
        ~skin_mask(image) &
        (purity < 0.45) &            # ignore strongly coloured objects
        (lum > 0.05) & (lum < 0.98)  # ignore crushed and clipped pixels
    )

    # Fall back to the whole frame rather than return nothing measurable.
    if usable.sum() < MIN_ILLUMINANT_PIXELS:
        return np.ones_like(usable, dtype=bool)
    return usable


def shades_of_gray_gains(image, p=6):
    """Corrective per-channel gains. gain < 1 means that channel is in excess."""
    arr = _as_float(image)
    mask = illuminant_mask(image)
    pixels = arr[mask]

    norms = []
    for c in range(3):
        channel = pixels[:, c]
        norms.append(np.mean(channel ** p) ** (1.0 / p))

    r_norm, g_norm, b_norm = norms
    gain_r = g_norm / r_norm if r_norm > 1e-9 else 1.0
    gain_b = g_norm / b_norm if b_norm > 1e-9 else 1.0
    return gain_r, gain_b


def white_balance_error(image):
    """How far the frame is from neutral. 0 is neutral."""
    gain_r, gain_b = shades_of_gray_gains(image)
    return float(max(abs(gain_r - 1.0), abs(gain_b - 1.0)))


def exposure_error(image):
    """Signed: negative is too dark, positive is too bright."""
    return float(np.median(luminance(image)) - TARGET_MEDIAN_LUMA)


def black_level_error(image):
    """How far the black point sits above true black. 0 when blacks are solid."""
    p01 = float(np.percentile(luminance(image), 1))
    return max(0.0, p01 - TARGET_BLACK_POINT)


# ── Saturation ───────────────────────────────────────────────────────
#
# Unlike white balance or exposure, there is no target here. Colourfulness is a
# property of the scene: a grey warehouse is legitimately drab and a fruit
# market is legitimately vivid. The pristine evaluation scene measures 63.8,
# well above auto_grade's old target of 45 — fitting to that number would have
# "corrected" a scene that was already right.
#
# So this measures only whether saturation has left any plausible range, and
# stays silent inside it. The band is wide on purpose.

SATURATION_BAND = (25.0, 95.0)


def colorfulness(image):
    """Hasler-Susstrunk colourfulness, on the 0-255 scale it is defined for."""
    arr = _as_float(image) * 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    rg = (r - g).ravel()
    yb = (0.5 * (r + g) - b).ravel()
    return float(np.sqrt(rg.var() + yb.var()) +
                 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2))


def saturation_error(image):
    """Signed distance outside the plausible band; 0 anywhere inside it.

    Negative means washed out, positive means overcooked. Normalised by the
    band width so it sits on roughly the same scale as the other terms.
    """
    value = colorfulness(image)
    low, high = SATURATION_BAND
    width = high - low

    if value < low:
        return (value - low) / width
    if value > high:
        return (value - high) / width
    return 0.0


def skin_hue_error(image):
    """Absolute skin hue error in degrees, or 0 when no skin is present."""
    hue = skin_hue(image)
    if hue is None:
        return 0.0
    return abs(hue - TARGET_SKIN_HUE)


# ── Composite ────────────────────────────────────────────────────────

def measure(image):
    """All measurements at once, for reporting."""
    return {
        'white_balance': white_balance_error(image),
        'exposure': exposure_error(image),
        'black_level': black_level_error(image),
        'saturation': saturation_error(image),
        'skin_hue': skin_hue_error(image),
        'skin_confidence': skin_confidence(image),
    }


def skin_term(image, measured=None):
    """The skin contribution to the score, scaled by how much skin there is."""
    m = measured or measure(image)
    if m['skin_hue'] == 0.0:
        return 0.0
    ramp = min(m['skin_confidence'] / FULL_SKIN_CONFIDENCE, 1.0)
    # Normalise degrees onto roughly the same scale as the other terms.
    return WEIGHTS['skin_hue'] * (m['skin_hue'] / 30.0) * ramp


def total_error(image):
    """Single scalar the solver minimises. Lower is better; 0 is ideal."""
    m = measure(image)
    return float(
        WEIGHTS['white_balance'] * m['white_balance'] +
        WEIGHTS['exposure'] * abs(m['exposure']) +
        WEIGHTS['black_level'] * m['black_level'] +
        WEIGHTS['saturation'] * abs(m['saturation']) +
        skin_term(image, measured=m)
    )

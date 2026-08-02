#!/usr/bin/env python3
"""
Compare a graded output image against a reference image and suggest
preset adjustments to close the gap.

Usage:
  python3 match_grade.py reference.jpg output.png
  python3 match_grade.py reference.jpg output.png --skin-only
"""

import sys
import numpy as np
from PIL import Image
from colorsys import rgb_to_hsv

def extract_skin(pixels):
    """Filter to skin-tone pixels by HSV range."""
    hsv = np.array([rgb_to_hsv(r/255, g/255, b/255) for r, g, b in pixels])
    h, s, v = hsv[:, 0] * 360, hsv[:, 1], hsv[:, 2]
    mask = (h > 5) & (h < 50) & (s > 0.08) & (v > 0.15)
    return pixels[mask], hsv[mask]

def analyze(img_array, label, sample_step=10):
    """Full color analysis of an image."""
    h, w = img_array.shape[:2]
    flat = img_array.reshape(-1, 3)
    sampled = flat[::sample_step]

    # Overall RGB
    r_mean, g_mean, b_mean = sampled[:, 0].mean(), sampled[:, 1].mean(), sampled[:, 2].mean()

    # Luminance
    lum = 0.299 * sampled[:, 0] + 0.587 * sampled[:, 1] + 0.114 * sampled[:, 2]
    lum_p = np.percentile(lum, [5, 25, 50, 75, 95])

    # Skin pixels
    skin_px, skin_hsv = extract_skin(sampled)
    skin_count = len(skin_px)

    skin = {}
    if skin_count > 50:
        skin = {
            'rgb': skin_px.mean(axis=0),
            'r_g': skin_px[:, 0].mean() - skin_px[:, 1].mean(),
            'r_b': skin_px[:, 0].mean() - skin_px[:, 2].mean(),
            'hue': skin_hsv[:, 0].mean() * 360,
            'sat': skin_hsv[:, 1].mean(),
            'sat_p50': np.median(skin_hsv[:, 1]),
            'val': skin_hsv[:, 2].mean(),
            'val_p50': np.median(skin_hsv[:, 2]),
        }

    # Neutral detection: high-value, low-saturation pixels
    hsv_all = np.array([rgb_to_hsv(r/255, g/255, b/255) for r, g, b in sampled[::5]])
    neutral_mask = (hsv_all[:, 1] < 0.1) & (hsv_all[:, 2] > 0.3)
    neutral_sampled = sampled[::5]
    neutral_px = neutral_sampled[neutral_mask] if neutral_mask.any() else None

    return {
        'label': label,
        'rgb_mean': np.array([r_mean, g_mean, b_mean]),
        'lum_p5': lum_p[0], 'lum_p25': lum_p[1], 'lum_p50': lum_p[2],
        'lum_p75': lum_p[3], 'lum_p95': lum_p[4],
        'contrast': lum_p[4] - lum_p[0],
        'skin_count': skin_count,
        'skin': skin,
        'neutral_px': neutral_px,
    }

def print_analysis(a):
    print(f"\n{'='*50}")
    print(f"  {a['label']}")
    print(f"{'='*50}")
    print(f"  Overall RGB:  R={a['rgb_mean'][0]:.0f}  G={a['rgb_mean'][1]:.0f}  B={a['rgb_mean'][2]:.0f}")
    print(f"  Luminance:    p5={a['lum_p5']:.0f}  p25={a['lum_p25']:.0f}  p50={a['lum_p50']:.0f}  p75={a['lum_p75']:.0f}  p95={a['lum_p95']:.0f}")
    print(f"  Contrast:     {a['contrast']:.0f} (p95-p5)")

    if a['skin']:
        s = a['skin']
        print(f"\n  Skin ({a['skin_count']} px):")
        print(f"    RGB:        R={s['rgb'][0]:.0f}  G={s['rgb'][1]:.0f}  B={s['rgb'][2]:.0f}")
        print(f"    Warmth:     R-G={s['r_g']:.0f}  R-B={s['r_b']:.0f}")
        print(f"    Hue:        {s['hue']:.1f}°")
        print(f"    Saturation: {s['sat']:.3f} (median {s['sat_p50']:.3f})")
        print(f"    Brightness: {s['val']:.3f} (median {s['val_p50']:.3f})")

    if a['neutral_px'] is not None and len(a['neutral_px']) > 20:
        n = a['neutral_px']
        r, g, b = n[:, 0].mean(), n[:, 1].mean(), n[:, 2].mean()
        print(f"\n  Neutrals ({len(n)} px):")
        print(f"    RGB:        R={r:.0f}  G={g:.0f}  B={b:.0f}")
        print(f"    Cast:       R-G={r-g:+.1f}  G-B={g-b:+.1f}")

def suggest(ref, out):
    print(f"\n{'='*50}")
    print(f"  RECOMMENDATIONS")
    print(f"{'='*50}")

    # Exposure
    exp_diff = ref['lum_p50'] - out['lum_p50']
    if abs(exp_diff) > 5:
        direction = "darker" if exp_diff < 0 else "brighter"
        # Rough gamma estimate: ratio of midpoints
        if out['lum_p50'] > 0 and ref['lum_p50'] > 0:
            gamma_ratio = np.log(ref['lum_p50']/255) / np.log(out['lum_p50']/255)
            print(f"\n  Exposure: needs to be {direction} (midpoint {out['lum_p50']:.0f} → {ref['lum_p50']:.0f})")
            print(f"    → gamma ≈ {gamma_ratio:.2f} in exposure step")

    # Black level
    black_diff = ref['lum_p5'] - out['lum_p5']
    if abs(black_diff) > 3:
        if black_diff > 0:
            print(f"\n  Blacks: too crushed (p5={out['lum_p5']:.0f} → {ref['lum_p5']:.0f})")
            print(f"    → reduce black_crush strength or use black_lift")
        else:
            print(f"\n  Blacks: too lifted (p5={out['lum_p5']:.0f} → {ref['lum_p5']:.0f})")
            print(f"    → increase black_crush strength")

    # Contrast
    con_diff = ref['contrast'] - out['contrast']
    if abs(con_diff) > 10:
        print(f"\n  Contrast: {'too low' if con_diff > 0 else 'too high'} ({out['contrast']:.0f} → {ref['contrast']:.0f})")

    # Skin analysis
    if ref['skin'] and out['skin']:
        rs, os = ref['skin'], out['skin']

        sat_ratio = rs['sat'] / max(os['sat'], 0.01)
        if abs(sat_ratio - 1.0) > 0.05:
            print(f"\n  Skin saturation: {'too low' if sat_ratio > 1 else 'too high'} ({os['sat']:.3f} → {rs['sat']:.3f})")
            print(f"    → multiply skin sat by {sat_ratio:.2f}")
            # Translate to sat_boost strength estimate
            # sat_boost is +15% at full strength, so needed_boost = (ratio - 1) / 0.15
            needed = (sat_ratio - 1.0) / 0.15 * 100
            print(f"    → sat_boost strength ≈ {min(needed, 100):.0f}% (if only using global sat)")

        warmth_diff = rs['r_b'] - os['r_b']
        if abs(warmth_diff) > 5:
            print(f"\n  Skin warmth (R-B): {'too cool' if warmth_diff > 0 else 'too warm'} ({os['r_b']:.0f} → {rs['r_b']:.0f})")
            # Estimate rgb_rebalance gains needed
            # Each 0.01 of r_gain adds ~2.5 to R on a mid-tone pixel
            r_adj = warmth_diff / 2 / 255
            print(f"    → increase r_gain by ~{r_adj:.3f} or decrease b_gain by ~{r_adj:.3f}")

        hue_diff = rs['hue'] - os['hue']
        if abs(hue_diff) > 2:
            print(f"\n  Skin hue: {os['hue']:.1f}° → {rs['hue']:.1f}° (shift {hue_diff:+.1f}°)")

        val_diff = rs['val'] - os['val']
        if abs(val_diff) > 0.03:
            print(f"\n  Skin brightness: {os['val']:.3f} → {rs['val']:.3f} ({'too dark' if val_diff > 0 else 'too bright'})")

    # Neutral cast
    if ref.get('neutral_px') is not None and out.get('neutral_px') is not None:
        if len(ref['neutral_px']) > 20 and len(out['neutral_px']) > 20:
            rn = ref['neutral_px'].mean(axis=0)
            on = out['neutral_px'].mean(axis=0)
            rn_rg = rn[0] - rn[1]
            on_rg = on[0] - on[1]
            rn_gb = rn[1] - rn[2]
            on_gb = on[1] - on[2]
            if abs(on_rg - rn_rg) > 3 or abs(on_gb - rn_gb) > 3:
                print(f"\n  Neutral cast:")
                print(f"    Ref  R-G={rn_rg:+.1f}  G-B={rn_gb:+.1f}")
                print(f"    Out  R-G={on_rg:+.1f}  G-B={on_gb:+.1f}")
                if on_rg > rn_rg + 3:
                    print(f"    → reduce r_gain or increase g_gain (pink cast on neutrals)")
                if on_gb > rn_gb + 3:
                    print(f"    → reduce g_gain or increase b_gain (green cast on neutrals)")

    print()

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 match_grade.py reference.jpg output.png")
        sys.exit(1)

    ref_path = sys.argv[1]
    out_path = sys.argv[2]

    print(f"Loading {ref_path}...")
    ref_img = np.array(Image.open(ref_path).convert('RGB'))
    print(f"Loading {out_path}...")
    out_img = np.array(Image.open(out_path).convert('RGB'))

    ref_a = analyze(ref_img, f"Reference: {ref_path.split('/')[-1]}")
    out_a = analyze(out_img, f"Output: {out_path.split('/')[-1]}")

    print_analysis(ref_a)
    print_analysis(out_a)
    suggest(ref_a, out_a)

if __name__ == '__main__':
    main()

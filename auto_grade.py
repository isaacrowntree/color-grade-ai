#!/usr/bin/env python3
"""auto_grade.py — Analyze a frame and recommend color correction node settings.

Takes a Rec.709 frame (post-conversion LUT) and outputs recommended values for
a DaVinci Resolve-style node chain. Uses classical color science — no ML.

Usage:
    python3 auto_grade.py <frame.png>

Methodology:
    Node 2 (Contrast/Exposure):
        - Luminance histogram percentile analysis
        - Target: blacks at ~3%, highlights at ~92%, median ~45%
        - Derives gamma, highlight knee, shadow crush values

    Node 3 (White Balance / Color Temperature):
        - Shades of Gray algorithm (Finlayson & Trezzi 2004, Minkowski p=6)
        - Cross-referenced with White Patch (top 1% brightest pixels)
        - Outputs RGB gains for channel rebalancing

    Node 4 (Skin Tone):
        - HSV-based skin detection (H:0-50, S:0.10-0.70, V:0.20-0.90)
        - Measures mean skin hue vs target I-line (~20 degrees)
        - Outputs hue shift to bring skin toward natural peach

    Node 5 (Saturation):
        - Hasler-Susstrunk colorfulness metric
        - Target range: 35-55 for natural indoor scenes
        - Outputs global saturation multiplier

    Node 6 (Black Level):
        - Bottom 5% luminance analysis
        - Shadow noise estimation (std dev of darkest pixels)
        - Shadow color neutrality check
        - Outputs crush threshold based on noise floor
"""

import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image

import grade_metrics


def rgb_to_hsv(r, g, b):
    """Vectorized RGB (0-1) to HSV (H: 0-360, S: 0-1, V: 0-1)."""
    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    v = maxc
    delta = maxc - minc

    s = np.where(maxc > 0, delta / maxc, 0)

    h = np.zeros_like(r)
    mask = delta > 0
    # Red is max
    m = mask & (maxc == r)
    h[m] = 60.0 * (((g[m] - b[m]) / delta[m]) % 6)
    # Green is max
    m = mask & (maxc == g)
    h[m] = 60.0 * (((b[m] - r[m]) / delta[m]) + 2)
    # Blue is max
    m = mask & (maxc == b)
    h[m] = 60.0 * (((r[m] - g[m]) / delta[m]) + 4)

    h[h < 0] += 360
    return h, s, v


def analyze_frame(img_path):
    """Analyze a frame and return per-node recommendations."""
    img = Image.open(img_path).convert('RGB')
    arr = np.array(img, dtype=np.float64) / 255.0
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    # Rec.709 luminance
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    lum_flat = lum.flatten()

    results = {}

    # ── Node 2: Contrast / Exposure ────────────────────────────────
    p01 = np.percentile(lum_flat, 1)   # black point
    p05 = np.percentile(lum_flat, 5)
    p50 = np.percentile(lum_flat, 50)  # median
    p95 = np.percentile(lum_flat, 95)
    p99 = np.percentile(lum_flat, 99)  # white point
    mean_lum = np.mean(lum_flat)

    # Target: median ~0.45 for well-lit interior
    target_median = 0.45
    # Gamma to shift median toward target: new = old^gamma => gamma = log(target)/log(current)
    if 0.01 < p50 < 0.99:
        gamma_recommend = math.log(target_median) / math.log(p50)
    else:
        gamma_recommend = 1.0

    # Highlight clipping: % of pixels above 0.92
    highlight_clip_pct = np.mean(lum_flat > 0.92) * 100

    # Dynamic range usage
    dynamic_range = p99 - p01

    results['node2_contrast'] = {
        'black_point_p01': round(p01, 4),
        'shadow_p05': round(p05, 4),
        'median': round(p50, 4),
        'highlight_p95': round(p95, 4),
        'white_point_p99': round(p99, 4),
        'mean_luminance': round(mean_lum, 4),
        'dynamic_range': round(dynamic_range, 4),
        'highlight_clip_pct': round(highlight_clip_pct, 2),
        'gamma_recommendation': round(gamma_recommend, 3),
        'assessment': (
            'underexposed' if p50 < 0.30 else
            'slightly dark' if p50 < 0.40 else
            'good exposure' if p50 < 0.55 else
            'slightly bright' if p50 < 0.65 else
            'overexposed'
        ),
        'preset_recommendation': (
            'underexposure_fix' if p50 < 0.30 else
            'studio_punch' if 0.30 <= p50 < 0.55 else
            'film_contrast' if p50 >= 0.55 else
            'none'
        ),
        'recommended_strength': round(min(abs(gamma_recommend - 1.0) * 5, 1.0), 2),
    }

    # ── Node 3: White Balance / Color Temperature ──────────────────
    # Shades of Gray (Minkowski p=6)
    p = 6
    norm_r = np.mean(r.flatten() ** p) ** (1 / p)
    norm_g = np.mean(g.flatten() ** p) ** (1 / p)
    norm_b = np.mean(b.flatten() ** p) ** (1 / p)

    # Normalize gains relative to green (industry convention)
    gain_r_sg = norm_g / norm_r if norm_r > 0 else 1.0
    gain_b_sg = norm_g / norm_b if norm_b > 0 else 1.0

    # White Patch: top 1% brightest
    bright_threshold = np.percentile(lum_flat, 99)
    bright_mask = lum >= bright_threshold
    if np.sum(bright_mask) > 10:
        wp_r = np.mean(r[bright_mask])
        wp_g = np.mean(g[bright_mask])
        wp_b = np.mean(b[bright_mask])
        gain_r_wp = wp_g / wp_r if wp_r > 0 else 1.0
        gain_b_wp = wp_g / wp_b if wp_b > 0 else 1.0
    else:
        gain_r_wp, gain_b_wp = 1.0, 1.0

    # Blend: 60% Shades of Gray, 40% White Patch
    gain_r = 0.6 * gain_r_sg + 0.4 * gain_r_wp
    gain_b = 0.6 * gain_b_sg + 0.4 * gain_b_wp

    # Estimate color temperature direction.
    #
    # Gains are corrective: gain_c = norm_g / norm_c, so gain < 1.0 means that
    # channel is in EXCESS and must be pulled down, and gain > 1.0 means it is
    # DEFICIENT and must be pushed up. The recommended preset is therefore the
    # one that moves the scene toward neutral, i.e. the opposite of the cast.
    if gain_r > 1.02 and gain_b > 1.02:
        # Both red and blue need lifting → green is in excess.
        wb_direction = 'green tint (cheap LED/fluorescent) → led_green_fix'
        preset = 'led_green_fix'
    elif gain_r < 0.98 and gain_b < 0.98:
        # Both red and blue in excess → green is deficient: magenta/pink cast.
        wb_direction = 'magenta/pink cast → pink_cast_fix'
        preset = 'pink_cast_fix'
    elif gain_r < 0.98 and gain_b > 1.02:
        # Red in excess, blue deficient → scene is too warm, cool it down.
        wb_direction = 'scene is too warm → cool_shift'
        preset = 'cool_shift'
    elif gain_b < 0.98 and gain_r > 1.02:
        # Blue in excess, red deficient → scene is too cool, warm it up.
        wb_direction = 'scene is too cool → warm_shift'
        preset = 'warm_shift'
    else:
        wb_direction = 'neutral (no correction needed)'
        preset = 'none'

    # Deviation from neutral
    wb_deviation = max(abs(gain_r - 1.0), abs(gain_b - 1.0))

    results['node3_white_balance'] = {
        'shades_of_gray_gains': {'r': round(gain_r_sg, 4), 'g': 1.0, 'b': round(gain_b_sg, 4)},
        'white_patch_gains': {'r': round(gain_r_wp, 4), 'g': 1.0, 'b': round(gain_b_wp, 4)},
        'blended_gains': {'r': round(gain_r, 4), 'g': 1.0, 'b': round(gain_b, 4)},
        'deviation_from_neutral': round(wb_deviation, 4),
        # 'assessment' is the key every node exposes for the summary loop;
        # 'direction' is kept as an alias for backward compatibility.
        'assessment': wb_direction,
        'direction': wb_direction,
        'preset_recommendation': preset,
        'recommended_strength': round(min(wb_deviation * 10, 1.0), 2),
    }

    # ── Node 4: Skin Tone ──────────────────────────────────────────
    h, s, v = rgb_to_hsv(r, g, b)

    # Skin detection lives in grade_metrics so the analyzer and the solver
    # always agree about which pixels are skin. It uses the YCbCr skin locus
    # rather than an HSV box, which also selects wood, khaki and amber
    # practicals — "warm and mid-bright" is not a description of skin.
    skin_mask = grade_metrics.skin_mask(arr)
    skin_pixel_count = np.sum(skin_mask)
    skin_pct = skin_pixel_count / lum_flat.size * 100

    if skin_pixel_count > 100:
        skin_hues = h[skin_mask]
        # Handle hue wrapping (convert 340-360 to -20 to 0)
        skin_hues_unwrapped = np.where(skin_hues > 180, skin_hues - 360, skin_hues)
        mean_skin_hue = np.mean(skin_hues_unwrapped)
        if mean_skin_hue < 0:
            mean_skin_hue += 360
        mean_skin_sat = np.mean(s[skin_mask])
        mean_skin_val = np.mean(v[skin_mask])

        # Target: ~20 degrees (peach)
        target_hue = 20.0
        hue_delta = target_hue - mean_skin_hue
        # Handle wrapping
        if hue_delta > 180:
            hue_delta -= 360
        elif hue_delta < -180:
            hue_delta += 360

        needs_correction = abs(hue_delta) > 3  # more than 3 degrees off

        results['node4_skin'] = {
            'skin_pixels_pct': round(skin_pct, 1),
            'mean_hue': round(mean_skin_hue, 1),
            'mean_saturation': round(mean_skin_sat, 3),
            'mean_value': round(mean_skin_val, 3),
            'target_hue': target_hue,
            'hue_delta': round(hue_delta, 1),
            'assessment': (
                'skin too red/magenta' if mean_skin_hue > 350 or mean_skin_hue < 5 else
                'skin too red' if mean_skin_hue < 12 else
                'skin natural' if 12 <= mean_skin_hue <= 28 else
                'skin too yellow' if mean_skin_hue > 28 else
                'skin hue unusual'
            ),
            'preset_recommendation': 'red_skin_fix' if needs_correction and (mean_skin_hue < 12 or mean_skin_hue > 340) else 'none',
            'recommended_strength': round(min(abs(hue_delta) / 15, 1.0), 2) if needs_correction else 0,
        }
    else:
        results['node4_skin'] = {
            'skin_pixels_pct': round(skin_pct, 1),
            'assessment': 'insufficient skin pixels detected',
            'preset_recommendation': 'none',
            'recommended_strength': 0,
        }

    # ── Node 5: Saturation ─────────────────────────────────────────
    # Hasler-Susstrunk colorfulness metric
    # Scale to 0-255 range for Hasler-Susstrunk metric (reference values are 0-255)
    rg = ((r - g) * 255).flatten()
    yb = ((0.5 * (r + g) - b) * 255).flatten()
    colorfulness = (
        math.sqrt(np.mean(rg ** 2) + np.mean(yb ** 2)) +
        0.3 * math.sqrt(np.mean(rg) ** 2 + np.mean(yb) ** 2)
    )

    mean_sat = np.mean(s.flatten())
    # Target colorfulness: 35-55 for natural indoor
    target_colorfulness = 45.0
    sat_ratio = target_colorfulness / colorfulness if colorfulness > 0 else 1.0

    results['node5_saturation'] = {
        'colorfulness': round(colorfulness, 2),
        'mean_saturation_hsl': round(mean_sat, 4),
        'target_colorfulness': target_colorfulness,
        'sat_ratio': round(sat_ratio, 3),
        'assessment': (
            'very desaturated' if colorfulness < 20 else
            'slightly desaturated' if colorfulness < 35 else
            'natural' if colorfulness < 55 else
            'slightly oversaturated' if colorfulness < 70 else
            'oversaturated'
        ),
        'preset_recommendation': (
            'sat_boost' if sat_ratio > 1.08 else
            'sat_reduce' if sat_ratio < 0.92 else
            'none'
        ),
        'recommended_strength': round(min(abs(sat_ratio - 1.0) * 5, 1.0), 2),
    }

    # ── Node 6: Black Level ────────────────────────────────────────
    shadow_threshold = np.percentile(lum_flat, 5)
    shadow_mask = lum_flat < shadow_threshold
    shadow_pixels = lum_flat[shadow_mask]
    shadow_noise = np.std(shadow_pixels)
    shadow_mean = np.mean(shadow_pixels)

    # Check shadow color neutrality
    shadow_mask_2d = lum < shadow_threshold
    if np.sum(shadow_mask_2d) > 100:
        shadow_r = np.mean(r[shadow_mask_2d])
        shadow_g = np.mean(g[shadow_mask_2d])
        shadow_b = np.mean(b[shadow_mask_2d])
        shadow_color_deviation = max(
            abs(shadow_r - shadow_g),
            abs(shadow_g - shadow_b),
            abs(shadow_r - shadow_b)
        )
    else:
        shadow_r = shadow_g = shadow_b = 0
        shadow_color_deviation = 0

    # Milky blacks: if p01 > 0.05, blacks are lifted
    milky_blacks = p01 > 0.05

    results['node6_black_level'] = {
        'black_point': round(p01, 4),
        'shadow_mean': round(shadow_mean, 4),
        'shadow_noise_std': round(shadow_noise, 4),
        'shadow_color': {'r': round(shadow_r, 4), 'g': round(shadow_g, 4), 'b': round(shadow_b, 4)},
        'shadow_color_deviation': round(shadow_color_deviation, 4),
        'milky_blacks': bool(milky_blacks),
        'assessment': (
            'milky/lifted blacks — crush recommended' if milky_blacks else
            'blacks are solid' if p01 < 0.02 else
            'blacks acceptable'
        ),
        'preset_recommendation': 'black_crush' if milky_blacks else 'none',
        'recommended_strength': round(min((p01 - 0.02) * 10, 1.0), 2) if milky_blacks else 0,
    }

    # ── Summary ────────────────────────────────────────────────────
    results['summary'] = {
        'recommended_chain': [],
    }
    for key, node_name in [
        ('node2_contrast', 'Contrast'),
        ('node3_white_balance', 'White Balance'),
        ('node4_skin', 'Skin Tone'),
        ('node5_saturation', 'Saturation'),
        ('node6_black_level', 'Black Level'),
    ]:
        preset = results[key]['preset_recommendation']
        strength = results[key]['recommended_strength']
        if preset != 'none' and strength > 0:
            results['summary']['recommended_chain'].append({
                'node': node_name,
                'preset': preset,
                'strength': strength,
                'assessment': results[key]['assessment'],
            })

    return results


def print_report(results):
    """Print a human-readable grading report."""
    print("\n" + "=" * 60)
    print("  AUTO-GRADE ANALYSIS REPORT")
    print("=" * 60)

    n2 = results['node2_contrast']
    print(f"\n{'─' * 60}")
    print(f"  Node 2: CONTRAST / EXPOSURE")
    print(f"{'─' * 60}")
    print(f"  Black point (1%):   {n2['black_point_p01']:.4f}")
    print(f"  Median luminance:   {n2['median']:.4f}")
    print(f"  White point (99%):  {n2['white_point_p99']:.4f}")
    print(f"  Dynamic range:      {n2['dynamic_range']:.4f}")
    print(f"  Highlight clip:     {n2['highlight_clip_pct']:.1f}%")
    print(f"  Gamma correction:   {n2['gamma_recommendation']:.3f}")
    print(f"  Assessment:         {n2['assessment']}")
    print(f"  → Preset: {n2['preset_recommendation']} @ {int(n2['recommended_strength']*100)}%")

    n3 = results['node3_white_balance']
    print(f"\n{'─' * 60}")
    print(f"  Node 3: WHITE BALANCE / COLOR TEMPERATURE")
    print(f"{'─' * 60}")
    g = n3['blended_gains']
    print(f"  RGB gains:          R={g['r']:.4f}  G={g['g']:.4f}  B={g['b']:.4f}")
    print(f"  Deviation:          {n3['deviation_from_neutral']:.4f}")
    print(f"  Direction:          {n3['direction']}")
    print(f"  → Preset: {n3['preset_recommendation']} @ {int(n3['recommended_strength']*100)}%")

    n4 = results['node4_skin']
    print(f"\n{'─' * 60}")
    print(f"  Node 4: SKIN TONE")
    print(f"{'─' * 60}")
    print(f"  Skin pixels:        {n4['skin_pixels_pct']:.1f}%")
    if 'mean_hue' in n4:
        print(f"  Mean hue:           {n4['mean_hue']:.1f}° (target: {n4['target_hue']}°)")
        print(f"  Hue delta:          {n4['hue_delta']:.1f}°")
        print(f"  Mean saturation:    {n4['mean_saturation']:.3f}")
    print(f"  Assessment:         {n4['assessment']}")
    print(f"  → Preset: {n4['preset_recommendation']} @ {int(n4['recommended_strength']*100)}%")

    n5 = results['node5_saturation']
    print(f"\n{'─' * 60}")
    print(f"  Node 5: SATURATION")
    print(f"{'─' * 60}")
    print(f"  Colorfulness:       {n5['colorfulness']:.2f} (target: {n5['target_colorfulness']})")
    print(f"  Sat ratio:          {n5['sat_ratio']:.3f}")
    print(f"  Assessment:         {n5['assessment']}")
    print(f"  → Preset: {n5['preset_recommendation']} @ {int(n5['recommended_strength']*100)}%")

    n6 = results['node6_black_level']
    print(f"\n{'─' * 60}")
    print(f"  Node 6: BLACK LEVEL")
    print(f"{'─' * 60}")
    print(f"  Black point:        {n6['black_point']:.4f}")
    print(f"  Shadow noise:       {n6['shadow_noise_std']:.4f}")
    sc = n6['shadow_color']
    print(f"  Shadow color:       R={sc['r']:.4f} G={sc['g']:.4f} B={sc['b']:.4f}")
    print(f"  Milky blacks:       {'YES' if n6['milky_blacks'] else 'no'}")
    print(f"  Assessment:         {n6['assessment']}")
    print(f"  → Preset: {n6['preset_recommendation']} @ {int(n6['recommended_strength']*100)}%")

    print(f"\n{'=' * 60}")
    print(f"  RECOMMENDED NODE CHAIN")
    print(f"{'=' * 60}")
    chain = results['summary']['recommended_chain']
    if chain:
        for step in chain:
            print(f"  [{step['node']}] {step['preset']} @ {int(step['strength']*100)}% — {step['assessment']}")
    else:
        print("  No corrections needed — image looks well-graded.")
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='auto_grade.py',
        description='Analyze a Rec.709 frame and recommend node corrections.')
    parser.add_argument('frame', help='frame to analyse (PNG/JPEG)')
    parser.add_argument('--emit', metavar='OUT.cube',
                        help='fit and write a correction LUT for this frame')
    parser.add_argument('--size', type=int, default=33,
                        help='emitted LUT grid size (default: 33)')
    parser.add_argument('--no-json', action='store_true',
                        help='skip writing the _analysis.json sidecar')
    args = parser.parse_args(argv)

    results = analyze_frame(args.frame)
    print_report(results)

    if not args.no_json:
        json_path = args.frame.rsplit('.', 1)[0] + '_analysis.json'
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"  JSON saved: {json_path}\n")

    if args.emit:
        # Closing the loop: rather than leave the user to transcribe the
        # recommendations, fit the correction by measurement and bake it.
        import solve_grade

        image = np.array(Image.open(args.frame).convert('RGB'))
        plan = solve_grade.solve(image)
        solve_grade.report(image, plan, os.path.basename(args.frame))
        plan.write_cube(args.emit, size=args.size)
        print(f"\n  Wrote {args.emit}\n")

    return 0


if __name__ == '__main__':
    sys.exit(main())

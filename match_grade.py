#!/usr/bin/env python3
"""match_grade.py — Match one frame's grade to another, and emit the LUT.

This used to print prose for a human to act on ("increase r_gain by ~0.012")
and detected skin with a per-pixel colorsys loop that took seconds on a 4K
frame. Both are gone: it now fits the correction the same way solve_grade.py
does — apply, re-measure, keep what closes the gap — and hands you a .cube.

The difference from solve_grade.py is the target. There, the targets are fixed
(neutral white balance, 0.45 median, and so on). Here the target is another
image: match this shot to that one.

    python3 match_grade.py reference.png output.png --emit match.cube
"""

import argparse
import os
import sys

import numpy as np

import footage_type
import grade_metrics
import solve_grade

# Same scale search as the fixed-target solver.
SCALE_GRID = solve_grade.SCALE_GRID


# ── Distance between two images ──────────────────────────────────────

def descriptor(image):
    """The measurements a match is judged on.

    Deliberately global and low-dimensional: two frames of the same scene will
    never agree pixel for pixel, and trying to make them is how a match turns
    into a smear.
    """
    arr = grade_metrics._as_float(image)
    lum = grade_metrics.luminance(arr)

    shadow = float(np.percentile(lum, 5))
    highlight = float(np.percentile(lum, 95))

    desc = {
        'median': float(np.median(lum)),
        'shadow': shadow,
        'highlight': highlight,
        'contrast': highlight - shadow,
    }

    # Channel balance on the pixels that carry illuminant information.
    mask = grade_metrics.illuminant_mask(arr)
    pixels = arr[mask] if mask.any() else arr.reshape(-1, 3)
    for i, name in enumerate(('r', 'g', 'b')):
        desc[f'mean_{name}'] = float(np.mean(pixels[:, i]))

    desc['skin_hue'] = grade_metrics.skin_hue(arr)
    desc['skin_confidence'] = grade_metrics.skin_confidence(arr)
    return desc


# How much each term counts toward the match. Channel balance dominates,
# because a colour mismatch between two shots is what an audience notices.
DISTANCE_WEIGHTS = {
    'mean_r': 2.0, 'mean_g': 2.0, 'mean_b': 2.0,
    'median': 1.2,
    'shadow': 0.8,
    'highlight': 0.8,
    'contrast': 0.6,
}


def distance(reference, candidate):
    """Scalar gap between two descriptors. 0 is a perfect match."""
    total = 0.0
    for key, weight in DISTANCE_WEIGHTS.items():
        total += weight * abs(reference[key] - candidate[key])

    # Skin hue only counts when both frames actually contain skin.
    if reference['skin_hue'] is not None and candidate['skin_hue'] is not None:
        ramp = min(min(reference['skin_confidence'],
                       candidate['skin_confidence']) /
                   grade_metrics.FULL_SKIN_CONFIDENCE, 1.0)
        total += 0.5 * abs(reference['skin_hue'] -
                           candidate['skin_hue']) / 30.0 * ramp

    return total


# ── Fitting toward the reference ─────────────────────────────────────

def fit_channel_balance(target, current):
    """Solve the gains that bring the channel means onto the reference."""
    ref = descriptor(target)
    cur = descriptor(current)

    def ratio(name):
        denominator = cur[f'mean_{name}']
        return ref[f'mean_{name}'] / denominator if denominator > 1e-6 else 1.0

    # Normalise against green, the industry convention and what rgb_rebalance
    # expects.
    green = ratio('g')
    gain_r = ratio('r') / green if green > 1e-6 else 1.0
    gain_b = ratio('b') / green if green > 1e-6 else 1.0

    if max(abs(gain_r - 1.0), abs(gain_b - 1.0)) < 0.005:
        return None

    def build(scale):
        return [{'pipeline': [solve_grade.rgb_rebalance_step(
            1.0 + (gain_r - 1.0) * scale, 1.0,
            1.0 + (gain_b - 1.0) * scale)], 'strength': 1.0}]

    return build, 'matched_white_balance'


def fit_exposure_to(target, current):
    """Solve the gamma that puts the median onto the reference's."""
    ref = descriptor(target)['median']
    cur = descriptor(current)['median']

    if not (0.01 < cur < 0.99 and 0.01 < ref < 0.99):
        return None
    if abs(ref - cur) < 0.01:
        return None

    gamma = np.log(ref) / np.log(cur)

    def build(scale):
        return [{'pipeline': [solve_grade.exposure_step(
            1.0 + (gamma - 1.0) * scale)], 'strength': 1.0}]

    return build, 'matched_exposure'


def fit_black_level_to(target, current):
    """Solve a crush that brings the shadow point onto the reference's."""
    ref = descriptor(target)['shadow']
    cur = descriptor(current)['shadow']

    if cur - ref < 0.01:
        return None   # already at or below the reference's floor

    def build(scale):
        return [{'pipeline': [solve_grade.black_crush_step(
            black_threshold=max(0.01, cur * 0.4),
            crush_gamma=1.0 + 1.6 * scale,
            transition_end=min(0.5, max(0.12, cur * 2.6)))], 'strength': 1.0}]

    return build, 'matched_black_level'


MATCHERS = [
    ('white_balance', fit_channel_balance, False),
    ('exposure', fit_exposure_to, True),
    ('black_level', fit_black_level_to, True),
]


def match(reference, output, size=solve_grade.SOLVE_SIZE, transfer='auto'):
    """Fit a chain that moves `output` toward `reference`."""
    ref = grade_metrics._as_float(reference)
    current = grade_metrics._as_float(output)

    ref_footage = footage_type.detect(ref, assume=transfer)
    out_footage = footage_type.detect(current, assume=transfer)

    # Matching a display-referred reference from log footage (or the reverse)
    # is not a grading problem, it is a missing conversion LUT.
    mismatched = ref_footage.kind != out_footage.kind
    tone_ok = ref_footage.tone_targets_apply and out_footage.tone_targets_apply

    ref_desc = descriptor(ref)
    chain = []
    skipped = []

    for stage, matcher, needs_display in MATCHERS:
        if needs_display and not tone_ok:
            skipped.append(stage)
            continue

        fitted = matcher(ref, current)
        if fitted is None:
            continue
        build, label = fitted

        best_scale, best_steps, best_image = 0.0, None, current
        best_gap = distance(ref_desc, descriptor(current))

        solve_grade.bake_many([(build(s), None) for s in SCALE_GRID if s > 0],
                              size)

        for scale in SCALE_GRID:
            if scale <= 0:
                continue
            steps = build(scale)
            candidate = solve_grade.lut_for(steps, size).apply(current)
            gap = distance(ref_desc, descriptor(candidate))
            if gap < best_gap - 1e-9:
                best_gap, best_scale = gap, scale
                best_steps, best_image = steps, candidate

        if best_steps is not None:
            chain.append({'preset': label, 'strength': best_scale,
                          'steps': best_steps})
            current = best_image

    plan = solve_grade.GradePlan(chain, size, footage=out_footage,
                                 skipped=skipped)
    plan.mismatched_transfer = mismatched
    plan.reference_footage = ref_footage
    return plan


# ── CLI ──────────────────────────────────────────────────────────────

def report(reference, output, plan):
    ref = descriptor(reference)
    before = descriptor(output)
    after = descriptor(plan.apply(output))

    print(f'\n  {"":14s} {"reference":>11s} {"before":>11s} {"after":>11s}')
    print(f'  {"-" * 52}')
    for key in ('median', 'shadow', 'highlight', 'contrast',
                'mean_r', 'mean_g', 'mean_b'):
        print(f'  {key:14s} {ref[key]:>11.4f} {before[key]:>11.4f} '
              f'{after[key]:>11.4f}')

    print(f'\n  match distance  {distance(ref, before):>11.4f} -> '
          f'{distance(ref, after):.4f}')

    print('\n  Fitted chain:')
    if plan.chain:
        for step in plan.chain:
            print(f'    {step["preset"]:24s} @ {step["strength"]:.0%}')
    else:
        print('    (none - the two already match)')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Fit a LUT that matches one frame to another.')
    parser.add_argument('reference', help='the look to match')
    parser.add_argument('output', help='the frame to correct')
    parser.add_argument('--emit', metavar='OUT.cube',
                        help='write the fitted match LUT')
    parser.add_argument('--size', type=int, default=solve_grade.EMIT_SIZE)
    parser.add_argument('--transfer', default='auto',
                        choices=footage_type.VALID_ASSUMPTIONS)
    args = parser.parse_args(argv)

    from PIL import Image

    reference = np.array(Image.open(args.reference).convert('RGB'))
    output = np.array(Image.open(args.output).convert('RGB'))

    plan = match(reference, output, transfer=args.transfer)

    print(f'\n  reference: {os.path.basename(args.reference)} '
          f'[{plan.reference_footage.describe()}]')
    print(f'  output:    {os.path.basename(args.output)} '
          f'[{plan.footage.describe()}]')

    if plan.mismatched_transfer:
        print('\n  ! the two frames are not the same kind of footage — '
              'match a converted frame against a converted reference, '
              'not log against Rec.709')
    for warning in plan.warnings:
        print(f'\n  ! {warning}')

    report(reference, output, plan)

    if args.emit:
        plan.write_cube(args.emit, size=args.size)
        print(f'\n  Wrote {args.emit}')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())

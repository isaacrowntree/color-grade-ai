#!/usr/bin/env python3
"""solve_grade.py — Closed-loop grading: fit a correction to a frame.

The analyzer measures a frame and names presets that should help. It used to
guess how much of each to apply with hand-tuned constants (`deviation * 10`,
`abs(gamma - 1) * 5`). This module replaces guessing with measurement: it
applies a candidate correction, re-measures the result, and keeps what actually
reduces the remaining error.

It also *synthesises* corrections rather than only picking from the preset
library. The library is deliberately gentle — cool_shift is a 4% channel shift
at full strength — so no combination of library presets can neutralise a 22%
tungsten cast. For white balance and exposure the solver therefore fits the
parameters directly from the measurement and bakes a bespoke pipeline.

Ruby stays the single source of truth for the colour maths; this module only
decides which steps to assemble and how strongly.

    python3 solve_grade.py frame.png --emit fix.cube
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

import numpy as np

import footage_type
import grade_metrics
from lut_apply import CubeLUT

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, 'tmp', 'lut_cache')

# Coarse grid while solving (fast, and far finer than the measurement noise),
# full resolution for the LUT the user actually receives.
SOLVE_SIZE = 17
EMIT_SIZE = 33

# Scale factors applied to a fitted correction. 1.0 means "exactly what the
# measurement implies"; the solver searches around it because the estimator is
# not perfect and overcorrection is worse than slight undercorrection.
SCALE_GRID = [round(i * 0.1, 2) for i in range(0, 16)]

_lut_cache = {}


# ── Step construction ────────────────────────────────────────────────

def rgb_rebalance_step(gain_r, gain_g, gain_b, gain_ramp=0.05):
    return {
        'step': 'rgb_rebalance',
        'r_gain': gain_r, 'g_gain': gain_g, 'b_gain': gain_b,
        'gain_ramp': gain_ramp,
    }


def exposure_step(gamma, shadow_lift=0.0):
    return {'step': 'exposure', 'gamma': gamma, 'shadow_lift': shadow_lift}


def black_crush_step(black_threshold, crush_gamma, transition_end):
    return {
        'step': 'black_crush',
        'black_threshold': black_threshold,
        'crush_gamma': crush_gamma,
        'transition_end': transition_end,
    }


def load_preset_pipeline(name):
    """Read a pipeline out of presets.yml without a YAML dependency clash."""
    import yaml  # noqa: F401  (only needed when a library preset is used)
    path = os.path.join(HERE, 'presets.yml')
    with open(path, encoding='utf-8') as f:
        presets = yaml.safe_load(f)
    if name not in presets:
        raise KeyError(f'unknown preset: {name}')
    return presets[name]['pipeline']


# ── LUT supply ───────────────────────────────────────────────────────

def _digest(steps, size):
    payload = json.dumps({'steps': steps, 'size': size}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


def bake(steps, size, path=None):
    """Bake a chain of {pipeline, strength} steps into a .cube."""
    return bake_many([(steps, path)], size)[0]


def bake_many(jobs, size):
    """Bake several chains in one Ruby invocation.

    jobs: list of (steps, path_or_None). Returns the list of written paths.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    outputs = []
    paths = []
    for steps, path in jobs:
        if path is None:
            path = os.path.join(CACHE_DIR, f'{_digest(steps, size)}.cube')
        paths.append(path)
        if not os.path.exists(path):
            outputs.append({'path': path, 'title': 'fitted correction',
                            'steps': steps})

    if outputs:
        request = json.dumps({'size': size, 'outputs': outputs})
        result = subprocess.run(['ruby', 'bake_lut.rb'], input=request,
                                capture_output=True, text=True, cwd=HERE)
        if result.returncode != 0:
            raise RuntimeError(f'bake_lut.rb failed: {result.stderr}')

    return paths


def lut_for(steps, size):
    key = (_digest(steps, size), size)
    if key not in _lut_cache:
        _lut_cache[key] = CubeLUT.load(bake(steps, size))
    return _lut_cache[key]


# ── Fitting individual corrections ───────────────────────────────────

def fit_white_balance(image):
    """Solve channel gains directly from the illuminant estimate."""
    gain_r, gain_b = grade_metrics.shades_of_gray_gains(image)
    if max(abs(gain_r - 1.0), abs(gain_b - 1.0)) < 0.01:
        return None

    def build(scale):
        return [{'pipeline': [rgb_rebalance_step(
            1.0 + (gain_r - 1.0) * scale, 1.0,
            1.0 + (gain_b - 1.0) * scale)], 'strength': 1.0}]

    return build, _describe_wb(gain_r, gain_b)


def _describe_wb(gain_r, gain_b):
    if gain_r > 1.02 and gain_b > 1.02:
        return 'fitted_green_fix'
    if gain_r < 0.98 and gain_b < 0.98:
        return 'fitted_magenta_fix'
    if gain_r < 0.98 and gain_b > 1.02:
        return 'fitted_cool_shift'
    if gain_b < 0.98 and gain_r > 1.02:
        return 'fitted_warm_shift'
    return 'fitted_white_balance'


def fit_exposure(image):
    """Solve the gamma that puts the median at the target."""
    median = float(np.median(grade_metrics.luminance(image)))
    if not 0.01 < median < 0.99:
        return None
    if abs(median - grade_metrics.TARGET_MEDIAN_LUMA) < 0.015:
        return None

    gamma = np.log(grade_metrics.TARGET_MEDIAN_LUMA) / np.log(median)

    def build(scale):
        scaled = 1.0 + (gamma - 1.0) * scale
        return [{'pipeline': [exposure_step(scaled)], 'strength': 1.0}]

    label = 'fitted_exposure_lift' if gamma < 1.0 else 'fitted_exposure_pull'
    return build, label


def fit_black_level(image):
    """Solve a crush that brings the black point down to target."""
    p01 = float(np.percentile(grade_metrics.luminance(image), 1))
    if p01 <= grade_metrics.TARGET_BLACK_POINT + 0.01:
        return None

    # Crush everything below roughly twice the measured floor, hardest at the
    # bottom, so the lift is removed without flattening real shadow detail.
    transition_end = min(0.5, max(0.12, p01 * 2.6))

    def build(scale):
        crush_gamma = 1.0 + 1.6 * scale
        return [{'pipeline': [black_crush_step(
            black_threshold=max(0.01, p01 * 0.4),
            crush_gamma=crush_gamma,
            transition_end=transition_end)], 'strength': 1.0}]

    return build, 'fitted_black_crush'


def fit_saturation(image):
    """Solve a global saturation multiplier, but only when clearly out of band.

    There is no saturation target to fit toward — colourfulness is a property
    of the scene — so this aims at the nearest edge of the plausible range
    rather than at a number, and does nothing inside it.
    """
    error = grade_metrics.saturation_error(image)
    if error == 0.0:
        return None

    current = grade_metrics.colorfulness(image)
    low, high = grade_metrics.SATURATION_BAND
    edge = low if error < 0 else high
    if current <= 1e-6:
        return None

    # Colourfulness moves roughly linearly with an HSL saturation multiplier,
    # so the ratio to the band edge is a good first estimate; the scale search
    # corrects the rest.
    boost = edge / current

    def build(scale):
        scaled = 1.0 + (boost - 1.0) * scale
        return [{'pipeline': [{'step': 'global_sat', 'boost': scaled}],
                 'strength': 1.0}]

    return build, 'fitted_saturation'


def fit_skin(image):
    """Skin hue is a shape correction, so use the tuned library preset."""
    if grade_metrics.skin_hue_error(image) <= 3.0:
        return None
    if grade_metrics.skin_confidence(image) < grade_metrics.MIN_SKIN_FRACTION:
        return None

    pipeline = load_preset_pipeline('red_skin_fix')

    def build(scale):
        return [{'pipeline': pipeline, 'strength': min(scale, 1.0)}]

    return build, 'red_skin_fix'


# Conventional node order: balance, expose, skin, then black level.
#
# `tone` marks stages whose targets assume display-referred Rec.709. A 0.45
# median and a 0.02 black point describe a graded image, not a log container,
# so these are held back unless the footage is confirmed display-referred.
# White balance and skin hue are not tone-dependent: a cast is a cast, and skin
# should read as skin, whatever the transfer curve.
# Saturation is display-only for the same reason as the tone stages: log is
# desaturated by design (37.6 against 63.8 for the same scene in Rec.709), so
# "correcting" it would be actively wrong.
FITTERS = [
    ('white_balance', fit_white_balance, False),
    ('exposure', fit_exposure, True),
    ('skin', fit_skin, False),
    ('saturation', fit_saturation, True),
    ('black_level', fit_black_level, True),
]

# What the unoptimised path uses, so the comparison is like for like.
HEURISTIC_SCALE = 1.0


# ── The plan ─────────────────────────────────────────────────────────

class GradePlan:
    """An ordered chain of fitted corrections."""

    def __init__(self, chain, size=SOLVE_SIZE, footage=None, skipped=()):
        self.chain = chain
        self.size = size
        self.footage = footage
        self.skipped = list(skipped)

    @property
    def warnings(self):
        notes = list(self.footage.warnings) if self.footage else []
        if self.skipped:
            notes.append(
                'held back on this footage: ' + ', '.join(self.skipped) +
                ' — these fit against display-referred targets')
        return notes

    def __repr__(self):
        if not self.chain:
            return 'GradePlan(no corrections)'
        steps = ', '.join(f"{s['preset']}@{s['strength']:.2f}" for s in self.chain)
        return f'GradePlan({steps})'

    @property
    def steps(self):
        """Flattened pipeline steps, in order, for baking."""
        flat = []
        for entry in self.chain:
            flat.extend(entry['steps'])
        return flat

    def apply(self, image):
        out = grade_metrics._as_float(image)
        for entry in self.chain:
            out = lut_for(entry['steps'], self.size).apply(out)
        return out

    def write_cube(self, path, size=EMIT_SIZE):
        if not self.chain:
            # An honest no-op rather than a refusal: an identity LUT still
            # slots into a node chain.
            steps = [{'pipeline': [exposure_step(1.0)], 'strength': 0.0}]
        else:
            steps = self.steps
        bake(steps, size, path)
        return path

    def as_dict(self):
        return {'chain': [{'preset': s['preset'], 'strength': s['strength']}
                          for s in self.chain]}


# ── The solver ───────────────────────────────────────────────────────

def solve(image, optimise=True, size=SOLVE_SIZE, transfer='auto'):
    """Fit a correction chain to a frame.

    optimise=True   search the scale that actually minimises measured error
    optimise=False  apply each fit at face value, without verifying it helps
    transfer        'auto' to detect log vs display-referred, or state it
    """
    arr = grade_metrics._as_float(image)
    footage = footage_type.detect(arr, assume=transfer)

    chain, skipped = _build_chain(arr, optimise, size, footage)

    if optimise:
        # The stage-by-stage search is greedy: it only accepts a scale that
        # improves the score at that point, so a locally unhelpful step that
        # would have set up a better final result gets dropped. On two of the
        # nine evaluation cases that left it behind the un-searched fit.
        #
        # Rather than tune the greedy rule, keep the face-value chain as a
        # floor and return whichever actually measures better. The solver can
        # then never be worse than not searching at all.
        face_value, _ = _build_chain(arr, False, size, footage)
        if _score(arr, face_value, size) < _score(arr, chain, size) - 1e-9:
            chain = face_value

    return GradePlan(chain, size, footage=footage, skipped=skipped)


def _score(image, chain, size):
    out = image
    for entry in chain:
        out = lut_for(entry['steps'], size).apply(out)
    return grade_metrics.total_error(out)


def _build_chain(image, optimise, size, footage):
    current = image
    chain = []
    skipped = []

    for stage, fitter, needs_display in FITTERS:
        if needs_display and not footage.tone_targets_apply:
            skipped.append(stage)
            continue

        fitted = fitter(current)
        if fitted is None:
            continue
        build, label = fitted

        if not optimise:
            steps = build(HEURISTIC_SCALE)
            chain.append({'preset': label, 'strength': HEURISTIC_SCALE,
                          'steps': steps})
            current = lut_for(steps, size).apply(current)
            continue

        best_scale = 0.0
        best_error = grade_metrics.total_error(current)
        best_image = current
        best_steps = None

        # Batch every candidate for this stage into one Ruby call.
        candidates = [(build(s), None) for s in SCALE_GRID if s > 0]
        bake_many(candidates, size)

        for scale in SCALE_GRID:
            if scale <= 0:
                continue
            steps = build(scale)
            result = lut_for(steps, size).apply(current)
            error = grade_metrics.total_error(result)
            if error < best_error - 1e-6:
                best_error, best_scale = error, scale
                best_image, best_steps = result, steps

        if best_steps is not None:
            chain.append({'preset': label, 'strength': best_scale,
                          'steps': best_steps})
            current = best_image

    return chain, skipped


# ── CLI ──────────────────────────────────────────────────────────────

def report(image, plan, name=''):
    if plan.footage is not None:
        print(f'\n  Footage: {plan.footage.describe()}')
    before = grade_metrics.measure(image)
    graded = plan.apply(image)
    after = grade_metrics.measure(graded)

    print(f'\n  {name}')
    print(f'  {"-" * 56}')
    print(f'  {"":18s} {"before":>10s} {"after":>10s}')
    for key in ('white_balance', 'exposure', 'black_level', 'skin_hue'):
        print(f'  {key:18s} {before[key]:>10.4f} {after[key]:>10.4f}')
    print(f'  {"total":18s} {grade_metrics.total_error(image):>10.4f} '
          f'{grade_metrics.total_error(graded):>10.4f}')
    print(f'\n  skin detected in {before["skin_confidence"]:.1%} of the frame')

    for warning in plan.warnings:
        print(f'\n  ! {warning}')

    print(f'\n  Fitted chain:')
    if plan.chain:
        for step in plan.chain:
            print(f'    {step["preset"]:24s} @ {step["strength"]:.0%}')
    else:
        print('    (none - frame already measures clean)')


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Fit a correction LUT to a frame by closed-loop measurement.')
    parser.add_argument('frame', help='frame to analyse (PNG/JPEG)')
    parser.add_argument('--emit', metavar='OUT.cube',
                        help='write the fitted correction LUT')
    parser.add_argument('--no-optimise', action='store_true',
                        help='apply fits at face value without verifying them')
    parser.add_argument('--size', type=int, default=EMIT_SIZE,
                        help=f'emitted LUT grid size (default: {EMIT_SIZE})')
    parser.add_argument('--transfer', default='auto',
                        choices=footage_type.VALID_ASSUMPTIONS,
                        help='log or display-referred; default is to detect')
    args = parser.parse_args(argv)

    from PIL import Image

    image = np.array(Image.open(args.frame).convert('RGB'))
    plan = solve(image, optimise=not args.no_optimise, transfer=args.transfer)
    report(image, plan, os.path.basename(args.frame))

    if args.emit:
        plan.write_cube(args.emit, size=args.size)
        print(f'\n  Wrote {args.emit}')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())

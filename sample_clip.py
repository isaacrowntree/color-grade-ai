#!/usr/bin/env python3
"""sample_clip.py — Grade from a clip rather than one arbitrary frame.

Grading off a single frame assumes the rest of the clip looks like it. That
assumption breaks constantly: a subject walks under a different practical, the
camera pans off a window, an editor joins two shots. This module samples across
a clip, aggregates the measurements robustly, and says so when the clip is not
consistent enough to deserve one LUT.

    python3 sample_clip.py clip.mov --emit fix.cube
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

import footage_type
import grade_metrics
import solve_grade

DEFAULT_SAMPLES = 12

# Above this spread across sampled frames, one LUT for the whole clip is the
# wrong answer and the user should be told rather than handed a compromise.
INCONSISTENT_THRESHOLDS = {
    'white_balance': 0.06,
    'exposure': 0.10,
    'black_level': 0.06,
}


# ── Probing ──────────────────────────────────────────────────────────

def probe_duration(path):
    """Clip duration in seconds."""
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'json', path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f'ffprobe failed for {path}: {result.stderr.strip()}')

    duration = json.loads(result.stdout)['format'].get('duration')
    if duration is None:
        raise RuntimeError(f'{path}: no duration reported')
    return float(duration)


def probe_frame_count(path):
    """Number of frames, or None when the container does not say."""
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
         '-count_frames', '-show_entries', 'stream=nb_read_frames',
         '-of', 'json', path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout)['streams'][0]['nb_read_frames']
        return int(value)
    except (KeyError, IndexError, ValueError, TypeError):
        return None


def sample_timestamps(path, count=DEFAULT_SAMPLES):
    """Evenly spaced timestamps, avoiding the very first and last frames.

    The head and tail of a clip are the least representative parts of it —
    handles, fades, and the operator still settling.
    """
    duration = probe_duration(path)

    available = probe_frame_count(path)
    if available:
        count = max(1, min(count, available))

    if count == 1:
        return [duration / 2.0]

    margin = duration * 0.05
    usable = max(duration - 2 * margin, 1e-3)
    return [margin + usable * i / (count - 1) for i in range(count)]


def sample_frames(path, count=DEFAULT_SAMPLES):
    """Extract frames spread across the clip as float arrays in 0-1."""
    stamps = sample_timestamps(path, count)
    frames = []

    with tempfile.TemporaryDirectory() as tmp:
        for i, stamp in enumerate(stamps):
            out = os.path.join(tmp, f'{i:04d}.png')
            result = subprocess.run(
                ['ffmpeg', '-v', 'error', '-ss', f'{stamp:.4f}', '-i', path,
                 '-frames:v', '1', '-y', out],
                capture_output=True, text=True,
            )
            if result.returncode != 0 or not os.path.exists(out):
                continue
            frames.append(np.array(Image.open(out).convert('RGB'),
                                   dtype=np.float64) / 255.0)

    if not frames:
        raise RuntimeError(f'{path}: could not extract any frames')
    return frames


# ── Aggregation ──────────────────────────────────────────────────────

def aggregate_value(values):
    """Median, not mean: one blown or black frame must not steer the grade."""
    return float(np.median(np.asarray(values, dtype=np.float64)))


def spread(values):
    """Robust spread: the interquartile range."""
    arr = np.asarray(values, dtype=np.float64)
    return float(np.percentile(arr, 75) - np.percentile(arr, 25))


def analyze_clip(path, count=DEFAULT_SAMPLES):
    """Measure a clip across several frames and report how consistent it is."""
    stamps = sample_timestamps(path, count)
    frames = sample_frames(path, count)

    per_frame = []
    for stamp, frame in zip(stamps, frames):
        entry = grade_metrics.measure(frame)
        entry['timestamp'] = round(stamp, 3)
        per_frame.append(entry)

    keys = ('white_balance', 'exposure', 'black_level', 'skin_hue',
            'skin_confidence')
    aggregate = {k: aggregate_value([e[k] for e in per_frame]) for k in keys}
    variation = {k: spread([e[k] for e in per_frame]) for k in keys}

    warnings = []
    inconsistent = False
    for key, limit in INCONSISTENT_THRESHOLDS.items():
        if variation[key] > limit:
            inconsistent = True
            warnings.append(
                f'{key.replace("_", " ")} varies across the clip '
                f'(spread {variation[key]:.3f} > {limit:.2f}) — '
                f'consider grading shots separately')

    if aggregate['skin_confidence'] < 0.01:
        warnings.append('little or no skin detected — '
                        'skin correction will be skipped')

    return {
        'path': path,
        'frames': per_frame,
        'aggregate': aggregate,
        'variation': variation,
        'inconsistent': inconsistent,
        'warnings': warnings,
    }


def representative_frame(path, count=DEFAULT_SAMPLES):
    """The sampled frame closest to the clip's aggregate behaviour.

    Fitting against a real frame rather than a synthesised average keeps the
    optimiser working on an image that actually occurs in the clip.
    """
    frames = sample_frames(path, count)
    scores = [grade_metrics.total_error(f) for f in frames]
    target = aggregate_value(scores)
    best = int(np.argmin([abs(s - target) for s in scores]))
    return frames[best]


def solve_clip(path, count=DEFAULT_SAMPLES, transfer='auto'):
    """Fit one correction for the whole clip."""
    return solve_grade.solve(representative_frame(path, count), transfer=transfer)


# ── CLI ──────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Analyse a clip across several frames and fit one LUT.')
    parser.add_argument('clip', help='video file')
    parser.add_argument('--emit', metavar='OUT.cube',
                        help='write the fitted correction LUT')
    parser.add_argument('--frames', type=int, default=DEFAULT_SAMPLES,
                        help=f'frames to sample (default: {DEFAULT_SAMPLES})')
    parser.add_argument('--size', type=int, default=solve_grade.EMIT_SIZE,
                        help='emitted LUT grid size')
    parser.add_argument('--transfer', default='auto',
                        choices=footage_type.VALID_ASSUMPTIONS,
                        help='log or display-referred; default is to detect')
    args = parser.parse_args(argv)

    analysis = analyze_clip(args.clip, args.frames)
    agg = analysis['aggregate']
    var = analysis['variation']

    print(f'\n  {os.path.basename(args.clip)} — {len(analysis["frames"])} frames sampled')
    print(f'  {"-" * 56}')
    print(f'  {"":18s} {"median":>10s} {"spread":>10s}')
    for key in ('white_balance', 'exposure', 'black_level', 'skin_hue'):
        print(f'  {key:18s} {agg[key]:>10.4f} {var[key]:>10.4f}')
    print(f'\n  skin detected in {agg["skin_confidence"]:.1%} of the frame (median)')

    for warning in analysis['warnings']:
        print(f'\n  ! {warning}')

    frame = representative_frame(args.clip, args.frames)
    plan = solve_grade.solve(frame, transfer=args.transfer)
    print(f'\n  Footage: {plan.footage.describe()}')
    for warning in plan.warnings:
        print(f'  ! {warning}')
    print(f'\n  Fitted chain:')
    if plan.chain:
        for step in plan.chain:
            print(f'    {step["preset"]:24s} @ {step["strength"]:.0%}')
    else:
        print('    (none - clip already measures clean)')

    if args.emit:
        plan.write_cube(args.emit, size=args.size)
        print(f'\n  Wrote {args.emit}')
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())

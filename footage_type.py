#!/usr/bin/env python3
"""footage_type.py — Is this frame log, or display-referred?

Every correction LUT in this repo is built for display-referred Rec.709 and is
meant to be applied *after* a camera conversion LUT. Handed log footage, the
analyzer sees lifted blacks and flat contrast, calls them defects, and fits a
correction for something that is supposed to be there. The output looks
plausible and is wrong, which is worse than failing.

So the distinction is made explicit: measured, reported out loud, and allowed
to change what the tool does.

Detection reads the shape of the encoding rather than any metadata, because by
the time a frame reaches here it is usually a PNG with nothing left to read:

  - lifted black point   log never reaches 0; S-Log3 puts black near 0.09
  - rolled highlights    log holds headroom, so nothing approaches 1.0
  - compressed range     the whole image sits in a narrow band
  - low purity           log is desaturated before the conversion LUT

Any one of these can occur in display-referred footage — milky blacks, a flat
grade, an overexposed frame with a raised floor. Log shows most of them at
once, so classification requires a majority rather than any single signal.
"""

import numpy as np

# Thresholds. Deliberately conservative: calling display-referred footage "log"
# would block a legitimate grade, so the bar for log is a clear majority.
BLACK_LIFT_MIN = 0.06        # log black sits well above zero
HIGHLIGHT_CEILING = 0.80     # log keeps headroom
RANGE_CEILING = 0.55         # log occupies a narrow band
PURITY_CEILING = 0.35        # log is desaturated pre-conversion

# A log curve spends disproportionate code values on shadows, which pushes the
# median high within the frame's range. This is the one signal that survives a
# linear remap: rescaling a display-referred image leaves the relative position
# untouched (measurably so — every display case sits at 0.446), while a log
# transfer moves it. It is not sufficient on its own, because underexposed log
# falls back into the display range.
MIDPOINT_LOG_MIN = 0.52

SHAPE_SIGNALS = 4            # black, highlight, range, purity
STRONG_SIGNALS = 3           # enough shape evidence to stop calling it display

VALID_ASSUMPTIONS = ('auto', 'log', 'display')


def _as_float(image):
    arr = np.asarray(image)
    if arr.dtype == np.uint8:
        return arr.astype(np.float64) / 255.0
    return arr.astype(np.float64)


def _luminance(arr):
    return 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]


def _mean_purity(arr):
    maxc = arr.max(axis=-1)
    minc = arr.min(axis=-1)
    return float(np.mean(np.where(maxc > 1e-6, 1.0 - minc / np.maximum(maxc, 1e-6), 0.0)))


class FootageType:
    """The verdict, plus everything needed to explain and act on it.

    Three outcomes, not two. A heavily flattened, lifted, desaturated
    display-referred grade is genuinely indistinguishable from log by shape
    alone, and guessing either way is worse than saying so: guessing 'log'
    blocks a legitimate grade, guessing 'display' produces a confidently wrong
    one. 'ambiguous' asks the user to state it, which they can always answer
    and the measurements never can.
    """

    def __init__(self, kind, confidence, evidence, stats, overridden=False):
        self.kind = kind                  # 'log' | 'display' | 'ambiguous'
        self.confidence = confidence      # 0-1
        self.evidence = evidence          # human-readable signals that fired
        self.stats = stats
        self.overridden = overridden

    @property
    def is_log(self):
        return self.kind == 'log'

    @property
    def needs_confirmation(self):
        return self.kind == 'ambiguous'

    @property
    def tone_targets_apply(self):
        """Whether exposure and black-level targets mean anything here.

        Only on confirmed display-referred footage. On log they do not: a 0.45
        median and a 0.02 black point describe a graded Rec.709 image, not a
        log container. On ambiguous footage the safe default is the same, since
        the cost of being wrong is a plausible-looking incorrect grade.
        """
        return self.kind == 'display'

    @property
    def warnings(self):
        if self.kind == 'log':
            return [
                'footage looks LOG, not display-referred Rec.709 — apply a '
                'camera conversion LUT first, then correct. Fitting exposure '
                'or black level against log is meaningless. '
                'Pass --transfer display to override.'
            ]
        if self.kind == 'ambiguous':
            return [
                'cannot tell whether this is LOG or a very flat display-'
                'referred grade — they measure the same. Tone fitting is '
                'held back until you say which: pass --transfer log or '
                '--transfer display. If it is log, apply a conversion LUT '
                'first.'
            ]
        return []

    def describe(self):
        labels = {
            'log': f'LOG (confidence {self.confidence:.0%})',
            'display': f'display-referred Rec.709 (confidence {self.confidence:.0%})',
            'ambiguous': 'AMBIGUOUS — log or a very flat display-referred grade',
        }
        label = labels[self.kind]
        if self.overridden:
            label += ' [set explicitly]'
        return label

    def as_dict(self):
        return {
            'kind': self.kind,
            'confidence': round(self.confidence, 3),
            'evidence': self.evidence,
            'overridden': self.overridden,
            'stats': {k: round(v, 4) for k, v in self.stats.items()},
        }


def measure(image):
    """The shape measurements detection is based on."""
    arr = _as_float(image)
    lum = _luminance(arr)
    p01 = float(np.percentile(lum, 1))
    p99 = float(np.percentile(lum, 99))
    span = max(p99 - p01, 1e-6)
    median = float(np.median(lum))
    return {
        'black_point': p01,
        'white_point': p99,
        'range': p99 - p01,
        'median': median,
        # Where the median sits within the frame's own range. Invariant under a
        # linear remap, so it distinguishes a rescaled display image from a
        # genuine log curve.
        'midpoint_position': (median - p01) / span,
        'purity': _mean_purity(arr),
    }


def detect(image, assume='auto'):
    """Classify a frame as log, display-referred, or ambiguous.

    assume='auto'     measure and decide (default)
    assume='log'      the caller knows it is log
    assume='display'  the caller knows it is not
    """
    return classify(measure(image), assume=assume)


def classify(stats, assume='auto'):
    """Classify from measurements alone.

    Split out from detect() so real footage can be covered by its measured
    shape without committing the frames themselves to the repo.
    """
    if assume not in VALID_ASSUMPTIONS:
        raise ValueError(
            f'unknown transfer assumption {assume!r}; '
            f'expected one of {", ".join(VALID_ASSUMPTIONS)}')

    signals = []
    if stats['black_point'] > BLACK_LIFT_MIN:
        signals.append(f'black point lifted to {stats["black_point"]:.3f} '
                       f'(> {BLACK_LIFT_MIN})')
    if stats['white_point'] < HIGHLIGHT_CEILING:
        signals.append(f'highlights stop at {stats["white_point"]:.3f} '
                       f'(< {HIGHLIGHT_CEILING})')
    if stats['range'] < RANGE_CEILING:
        signals.append(f'range compressed to {stats["range"]:.3f} '
                       f'(< {RANGE_CEILING})')
    if stats['purity'] < PURITY_CEILING:
        signals.append(f'low saturation, mean purity {stats["purity"]:.3f} '
                       f'(< {PURITY_CEILING})')

    fired = len(signals)

    log_midpoint = stats['midpoint_position'] > MIDPOINT_LOG_MIN
    if log_midpoint:
        signals.append(
            f'median sits high in the range at '
            f'{stats["midpoint_position"]:.3f} (> {MIDPOINT_LOG_MIN}), '
            f'as a log curve places it')

    if assume != 'auto':
        return FootageType(assume, 1.0, signals, stats, overridden=True)

    if fired < STRONG_SIGNALS:
        # Clearly display-referred: too few log characteristics to doubt it.
        return FootageType('display', 1.0 - fired / SHAPE_SIGNALS, signals, stats)

    if log_midpoint:
        # Log-shaped, plus the signature a linear remap cannot reproduce.
        return FootageType('log', min(1.0, (fired + 1) / (SHAPE_SIGNALS + 1)),
                           signals, stats)

    # Log-shaped, but without the midpoint signature this could equally be a
    # flat display-referred grade or underexposed log. Say so rather than guess.
    return FootageType('ambiguous', fired / SHAPE_SIGNALS, signals, stats)


def main(argv=None):
    import argparse
    from PIL import Image

    parser = argparse.ArgumentParser(
        description='Report whether a frame is log or display-referred.')
    parser.add_argument('frame')
    parser.add_argument('--transfer', choices=VALID_ASSUMPTIONS, default='auto')
    args = parser.parse_args(argv)

    image = np.array(Image.open(args.frame).convert('RGB'))
    result = detect(image, assume=args.transfer)

    print(f'\n  {args.frame}')
    print(f'  Footage: {result.describe()}')
    for key, value in result.stats.items():
        print(f'    {key:14s} {value:.4f}')
    if result.evidence:
        print('\n  Signals:')
        for item in result.evidence:
            print(f'    - {item}')
    for warning in result.warnings:
        print(f'\n  ! {warning}')
    print()
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())

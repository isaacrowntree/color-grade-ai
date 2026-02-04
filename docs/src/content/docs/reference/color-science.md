---
title: Color Science
description: Key concepts for understanding how the LUT generator works
---

## Color Spaces

**Rec.709** — The standard color space for HD displays. Small gamut, fixed gamma curve. What your audience sees on a normal monitor.

**Log curves** (ARRI LogC, Sony S-Log3, Canon C-Log) — Logarithmic encodings that compress maximum dynamic range from the sensor into a manageable file. Footage looks flat and desaturated by design. Each camera manufacturer defines their own curve.

**ACES** — Academy Color Encoding System. An open, scene-referred framework that encompasses all visible colors. The professional pipeline is: camera → Input Transform → ACES → Rendering Transform → Output Transform → display.

## How 3D LUTs Work

A 3D LUT (Look-Up Table) is a pre-calculated grid that maps input RGB values to output RGB values.

- A **33x33x33** grid contains **35,937 sample points**
- Values between grid points are interpolated (trilinear or tetrahedral)
- Each output channel depends on **all three** input channels — this allows cross-channel operations like shifting warm tones toward cool
- The `.cube` format is plain text: a header followed by RGB triplets

### 1D vs 3D

**1D LUTs** operate on each channel independently (like Photoshop Curves). They can adjust brightness, contrast, and gamma but can't do hue-selective work.

**3D LUTs** can change the red output based on the green and blue input values. This is what makes hue-selective corrections possible.

## HSL Color Model

The LUT generator works primarily in HSL (Hue, Saturation, Lightness) space:

- **Hue** (0-360°) — The color wheel position. Red=0°, Orange=30°, Yellow=60°, Green=120°, Blue=240°.
- **Saturation** (0-1) — How vivid the color is. 0 = grey, 1 = fully saturated.
- **Lightness** (0-1) — How bright. 0 = black, 0.5 = mid, 1 = white.

### Key Insight: Desaturating Warm Tones Produces Brown

When you desaturate orange in HSL, you get **brown/sepia**, not neutral grey. This is a mathematical property of the HSL model. The midpoint between vivid orange and grey is muddy brown.

For correcting warm color casts, it's better to:
- **Shift the hue** (rotate on the color wheel) — moves color without losing vibrancy
- **Rebalance RGB channels** (reduce R, boost B) — simulates a white balance correction
- **Use gentle desaturation** (15-20%) as a supplement, not the primary correction

## Targeting Skin in a LUT

Skin tones occupy a narrow band that's consistent across ethnicities:

| Property | Range |
|----------|-------|
| Hue | 10-35° |
| Saturation | 0.08-0.45 |
| Luminance | 0.25-0.75 |

Objects that overlap with skin in hue but differ in other dimensions:

| Object | Hue | Saturation | Luminance |
|--------|-----|------------|-----------|
| Skin | 10-35° | 0.08-0.45 | 0.25-0.75 |
| Warm light source | 15-40° | >0.60 | >0.85 |
| Wooden floor | 20-40° | 0.15-0.40 | <0.20 |
| Saturated warm object | 10-50° | >0.50 | varies |

By using **three-way windowing** (hue AND saturation AND luminance), you can isolate skin from all of these in a 3D LUT.

## LUT Limitations

LUTs process each pixel **independently**. They have zero knowledge of neighboring pixels. This means they cannot:

- Do noise reduction (requires spatial/temporal averaging)
- Do sharpening (requires edge detection)
- Distinguish a face from a similarly-colored wall
- Track objects between frames

For these operations, use your NLE's built-in tools (Resolve's NR, Qualifier, Power Windows) or dedicated plugins.

## Learning Resources

- **Color Correction Handbook** by Alexis Van Hurkman — the industry standard textbook
- **Blackmagic Official Training** — free at [blackmagicdesign.com/products/davinciresolve/training](https://www.blackmagicdesign.com/products/davinciresolve/training)
- **Cullen Kelly** (YouTube) — technically rigorous free color grading education from a Netflix/HBO colorist
- **MixingLight.com** — 1,200+ structured tutorials from working colorists (paid)
- **Frame.io ACES Guide** — [blog.frame.io/2019/09/09/guide-to-aces/](https://blog.frame.io/2019/09/09/guide-to-aces/)
- **Dado Valentic / Colour Training** — [colour.training](https://colour.training) — bridges color science and practical grading
- **Kodak Color Theory Workbook** — free PDF from Kodak covering fundamental color theory for motion pictures

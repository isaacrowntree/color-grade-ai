---
name: color-grade
description: Generate .cube 3D LUTs for color correction in DaVinci Resolve and Adobe Premiere Pro. Auto-analyze frames, recommend node settings, and preview grades interactively in-browser. Use when the user needs color grading, LUT generation, frame analysis, or auto-grade recommendations.
argument-hint: [lut-type] [output-path]
allowed-tools: Read, Bash(ruby *), Bash(python3 *), Bash(ffmpeg *), Bash(ffprobe *), Write, Glob, Grep
---

# Color Grade AI

Generate targeted .cube 3D LUTs for color correction. Auto-analyze frames and recommend DaVinci Resolve-style node chain settings. Interactive in-browser preview with Preact.

## Quick Start

```bash
# Generate a correction LUT (presets defined in presets.yml)
ruby generate_lut.rb <type> <output_path> [--strength=0.0-1.0]

# Bake multiple presets into a single .cube LUT
ruby generate_chain_lut.rb <output_path> <preset@strength> ...

# Auto-analyze a frame and get node recommendations
python3 auto_grade.py <frame.png>

# Compare reference vs output and get adjustment suggestions
python3 match_grade.py <reference.png> <output.png>

# Analyze specific regions for color stats
ruby analyze_frame.rb <image_path> <x1,y1,x2,y2> [label]

# Serve the interactive preview
python3 -m http.server 8080
# Open http://localhost:8080/preview.html
```

## Auto-Grade Analysis

`auto_grade.py` analyzes a Rec.709 frame (post-conversion LUT) and recommends correction values for each node using classical color science:

| Node | Method | Target |
|------|--------|--------|
| Contrast/Exposure | Luminance histogram percentiles | Median ~0.45, dynamic range ~0.85 |
| White Balance | Shades of Gray (Minkowski p=6) + White Patch blend | RGB gains near 1.0 |
| Skin Tone | HSV-based skin detection, I-line targeting | Hue ~20° (peach) |
| Saturation | Hasler-Susstrunk colorfulness metric | Colorfulness 35-55 |
| Black Level | Bottom 5% luminance analysis + noise floor | Black point < 0.02 |

```bash
# Full workflow
ffmpeg -y -ss 19 -i video.mp4 -vframes 1 -vf "scale=1280:-1" -update 1 frame_raw.png
ffmpeg -y -i frame_raw.png -vf "lut3d='conversion.cube':interp=tetrahedral" -update 1 frame_709.png
python3 auto_grade.py frame_709.png
```

## Match Grade Analysis

`match_grade.py` compares a reference image against an output image and suggests preset adjustments to bring the output closer to the reference.

```bash
python3 match_grade.py <reference.png> <output.png>
```

Useful for matching grades across clips or iterating toward a target look.

## Interactive Preview (preview.html)

Browser-based node chain previewer using Preact + HTM (~4KB). Applies .cube LUTs on canvas in real-time.

Features:
- **Drag-and-drop** any frame (raw S-Log3 or converted)
- **Node 1: Conversion LUT** — add your own .cube files (not included in repo)
- **Nodes 2-6: Correction chain** — dropdown presets + strength sliders
- **Creative presets** — one-click curated looks (Studio Dance, Studio Clean, Studio Ambient, Studio Gold, Studio Film)
- **S-Gamut3 → Cine compensation** toggle for gamut mismatch
- **Bypass/reset** all nodes instantly
- **URL parameters** — deep-link to a specific state: `?image=frame.png&lut=path/to.cube&preset=studio_gold`

Correction LUTs are committed in `correction_luts/`. Conversion LUTs are user-provided (gitignored in `luts/`).

## Config-Driven Presets

All LUT types are defined in `presets.yml`. Each preset is a pipeline of ordered processing steps. Adding a new LUT type means adding a YAML entry — no Ruby code changes needed.

Available step types: `exposure`, `highlight_protect`, `black_crush`, `hue_desat`, `skin_correction`, `shadow_sat_boost`, `skin_highlight`, `skin_rolloff`, `global_highlight_desat`, `rgb_rebalance`, `global_sat`.

## Available LUT Types

### Correction LUTs (apply after conversion)
| Type | What it fixes |
|------|--------------|
| `night_warm_fix` | All-in-one for underexposed warm/red scenes. ~1 stop lift + skin hue shift + black crush. |
| `night_purple_fix` | All-in-one for underexposed purple/magenta stage lighting. RGB rebalancing + lift + desat + skin fix. |
| `yellow_fix` | Warm amber/yellow cast from stage lighting. H=10-60, 55% desat. |
| `red_skin_fix` | Red/flushed skin from warm practicals. Hue shift to peach, skin-only targeting. |
| `pink_cast_fix` | Pink/magenta cast from stage lighting. Gentle RGB rebalance + magenta desat. |
| `overexposure_fix` | Scene-wide ~1 stop reduction with highlight rolloff. |
| `underexposure_fix` | Scene-wide ~1.2 stop lift with shadow recovery. |
| `black_crush` | Crushes milky/lifted blacks below 12% to true black. |
| `skin_highlight_fix` | Subtle skin-only highlight rolloff above 70% luminance. |
| `golden_warm` | Strong golden warm shift via RGB rebalance (R:1.20, G:1.00, B:0.80). For rich warm cinematic looks. |
| `cinema_dark` | Deep moody contrast with gamma 1.45, shadow lift 0.02, and knee compression (0.72-0.90). |

### Node Chain Building Blocks
| Type | Node | What it does |
|------|------|-------------|
| `studio_punch` | Contrast | Subtle contrast boost for well-lit interiors |
| `film_contrast` | Contrast | Stronger filmic contrast with deeper shadows |
| `flat_lift` | Contrast | Lifts shadows for softer, more open look |
| `warm_shift` | Temperature | Subtle warm shift via RGB rebalance |
| `cool_shift` | Temperature | Subtle cool shift via RGB rebalance |
| `led_green_fix` | Temperature | Fixes green tint from LED/fluorescent lights |
| `sat_boost` | Saturation | Global +15% saturation boost |
| `golden_warm` | Temperature | Strong golden warm shift (R:1.20, G:1.00, B:0.80) |
| `sat_reduce` | Saturation | Global -15% saturation reduction |
| `sgamut3_to_cine` | Gamut | S-Gamut3 → Cine compensation (desat ~12%) |
| `cinema_dark` | Contrast | Deep moody contrast (gamma 1.45, shadow lift, knee compression) |
| `black_lift` | Black Level | Lifts blacks for vintage/faded look |

### Creative Presets (node chain combinations)
| Preset | Look | Chain |
|--------|------|-------|
| Studio Clean | Natural bright | studio_punch(50%) + sat_boost(50%) |
| Studio Balanced | Warm natural | studio_punch(80%) + warm_shift(30%) + sat_boost(50%) + black_crush(15%) |
| Studio Dance | Warm cinematic | studio_punch(100%) + warm_shift(40%) + sat_boost(60%) + black_crush(25%) |
| Studio Ambient | No fill light | studio_punch(80%) + warm_shift(100%) + sat_boost(100%) + black_crush(20%) |
| Studio Gold | Warm cinematic | cinema_dark(80%) + golden_warm(75%) + sat_boost(100%) + black_crush(10%) |
| Studio Film | Moody cinematic | film_contrast(60%) + warm_shift(20%) + sat_reduce(30%) + black_crush(40%) |

### Baking Chain LUTs

`generate_chain_lut.rb` bakes multiple presets at different strengths into a single .cube file. This lets you apply a creative preset as one node in Resolve instead of multiple.

```bash
# Bake Studio Balanced into a single LUT
ruby generate_chain_lut.rb correction_luts/studio_balanced_baked.cube \
  studio_punch@0.8 warm_shift@0.3 sat_boost@0.5 black_crush@0.15

# Bake Studio Dance
ruby generate_chain_lut.rb correction_luts/studio_dance_baked.cube \
  studio_punch@1.0 warm_shift@0.4 sat_boost@0.6 black_crush@0.25
```

Pre-baked LUTs for all creative presets are committed in `correction_luts/`.

You can also bake a conversion LUT + creative chain into a single .cube for one-node grading in Resolve:

```bash
# Bake conversion + creative into a single pass LUT
ruby generate_chain_lut.rb final_grade.cube \
  --conversion=luts/SLog3_to_Rec709.cube \
  cinema_dark@0.8 golden_warm@1.0 sat_boost@1.0 black_crush@0.1
```

## Video Export Workflow

Apply conversion + correction LUTs and encode to H.265 in one pass using ffmpeg.

```bash
# Extract a sample frame for analysis
ffmpeg -y -ss 19 -i input.mp4 -vframes 1 -vf "scale=1280:-1" -update 1 frame_raw.png

# Apply conversion LUT to frame for preview
ffmpeg -y -i frame_raw.png -vf "lut3d='conversion.cube':interp=tetrahedral" -update 1 frame_709.png

# Full encode: conversion + correction → H.265 4K
# 50Mbps masters (for re-editing):
ffmpeg -i input.mp4 \
  -vf "lut3d='conversion.cube':interp=tetrahedral,lut3d='correction.cube':interp=tetrahedral,format=nv12" \
  -c:v hevc_videotoolbox -b:v 50M -spatial_aq 1 \
  -c:a aac -b:a 192k -tag:v hvc1 output_master.mp4

# 15Mbps web-optimized (for Instagram/web):
ffmpeg -i input.mp4 \
  -vf "lut3d='conversion.cube':interp=tetrahedral,lut3d='correction.cube':interp=tetrahedral,format=nv12" \
  -c:v hevc_videotoolbox -b:v 15M -spatial_aq 1 \
  -c:a aac -b:a 128k -tag:v hvc1 output_web.mp4
```

**Notes:**
- `hevc_videotoolbox` uses Apple Silicon hardware encoding (M1/M2/M3)
- `format=nv12` converts to YUV420p for compatibility
- `-tag:v hvc1` ensures QuickTime/browser playback compatibility
- `spatial_aq 1` enables adaptive quantization for better quality

## Conversion LUTs (not in repo)

Conversion LUTs (e.g. Sony S-Log3 → Rec.709, ARRI LogC → Rec.709) are camera-specific and often commercially licensed. Store them in `luts/` (gitignored).

**Phantom LUTs** (phantomluts.com) — ARRI Alexa709 emulation for Sony cameras:
- Location: `luts/a7s3-arri-g8/A7s3 Phntm Arri LUTs G8/65x/SLog3/Neutral A7s3_65x.cube`
- Variants: Neutral, IceBlue, Jamaica, Tungsten, Utopia (Standard + Legacy versions)
- Use 65x for post, 33x for in-camera/monitoring
- Designed for S-Log3 + S-Gamut3.Cine; enable Cine comp toggle for S-Gamut3 footage

**Resolve settings:** Colour Science = DaVinci YRGB, Timeline = Rec.709-A (Mac), 3D LUT interpolation = Tetrahedral

## Node Order (DaVinci Resolve)

Professional serial node chain:
1. Conversion LUT (camera log → Rec.709)
2. Contrast / Exposure
3. White Balance / Color Temperature
4. Skin Tone Correction
5. Color Saturation
6. Black Levels
7. (Noise Reduction — not achievable via LUT)
8. (Vignette — not achievable via LUT)
9. (Sharpening — not achievable via LUT)

## Applying LUTs

**DaVinci Resolve:** Add a serial node per LUT. Right-click node → LUT → browse to .cube file.

**Adobe Premiere Pro:** Lumetri Color → Creative → Look dropdown → browse to .cube file.

**ffmpeg (batch/preview):**
```bash
ffmpeg -i input.mp4 -vf "lut3d='conversion.cube':interp=tetrahedral,lut3d='correction.cube':interp=tetrahedral" output.mp4
```

## Tone Model (v2)

Tone operations — `exposure`, `black_crush`, `highlight_protect`, `skin_rolloff`,
`skin_highlight` — run in **linear light**, not on gamma-encoded HSL lightness.

The pipeline decodes with the BT.1886 display EOTF (pure 2.4 gamma), applies the
curve to Rec.709 luminance, and scales R, G and B by the resulting ratio. Because
all three channels are scaled together, hue and saturation are preserved by
construction. Where brightening pushes a colour outside the cube, it is
desaturated toward its target luminance rather than clipped per channel, which
would skew the hue.

Hue and saturation steps (`hue_desat`, `skin_correction`, `global_sat`,
`shadow_sat_boost`, `rgb_rebalance`) still work in HSL, where perceptual
behaviour is what you want.

**What changed from v1.** v1 applied tone curves to HSL lightness,
`L = (max + min) / 2`, which is not luminance — a saturated red and a grey that
look equally bright have very different `L`, so they were tonemapped by different
amounts and colours drifted relative to greys. Rewriting `L` and converting back
also quietly shifted hue and saturation.

Greys are bit-identical between v1 and v2. Only saturated colours move, by up to
~0.37 at the most saturated grid points. 14 of the 27 shipped LUTs changed; the
13 that are pure hue/saturation work are untouched.

To reproduce v1 output exactly:

```bash
ruby generate_lut.rb black_crush out.cube --legacy
ruby generate_chain_lut.rb out.cube studio_punch@0.8 sat_boost@0.5 --legacy
ruby regenerate_luts.rb --legacy
```

`reference_checksums_legacy.yml` pins the v1 output, and the test suite asserts
`--legacy` still reproduces it byte-for-byte.

## Color Science Notes

- **Desaturating warm tones in HSL produces brown/sepia.** Use hue shifting or RGB rebalancing instead.
- **Skin tones occupy H=10-35, S=0.08-0.45, L=0.25-0.75.** Use all three windows to isolate from light sources.
- **S-Gamut3 vs S-Gamut3.Cine:** S-Gamut3 is wider. LUTs calibrated for .Cine may oversaturate S-Gamut3 footage. Use `sgamut3_to_cine` compensation.
- **3D LUTs allow cross-channel operations** — R output can depend on G and B input.
- **LUTs have no spatial awareness** — no noise reduction, sharpening, or vignettes.

## Requirements

- Ruby 2.7+
- Python 3 with Pillow + NumPy (for auto_grade.py, match_grade.py, and analyze_frame.rb)
- ffmpeg / ffprobe (for frame extraction and metadata)

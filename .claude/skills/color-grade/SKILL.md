---
name: color-grade-resolve
description: Generates DaVinci Resolve color corrections using the node-based workflow. Builds a node tree following professional node order, exports as DRX grade stills or applies via Resolve scripting API. Use when users want color grading in DaVinci Resolve rather than Premiere Pro.
---

# Skill: Color Grade (DaVinci Resolve)

Generate DaVinci Resolve node-based color corrections. Resolve uses a node graph instead of stacked effects - each node is an independent corrector with its own primaries, curves, qualifier (HSL Secondary), power windows, and LUT.

## Node Order

Follow this professional node order for serial node chains. Each node serves one purpose:

1. **White Balance** — Correct color temperature and tint first, before any other processing
2. **Exposure** — Set overall exposure/gain to get correct brightness levels
3. **Main Conversion LUT** — Apply camera-to-display transform (e.g., ARRI LogC to Rec.709)
4. **General Color Adjustments** — Lift/Gamma/Gain wheels, contrast, color balance
5. **Color Saturation/Boost** — Global and selective saturation adjustments
6. **Noise Reduction** — Temporal and spatial NR (do this before sharpening)
7. **Black Levels** — Crush or lift blacks, set floor
8. **Vignette** — Power window with soft edge for light falloff
9. **Sharpening** — Always last - sharpens the final result

Not every grade needs all 9 nodes. Skip nodes that aren't needed. For qualifier-based (HSL Secondary) corrections like skin fixes, insert additional nodes between steps 5 and 6 with the qualifier keyed to the target zone.

## Resolve API Capabilities

The scripting API (Python/Lua, requires Resolve running) supports:

- `SetCDL({NodeIndex, Slope, Offset, Power, Saturation})` — ASC CDL values per node
- `SetLUT(nodeIndex, lutPath)` — Apply .cube LUT to a specific node
- `ApplyGradeFromDRX(path, gradeMode)` — Apply a saved grade still (DRX) to clips
- `ExportLUT(exportType, path)` — Bake grade to .cube file
- `GrabStill()` / `ExportStills()` — Save grades as DRX stills

**Not available via API:** Creating/adding nodes, setting color wheels directly, setting qualifiers/HSL keys, setting curves. These require either DRX files or manual work in the Color page.

## Workflow

### Option A: DRX Grade Stills (Full Node Graph)

If a DRX file is available (exported from Resolve with a reference grade):

1. User creates reference grade manually in Resolve's Color page
2. Export as DRX: Gallery → right-click still → Export → .drx
3. Apply to all clips via script:

```python
# apply_grade.py — run with Resolve open
import DaVinciResolveScript as dvr
resolve = dvr.scriptapp("Resolve")
project = resolve.GetProjectManager().GetCurrentProject()
timeline = project.GetCurrentTimeline()
clips = timeline.GetItemListInTrack("video", 1)
timeline.ApplyGradeFromDRX("/path/to/grade.drx", 0, clips)
```

### Option B: CDL + LUT (Basic Corrections)

For grades that can be expressed as CDL values + a LUT:

1. Analyze frames with `analyze_frame.rb` (same as Premiere workflow)
2. Calculate CDL slope/offset/power from desired corrections
3. Generate a Python script that applies CDL + LUT per node:

```python
import DaVinciResolveScript as dvr
resolve = dvr.scriptapp("Resolve")
project = resolve.GetProjectManager().GetCurrentProject()
timeline = project.GetCurrentTimeline()
clips = timeline.GetItemListInTrack("video", 1)
for clip in clips:
    # Node 1: White Balance (via CDL offset)
    clip.SetCDL({"NodeIndex": "1", "Slope": "1.0 1.0 1.0", "Offset": "0.0 0.0 0.0", "Power": "1.0 1.0 1.0", "Saturation": "1.0"})
    # Node 3: Main LUT
    graph = clip.GetNodeGraph()
    graph.SetLUT(3, "AMIRA_Default_LogC2Rec709.cube")
```

### Option C: Frame Analysis + Manual Guide

When API isn't sufficient (need qualifiers/HSL Secondary):

1. Analyze frames with `analyze_frame.rb` to get HSV stats per zone
2. Generate a detailed correction guide with specific values for the colorist:
   - Per-node settings following the node order above
   - Qualifier key ranges (hue center/range, sat center/range, lum center/range)
   - Correction values for each keyed zone
3. User applies manually in Resolve's Color page using the guide

### Option D: Custom .cube LUT Generation (No Studio Required)

Generate targeted correction LUTs programmatically using `generate_lut.rb`. Presets are config-driven via `presets.yml` — add new LUT types by editing YAML, no Ruby changes needed. These work in both Resolve and Premiere with no API or Studio dependency.

```bash
# Remove warm amber/yellow cast from stage lighting
ruby generate_lut.rb yellow_fix /path/to/output.cube

# Roll off overexposed skin highlights (only affects lum > 70%)
ruby generate_lut.rb skin_highlight_fix /path/to/output.cube

# Adjust strength (0.0-1.0)
ruby generate_lut.rb yellow_fix /path/to/output.cube --strength=0.5
```

To create a custom preset, add an entry to `presets.yml` with a pipeline of steps (exposure, black_crush, skin_correction, hue_desat, etc.) and run `ruby generate_lut.rb my_preset output.cube`.

Available LUT types:
- **yellow_fix** — Targets H=10°-60° (warm amber/yellow), reduces saturation 55%, shifts hue toward neutral. For stage lighting spill.
- **red_skin_fix** — Fixes sunburnt/flushed red skin from warm practical lights. Shifts red skin hues toward peach. Only targets skin luminance+saturation range — leaves light sources, deck, and saturated objects alone.
- **night_warm_fix** — All-in-one for underexposed warm/red practical scenes. ~1 stop lift + skin hue shift + black crush. No desaturation.
- **night_purple_fix** — All-in-one for underexposed purple/magenta stage lighting. RGB channel rebalancing (boost G, reduce B) + ~2 stop lift + purple desaturation + skin hue shift from purple toward natural + black crush. Preserves atmospheric purple from stage lights while making skin look natural. Developed for SSMC 2025 salsa performances.
- **overexposure_fix** — Scene-wide ~1 stop reduction with highlight rolloff from 55%. For blown-out footage.
- **underexposure_fix** — Scene-wide ~1.2 stop lift with shadow recovery and highlight protection. For dark footage.
- **black_crush** — Crushes milky/lifted blacks below 12% luminance to true black.
- **skin_highlight_fix** — Subtle skin-only rolloff above 70% luminance. For minor skin overexposure.

All LUTs support `--strength=N` (0.0-1.0) for intensity control.

Apply in Resolve: add node after conversion LUT → right-click → LUT → browse to .cube file.
Apply in Premiere: Lumetri Color → Creative → Look dropdown → browse.

## Scripting Setup (Windows)

```
RESOLVE_SCRIPT_API=C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting
RESOLVE_SCRIPT_LIB=E:\Davinci Resolve\fusionscript.dll
PYTHONPATH=%PYTHONPATH%;%RESOLVE_SCRIPT_API%\Modules\
```

Resolve must be running for scripts to connect.

## Key Reference

CDL parameters map to Resolve's primary corrections:
- **Slope** — Multiplier (like Gain). `"1.0 1.0 1.0"` = neutral. `"1.2 1.0 0.9"` = warmer
- **Offset** — Added value (like Lift). `"0.0 0.0 0.0"` = neutral
- **Power** — Gamma curve. `"1.0 1.0 1.0"` = neutral. Higher = brighter midtones
- **Saturation** — Global sat. `"1.0"` = neutral. `"0.0"` = monochrome

## Color Science Fundamentals

Key concepts for understanding what the LUT generator does and how to create new correction types:

### Color Spaces
- **Rec.709** — Standard HD display color space. Small gamut, fixed gamma. What the audience sees.
- **Log curves** (ARRI LogC, Sony S-Log3) — Logarithmic encodings that compress maximum dynamic range into a video signal. Look flat by design. Each camera manufacturer has their own curve.
- **ACES** — Academy Color Encoding System. Scene-referred, open framework. Pipeline: Input Transform → ACES → RRT → ODT → Display. Future-proof, encompasses full human vision.

### How LUTs Work
- **1D LUT** — Per-channel curve (like Photoshop Curves). Can do brightness, gamma, contrast. No cross-channel interaction.
- **3D LUT** — 3D lattice indexed by R, G, B simultaneously. Allows cross-channel operations (changing R output based on G and B input). A 33³ LUT has 35,937 sample points with trilinear/tetrahedral interpolation between them.
- **The .cube format** is plain text: header + RGB triplets. Simple to generate programmatically.

### HSL vs RGB for Corrections
- **Desaturating warm tones in HSL produces brown/sepia** — this is a mathematical property. Orange desaturated = muddy brown.
- **RGB channel rebalancing** (reduce R, boost B) cools warm tones toward neutral white — better for temperature correction.
- **Hue shifting** (rotate in HSL) moves colors without losing vibrancy — best for "sunburnt skin → peach" type fixes.
- Use **luminance + saturation windows** to isolate skin from light sources and saturated objects at similar hues.

### Frame Analysis Workflow for New LUT Development

When fixing a specific clip, follow this workflow to diagnose and build a correction LUT:

1. **Extract a frame** at the target timecode using ffmpeg:
   ```bash
   # Get starting timecode and frame rate from the clip
   ffprobe -v error -show_entries stream_tags=timecode -show_entries stream=r_frame_rate -of default video.mp4
   # Calculate offset: (target_tc - start_tc) in seconds
   # Extract frame at that offset
   ffmpeg -y -ss <offset_seconds> -i video.mp4 -vframes 1 -vf "scale=1280:-1" tmp/frames/raw_frame.png
   ```

2. **Apply the conversion LUT** (e.g., AMIRA LogC→Rec709) to get the Rec.709 starting point:
   ```bash
   ffmpeg -y -i raw_frame.png -vf "lut3d='/path/to/AMIRA_Default_LogC2Rec709.cube'" amira_applied.png
   ```
   AMIRA LUT location (Premiere Pro): `C:\Program Files\Adobe\Adobe Premiere Pro 2025\Lumetri\LUTs\Technical\AMIRA_Default_LogC2Rec709.cube`

3. **Analyze color regions** using Python or `analyze_frame.rb` to get HSV stats for skin, neutrals, and problem areas. Sample 5-8 regions: skin (multiple faces), ceiling/walls (should be neutral), floor, clothing (white reference), light sources.

4. **Identify the correction needed** based on the analysis:
   - Warm/amber cast → `yellow_fix`
   - Red/flushed skin → `red_skin_fix`
   - Underexposed + warm → `night_warm_fix`
   - Purple/magenta cast → `night_purple_fix`
   - If no existing type fits, create a new one following the same pattern

5. **Generate and test** the correction LUT, applying it after the conversion LUT:
   ```bash
   ruby generate_lut.rb <type> /path/to/output.cube
   ffmpeg -y -i raw_frame.png -vf "lut3d='conversion.cube',lut3d='correction.cube'" result.png
   ```

6. **Iterate** by comparing before/after color stats until skin tones are in the H=10-35° range and neutral areas are desaturated.

### Key Lesson: Purple vs Warm Cast Correction

Purple/magenta stage lighting (H=270-330°) requires a fundamentally different approach than warm/red casts:
- **Warm cast**: R channel elevated → fix with HSL desaturation/hue shift in orange range
- **Purple cast**: R+B elevated, G suppressed → must fix with RGB channel rebalancing FIRST (boost G, reduce B), then HSL corrections

The RGB rebalancing must be **luminance-adaptive** — scale the gain adjustments by pixel brightness. Very dark pixels (lum < 12%) get minimal rebalancing to avoid wild hue swings. Without this, dark shadows shift from purple to green.

### Targeting Skin Specifically in a LUT
Skin tones occupy a narrow band: H=10-35°, S=0.10-0.45, L=0.25-0.75. Light sources, colored objects, and surfaces may overlap in hue but differ in saturation and luminance:
- Light sources: very high luminance (>0.85) or very high saturation (>0.6)
- Dark surfaces (deck/floor): low luminance (<0.20)
- Skin: moderate saturation, mid luminance

### Learning Resources
- **Color Correction Handbook** by Alexis Van Hurkman — the industry-standard textbook
- **Blackmagic Official Training** — free at blackmagicdesign.com/products/davinciresolve/training
- **Cullen Kelly** (YouTube) — technically rigorous free color grading education, Netflix/HBO colorist
- **MixingLight.com** — 1,200+ structured tutorials from working colorists (paid subscription)
- **Frame.io ACES Guide** — blog.frame.io/2019/09/09/guide-to-aces/ — best ACES primer
- **Dado Valentic / Colour Training** — colour.training — bridges color science research and practical grading
- **Kodak Color Theory Workbook** — free PDF from Kodak covering fundamental color theory for motion pictures

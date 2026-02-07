---
title: Adobe Premiere Pro
description: How to use color-grade-ai LUTs in Premiere Pro
---

## Applying a LUT

1. Create an **Adjustment Layer** (Project panel → New Item → Adjustment Layer)
2. Drag it to a video track **above** your clip
3. Select the adjustment layer and open **Lumetri Color**
4. Go to the **Creative** tab
5. Click the **Look** dropdown → Browse → select your .cube file

Alternatively, use **Basic Correction** → **Input LUT** if you want the LUT applied before other Lumetri controls.

## Stacking LUTs

Use separate adjustment layers for each LUT, stacked on the timeline:

```
V4: Adjustment Layer — Black_Crush.cube
V3: Adjustment Layer — Overexposure_Fix.cube
V2: Adjustment Layer — Yellow_Cast_Fix.cube
V1: Your clip with camera conversion LUT (Input LUT in Basic Correction)
```

Premiere processes from bottom to top, so the camera conversion LUT on V1 is applied first, then each fix layer in order.

## Per-Section Corrections

If only part of your video needs correction (e.g. overexposed at the start, fine later), trim the adjustment layers to cover only the sections that need them:

- Razor tool (C) to cut the adjustment layer at the transition point
- Delete the portion that doesn't need correction
- Different sections can have different LUT stacks

## Stacking Presets

### Overexposed stage footage
```
V4: Black_Crush_Sub12pct_Shadow_Floor.cube
V3: Overexposure_Fix_Minus_1stop_Highlight_Rolloff.cube
V2: Yellow_Cast_Fix_H10-60_55pct_Desat.cube
V1: Clip + AMIRA_Default_LogC2Rec709.cube (Input LUT)
```

### Underexposed performance
```
V3: Underexposure_Fix_Plus_1.2stop_Shadow_Lift.cube
V2: Yellow_Cast_Fix_H10-60_55pct_Desat.cube
V1: Clip + camera conversion LUT
```

### Skin correction (outdoor night shoot)
```
V2: Red_Skin_Fix_Skin_Only_Hue_to_Peach.cube
V1: Clip + camera conversion LUT
```

### Night scene with warm practicals
```
V2: Night_Warm_Fix.cube (single LUT handles everything)
V1: Clip + AMIRA_Default_LogC2Rec709.cube (Input LUT)
```

The `night_warm_fix` preset combines underexposure lift, skin hue correction, and black crush into a single LUT. No stacking needed.

### Night scene with purple stage lighting
```
V2: Night_Purple_Fix.cube (single LUT handles everything)
V1: Clip + AMIRA_Default_LogC2Rec709.cube (Input LUT)
```

The `night_purple_fix` preset handles RGB rebalancing, exposure lift, purple desaturation, skin hue correction, and black crush in one pass.

## Noise Reduction

Premiere Pro has no built-in temporal/spatial noise reduction. Options:

- **Neat Video** (~$75-150) — industry standard NR plugin
- **Lumetri Blacks slider** — crush the noisiest shadows (blunt but free)
- **Do NR in Resolve** — Resolve's built-in NR is free and excellent. Grade in Resolve, export, bring back to Premiere timeline.

## Tips

- The Lumetri Sharpen control (in Creative tab) can help with mild softness but won't fix real blur.
- Use **Comparison View** (shot/frame icon in Program Monitor) to A/B your correction against the original.
- Copy/paste Lumetri effects between adjustment layers to reuse LUT assignments.

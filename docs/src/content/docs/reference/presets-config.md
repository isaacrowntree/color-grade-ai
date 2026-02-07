---
title: Preset Configuration
description: How to create and customize LUT presets
---

LUT presets are defined in `presets.yml` at the project root. Each preset is a named pipeline of ordered processing steps. Adding a new LUT type means adding a YAML entry — no Ruby code changes needed.

## YAML Format

```yaml
my_custom_lut:
  title: "My Custom LUT"
  comments:
    - "Description line 1"
    - "Description line 2"
  pipeline:
    - step: exposure
      gamma: 0.80
      shadow_lift: 0.02
    - step: black_crush
      black_threshold: 0.10
      crush_gamma: 2.0
      transition_end: 0.22
```

### Required Fields

| Field | Description |
|-------|-------------|
| `title` | Human-readable name (written to .cube file header) |
| `comments` | Array of description lines (written as .cube comments) |
| `pipeline` | Ordered array of processing steps |

Each step must have a `step` field naming the step type, plus the required parameters for that type.

## Strength Interpolation

All presets support `--strength=N` (0.0-1.0). Parameters in the YAML represent the value at full strength (1.0). The code interpolates from neutral toward the target:

- Gamma: `actual = 1.0 + (target - 1.0) * strength`
- Multiplicative gains: `actual = 1.0 + (target - 1.0) * strength`
- Additive values: `actual = target * strength`

At `--strength=0`, all presets produce an identity LUT (no change).

## Available Step Types

### rgb_rebalance

Per-channel RGB gain adjustment, scaled by luminance to avoid wild hue swings in dark pixels.

| Parameter | Description |
|-----------|-------------|
| `r_gain` | Red channel multiplier (1.0 = neutral) |
| `g_gain` | Green channel multiplier |
| `b_gain` | Blue channel multiplier |
| `gain_ramp` | Luminance threshold for full gain (below this, gains are reduced) |

### exposure

Global exposure adjustment via gamma curve with optional shadow floor lift.

| Parameter | Description |
|-----------|-------------|
| `gamma` | Gamma value at full strength (>1.0 darkens, <1.0 brightens) |
| `shadow_lift` | Shadow floor lift amount (0.0-0.05 typical) |

### highlight_protect

Soft knee highlight compression to prevent clipping.

| Parameter | Description |
|-----------|-------------|
| `knee_start` | Luminance where compression begins (0.0-1.0) |
| `knee_ceiling` | Maximum output luminance |

### black_crush

Steepens shadow ramp to push milky blacks toward true black.

| Parameter | Description |
|-----------|-------------|
| `black_threshold` | Luminance below which full crush applies |
| `crush_gamma` | Gamma at full strength (higher = steeper crush) |
| `transition_end` | Luminance where crush blends back to identity |

### hue_desat

Hue-targeted desaturation with optional hue shift. Good for neutralizing color casts.

| Parameter | Description |
|-----------|-------------|
| `hue_center` | Center hue angle (0-360) |
| `hue_width` | Half-width of hue window in degrees |
| `softness` | Feathering of hue window edges |
| `sat_reduce` | Target saturation ratio (0.45 = reduce to 45%) |
| `hue_shift` | Hue rotation in degrees (optional, default 0) |
| `min_sat` | Minimum saturation to trigger (optional) |
| `sat_scaling_ref` | Saturation reference for scaling effect (optional) |

### skin_correction

Targeted hue shift using 3-way window (hue + luminance + saturation) to isolate skin tones.

| Parameter | Description |
|-----------|-------------|
| `hue_center` | Center of skin hue range |
| `hue_width` | Half-width of hue window |
| `hue_soft` | Hue window feathering |
| `hue_shift` | Degrees to shift hue toward natural skin |
| `lum_low` | Lower luminance bound |
| `lum_high` | Upper luminance bound |
| `lum_soft` | Luminance window feathering |
| `sat_low` | Lower saturation bound |
| `sat_high` | Upper saturation bound |
| `sat_soft` | Saturation window feathering |
| `adaptive_desat` | Enable adaptive desaturation (true/false) |

### shadow_sat_boost

Saturation boost in shadows to counteract washed-out lifted darks.

| Parameter | Description |
|-----------|-------------|
| `boost` | Saturation boost amount (0.10 = +10%) |
| `range_low` | Lower luminance bound |
| `range_high` | Upper luminance bound |

### skin_highlight

Skin-targeted highlight rolloff with desaturation, plus gentle global highlight protection.

| Parameter | Description |
|-----------|-------------|
| `skin_hue_center` | Center of skin hue range |
| `skin_hue_width` | Half-width |
| `skin_softness` | Feathering |
| `knee_start` | Skin highlight knee |
| `knee_ceiling` | Skin max luminance |
| `global_knee` | Global highlight knee |
| `global_ceiling` | Global max luminance |
| `hot_desat` | Desaturation ratio for blown skin |
| `min_sat_ratio` | Minimum saturation for skin detection |

### skin_rolloff

Skin-targeted luminance rolloff blended by skin strength. Used for overexposure correction.

| Parameter | Description |
|-----------|-------------|
| `skin_hue_center` | Center of skin hue range |
| `skin_hue_width` | Half-width |
| `skin_softness` | Feathering |
| `knee_start` | Rolloff start luminance |
| `knee_ceiling` | Max luminance for skin |
| `min_sat` | Minimum saturation gate |

### global_highlight_desat

Desaturate blown highlights across the entire image.

| Parameter | Description |
|-----------|-------------|
| `threshold` | Luminance above which desat begins |
| `desat_amount` | Maximum desat ratio |

## Adding a Custom Preset

1. Open `presets.yml`
2. Add a new entry with `title`, `comments`, and `pipeline`
3. Choose steps from the types above and set parameters
4. Generate: `ruby generate_lut.rb my_preset output.cube`
5. Update docs: `ruby generate_docs.rb`

## Tips

- Steps execute in order. Put RGB rebalancing first, exposure next, then refinements.
- Use `skin_correction` for targeted hue shifts — it won't touch non-skin tones.
- The `orig_l` (original luminance) is used by `skin_correction` and `shadow_sat_boost` for their window calculations, even after exposure changes. This prevents false targeting.
- Test with `--strength=0.5` first, then adjust parameters.

---
title: LUT Types
description: Reference for all available LUT presets
---

All LUTs are generated with `generate_lut.rb` and support these options:

- `--strength=N` — Effect intensity from 0.0 (no change) to 1.0 (full). Default: 1.0
- `--size=N` — LUT grid resolution. Default: 33 (33x33x33 = 35,937 sample points)

Presets are defined in [`presets.yml`](/color-grade-ai/reference/presets-config/). Add new LUT types by editing the YAML.

## yellow_fix

**Yellow Cast Fix - Stage Lighting**

> Yellow/Amber Cast Fix LUT
> Targets warm stage lighting cast (H=10-60 degrees)
> Apply AFTER LogC to Rec.709 conversion
> Compatible with DaVinci Resolve and Adobe Premiere Pro

```bash
ruby generate_lut.rb yellow_fix output.cube
```

### Pipeline

1. **hue_desat** — Hue-targeted desaturation with optional hue shift. Good for neutralizing color casts.

   | Parameter | Value |
   |-----------|-------|
   | hue_center | 35.0 |
   | hue_width | 25.0 |
   | softness | 10.0 |
   | sat_reduce | 0.45 |
   | hue_shift | -5.0 |
   | min_sat | 0.02 |
   | sat_scaling_ref | 0.5 |


## warm_skin_cast_fix

**Warm Skin Cast Fix - Red/Orange Practical Light**

> Fixes red/orange cast on skin from warm practical lights
> Targets H=355-45 degrees (red through orange), 75% desaturation
> Only affects warm saturated tones - cool tones untouched
> Apply AFTER LogC to Rec.709 conversion
> Compatible with DaVinci Resolve and Adobe Premiere Pro

```bash
ruby generate_lut.rb warm_skin_cast_fix output.cube
```

### Pipeline

1. **skin_correction** — Targeted hue shift using 3-way window (hue + luminance + saturation) to isolate skin tones.

   | Parameter | Value |
   |-----------|-------|
   | hue_center | 10.0 |
   | hue_width | 22.0 |
   | hue_soft | 8.0 |
   | hue_shift | 8.0 |
   | lum_low | 0.1 |
   | lum_high | 0.78 |
   | lum_soft | 0.1 |
   | sat_low | 0.06 |
   | sat_high | 0.8 |
   | sat_soft | 0.12 |
   | adaptive_desat | true |
   | desat_baseline | 0.85 |
   | desat_range | 0.2 |
   | desat_sat_ref | 0.3 |
   | desat_sat_range | 0.7 |


## skin_highlight_fix

**Skin Highlight Fix - Overexposure Recovery**

> Skin Highlight Rolloff LUT
> Compresses overexposed skin tones with soft knee
> Apply AFTER LogC to Rec.709 conversion
> Compatible with DaVinci Resolve and Adobe Premiere Pro

```bash
ruby generate_lut.rb skin_highlight_fix output.cube
```

### Pipeline

1. **skin_highlight** — Skin-targeted highlight rolloff with desaturation, plus gentle global highlight protection.

   | Parameter | Value |
   |-----------|-------|
   | skin_hue_center | 25.0 |
   | skin_hue_width | 25.0 |
   | skin_softness | 12.0 |
   | knee_start | 0.7 |
   | knee_ceiling | 0.92 |
   | global_knee | 0.85 |
   | global_ceiling | 0.97 |
   | hot_desat | 0.7 |
   | min_sat_ratio | 0.15 |


## overexposure_fix

**Scene Overexposure Fix**

> Scene-wide overexposure correction (~1 stop reduction)
> Global gamma + highlight rolloff + skin protection
> Apply AFTER LogC to Rec.709 conversion
> Compatible with DaVinci Resolve and Adobe Premiere Pro

```bash
ruby generate_lut.rb overexposure_fix output.cube
```

### Pipeline

1. **exposure** — Global exposure adjustment via gamma curve with optional shadow floor lift.

   | Parameter | Value |
   |-----------|-------|
   | gamma | 1.35 |
   | shadow_lift | 0.0 |

2. **highlight_protect** — Soft knee highlight compression to prevent clipping.

   | Parameter | Value |
   |-----------|-------|
   | knee_start | 0.55 |
   | knee_ceiling | 0.85 |

3. **skin_rolloff** — Skin-targeted luminance rolloff blended by skin strength. Used for overexposure correction.

   | Parameter | Value |
   |-----------|-------|
   | skin_hue_center | 25.0 |
   | skin_hue_width | 25.0 |
   | skin_softness | 12.0 |
   | knee_start | 0.5 |
   | knee_ceiling | 0.78 |
   | min_sat | 0.03 |

4. **global_highlight_desat** — Desaturate blown highlights across the entire image.

   | Parameter | Value |
   |-----------|-------|
   | threshold | 0.65 |
   | desat_amount | 0.25 |


## underexposure_fix

**Scene Underexposure Fix**

> Scene-wide underexposure lift (~1.2 stops)
> Global gamma lift + shadow recovery + highlight protection
> Apply AFTER LogC to Rec.709 conversion
> Compatible with DaVinci Resolve and Adobe Premiere Pro

```bash
ruby generate_lut.rb underexposure_fix output.cube
```

### Pipeline

1. **exposure** — Global exposure adjustment via gamma curve with optional shadow floor lift.

   | Parameter | Value |
   |-----------|-------|
   | gamma | 0.7 |
   | shadow_lift | 0.03 |

2. **highlight_protect** — Soft knee highlight compression to prevent clipping.

   | Parameter | Value |
   |-----------|-------|
   | knee_start | 0.8 |
   | knee_ceiling | 0.95 |

3. **shadow_sat_boost** — Saturation boost in shadows to counteract washed-out lifted darks.

   | Parameter | Value |
   |-----------|-------|
   | boost | 0.1 |
   | range_low | 0.05 |
   | range_high | 0.5 |


## black_crush

**Black Crush - Shadow Floor**

> Crushes milky/lifted blacks to true black
> Only affects shadows below 25% luminance
> Apply AFTER LogC to Rec.709 conversion
> Compatible with DaVinci Resolve and Adobe Premiere Pro

```bash
ruby generate_lut.rb black_crush output.cube
```

### Pipeline

1. **black_crush** — Steepens shadow ramp to push milky blacks toward true black.

   | Parameter | Value |
   |-----------|-------|
   | black_threshold | 0.12 |
   | crush_gamma | 2.5 |
   | transition_end | 0.25 |


## night_warm_fix

**Night Warm Fix - Underexposed + Red Practicals**

> All-in-one fix for underexposed scenes with warm/red practical lights
> Combines: ~1 stop lift + skin hue shift + black crush
> No desaturation — preserves vivid reds from practicals
> Use with AMIRA LUT only — replaces the multi-LUT chain
> Apply AFTER LogC to Rec.709 conversion
> Compatible with DaVinci Resolve and Adobe Premiere Pro

```bash
ruby generate_lut.rb night_warm_fix output.cube
```

### Pipeline

1. **exposure** — Global exposure adjustment via gamma curve with optional shadow floor lift.

   | Parameter | Value |
   |-----------|-------|
   | gamma | 0.72 |
   | shadow_lift | 0.02 |

2. **highlight_protect** — Soft knee highlight compression to prevent clipping.

   | Parameter | Value |
   |-----------|-------|
   | knee_start | 0.82 |
   | knee_ceiling | 0.95 |

3. **black_crush** — Steepens shadow ramp to push milky blacks toward true black.

   | Parameter | Value |
   |-----------|-------|
   | black_threshold | 0.1 |
   | crush_gamma | 2.2 |
   | transition_end | 0.22 |

4. **skin_correction** — Targeted hue shift using 3-way window (hue + luminance + saturation) to isolate skin tones.

   | Parameter | Value |
   |-----------|-------|
   | hue_center | 10.0 |
   | hue_width | 22.0 |
   | hue_soft | 8.0 |
   | hue_shift | 8.0 |
   | lum_low | 0.08 |
   | lum_high | 0.78 |
   | lum_soft | 0.08 |
   | sat_low | 0.06 |
   | sat_high | 0.8 |
   | sat_soft | 0.1 |
   | adaptive_desat | false |


## night_purple_fix

**Night Purple Fix - Underexposed + Purple/Magenta Stage Lighting**

> All-in-one fix for underexposed scenes with purple/magenta stage lighting
> Combines: RGB rebalancing + ~2 stop lift + purple desat + skin hue shift + black crush
> Counters purple cast (R+B elevated, G suppressed) via channel gains
> Shifts purple-contaminated skin hues toward natural tones
> Apply AFTER LogC to Rec.709 conversion (e.g. AMIRA_Default_LogC2Rec709)
> Compatible with DaVinci Resolve and Adobe Premiere Pro

```bash
ruby generate_lut.rb night_purple_fix output.cube
```

### Pipeline

1. **rgb_rebalance** — Per-channel RGB gain adjustment, scaled by luminance to avoid wild hue swings in dark pixels.

   | Parameter | Value |
   |-----------|-------|
   | r_gain | 0.97 |
   | g_gain | 1.08 |
   | b_gain | 0.9 |
   | gain_ramp | 0.15 |

2. **exposure** — Global exposure adjustment via gamma curve with optional shadow floor lift.

   | Parameter | Value |
   |-----------|-------|
   | gamma | 0.82 |
   | shadow_lift | 0.008 |

3. **highlight_protect** — Soft knee highlight compression to prevent clipping.

   | Parameter | Value |
   |-----------|-------|
   | knee_start | 0.85 |
   | knee_ceiling | 0.96 |

4. **black_crush** — Steepens shadow ramp to push milky blacks toward true black.

   | Parameter | Value |
   |-----------|-------|
   | black_threshold | 0.1 |
   | crush_gamma | 2.8 |
   | transition_end | 0.25 |

5. **hue_desat** — Hue-targeted desaturation with optional hue shift. Good for neutralizing color casts.

   | Parameter | Value |
   |-----------|-------|
   | hue_center | 300.0 |
   | hue_width | 50.0 |
   | softness | 15.0 |
   | sat_reduce | 0.45 |
   | hue_shift | 0.0 |
   | min_sat | 0.05 |

6. **skin_correction** — Targeted hue shift using 3-way window (hue + luminance + saturation) to isolate skin tones.

   | Parameter | Value |
   |-----------|-------|
   | hue_center | 325.0 |
   | hue_width | 35.0 |
   | hue_soft | 12.0 |
   | hue_shift | 40.0 |
   | lum_low | 0.02 |
   | lum_high | 0.75 |
   | lum_soft | 0.04 |
   | sat_low | 0.05 |
   | sat_high | 0.75 |
   | sat_soft | 0.1 |
   | adaptive_desat | false |


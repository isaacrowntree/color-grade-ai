---
title: LUT Types
description: Reference for all available LUT presets
---

All LUTs are generated with `generate_lut.rb` and support these options:

- `--strength=N` — Effect intensity from 0.0 (no change) to 1.0 (full). Default: 1.0
- `--size=N` — LUT grid resolution. Default: 33 (33x33x33 = 35,937 sample points)

## yellow_fix

**Problem:** Yellow or amber color cast from stage lights, practicals, or mixed lighting.

```bash
ruby generate_lut.rb yellow_fix output.cube
```

| Parameter | Value |
|-----------|-------|
| Hue target | 10°-60° (warm amber through yellow) |
| Desaturation | 55% |
| Hue shift | -5° (away from yellow) |
| Affects | All luminance levels |

The saturation reduction scales with input saturation — already-neutral areas are unaffected, highly saturated warm tones get the full correction.

## warm_skin_cast_fix

**Problem:** Skin looks sunburnt, flushed, or overly red from warm practical lights (tungsten, etc).

```bash
ruby generate_lut.rb warm_skin_cast_fix output.cube
```

| Parameter | Value |
|-----------|-------|
| Hue target | 354°-30° (red through orange) |
| Hue shift | +15° toward peach |
| Desaturation | 15% (gentle) |
| Luminance window | 22%-78% (skin brightness only) |
| Saturation window | 0.06-0.48 (skin range only) |

This is the most surgical LUT. It uses a three-way targeting window (hue + saturation + luminance) to isolate only skin tones. Light sources (high sat/high lum), dark surfaces (low lum), and saturated objects (high sat) are excluded.

## overexposure_fix

**Problem:** Scene is blown out, highlights clipped, washed-out appearance.

```bash
ruby generate_lut.rb overexposure_fix output.cube
```

| Parameter | Value |
|-----------|-------|
| Exposure reduction | ~1 stop (gamma 1.35) |
| Highlight knee | Starts at 55% luminance |
| Highlight ceiling | 85% |
| Skin ceiling | 78% (extra protection) |
| Highlight desaturation | 25% above 65% lum |

Affects the entire scene. The gamma curve brings everything down, the highlight rolloff prevents clipping, and skin tones get extra compression.

## underexposure_fix

**Problem:** Scene is too dark, shadow detail is lost.

```bash
ruby generate_lut.rb underexposure_fix output.cube
```

| Parameter | Value |
|-----------|-------|
| Exposure lift | ~1.2 stops (gamma 0.70) |
| Shadow floor lift | +3% |
| Highlight protection | Knee at 80%, cap at 95% |
| Shadow saturation boost | +10% in shadows |

Lifts the entire scene while protecting highlights from blowing out. Includes a slight saturation boost in shadows to counteract the washed-out look of lifted dark areas.

## black_crush

**Problem:** Milky or lifted blacks, grey where it should be black.

```bash
ruby generate_lut.rb black_crush output.cube
```

| Parameter | Value |
|-----------|-------|
| Crush threshold | Below 12% luminance |
| Crush gamma | 2.5 (steep darkening) |
| Transition end | 25% (smooth blend to identity) |
| Midtone/highlight effect | None |

Only affects the bottom of the tonal range. Everything above 25% luminance passes through unchanged.

## skin_highlight_fix

**Problem:** Skin highlights are slightly blown but the rest of the scene is fine.

```bash
ruby generate_lut.rb skin_highlight_fix output.cube
```

| Parameter | Value |
|-----------|-------|
| Skin hue target | 0°-50° (peach through warm) |
| Skin knee | 70% luminance |
| Skin ceiling | 92% |
| Global knee | 85% |
| Global ceiling | 97% |
| Highlight desaturation | 30% on blown skin |

A subtle correction for minor overexposure on skin only. For severe overexposure, use `overexposure_fix` instead.

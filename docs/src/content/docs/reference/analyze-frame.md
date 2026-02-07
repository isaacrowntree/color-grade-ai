---
title: Frame Analysis
description: Analyze video frames to identify color problems
---

## Usage

```bash
ruby analyze_frame.rb <image_path> <x1,y1,x2,y2> [label]
```

Extracts color statistics from a rectangular region of an image. Use it to measure the actual HSV/RGB values of problem areas before choosing which LUT to generate.

## Parameters

| Parameter | Description |
|-----------|-------------|
| `image_path` | Path to a PNG or JPEG frame |
| `x1,y1,x2,y2` | Region coordinates (top-left to bottom-right) |
| `label` | Optional name for the region (default: "sample") |

## Extract a Frame First

```bash
# Frame at 30 seconds
ffmpeg -i video.mov -ss 00:00:30 -frames:v 1 frame.png

# Cropped to performer area (better detail)
ffmpeg -i video.mov -ss 00:00:30 -frames:v 1 -vf "crop=800:1000:1500:300" frame_crop.png
```

## Example

```bash
ruby analyze_frame.rb frame.png 1500,600,2000,900 skin
```

Output:
```
=== SKIN ===
Region: [1500, 600, 2000, 900] (150000 pixels)
Avg RGB: R=77.3 G=67.6 B=56.6
Avg HSV: H=31.9° S=0.268 V=0.303
Hue range: 0.0°-358.5° (std=48.1°)
Sat range: 0.053-0.915
Lum range: 0.043-0.882
```

## Reading the Output

| Stat | What It Tells You |
|------|-------------------|
| **Avg HSV H** | Dominant hue. Skin should be 20-35°. Below 15° = too red. Above 45° = too yellow. |
| **Avg HSV S** | Saturation level. Skin is typically 0.15-0.45. Above 0.5 = heavy color cast. |
| **Avg HSV V** | Brightness. Above 0.8 in log = severely overexposed. Below 0.15 = very underexposed. |
| **Hue std** | How spread out the hues are. Low std = consistent color. High std = mixed lighting. |
| **Lum range max** | If this is above 0.85 in log footage, highlights are likely clipping after conversion. |

## Common Patterns

| Analysis Result | Likely Problem | Recommended LUT |
|----------------|---------------|-----------------|
| H=10-20°, S>0.3 on skin | Red/flushed skin | `red_skin_fix` |
| H=20-50°, S>0.25 on neutrals | Yellow/amber cast | `yellow_fix` |
| V>0.8 on skin in log | Overexposed | `overexposure_fix` |
| V<0.2 overall | Underexposed | `underexposure_fix` |
| Dark areas not reaching V=0.0 | Lifted blacks | `black_crush` |

## Sampling Tips

- Sample multiple regions: skin, floor, background, lights
- Use cropped frames (`ffmpeg -vf "crop=..."`) for better accuracy on small subjects
- Compare the same region across different timestamps to see if exposure varies through the clip
- The coordinates are in pixels relative to the image dimensions (3840x2160 for UHD)

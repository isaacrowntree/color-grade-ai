---
title: DaVinci Resolve
description: How to use color-grade-ai LUTs in DaVinci Resolve
---

## Applying a LUT

1. Open your project and go to the **Color** page
2. Select a clip on the timeline
3. Add a **serial node** after your camera conversion LUT (Alt+S or right-click → Add Node → Serial)
4. Right-click the new node → **LUT** → browse to your .cube file
5. The correction is applied immediately

## Node Order

Follow this professional node order for a serial chain. Each node does one job:

| Node | Purpose |
|------|---------|
| 1 | White Balance |
| 2 | Exposure |
| 3 | Main Conversion LUT (e.g. LogC → Rec.709) |
| 4 | General Color Adjustments (Lift/Gamma/Gain) |
| 5 | Color Saturation/Boost |
| 6 | Noise Reduction |
| 7 | Black Levels |
| 8 | Vignette |
| 9 | Sharpening |

Not every grade needs all 9 nodes. Skip what you don't need.

Place color-grade-ai LUTs on nodes **after** your conversion LUT (node 3). For example:
- Node 4: `Yellow_Cast_Fix.cube`
- Node 5: `Overexposure_Fix.cube`
- Node 7: `Black_Crush.cube`

## Stacking Corrections

### Overexposed footage
```
Node 3: Camera → Rec.709 conversion LUT
Node 4: Yellow_Cast_Fix
Node 5: Overexposure_Fix_Minus_1stop
Node 7: Black_Crush
```

### Underexposed footage
```
Node 3: Camera → Rec.709 conversion LUT
Node 4: Yellow_Cast_Fix
Node 5: Underexposure_Fix_Plus_1.2stop
```

### Skin correction only
```
Node 3: Camera → Rec.709 conversion LUT
Node 4: Red_Skin_Fix (leaves everything else alone)
```

## Noise Reduction

LUTs cannot do noise reduction — they have no spatial awareness. Use Resolve's built-in **Temporal NR** and **Spatial NR** in the Motion Effects panel (node 6 in the order above). This is one of Resolve's best features and it's available in the free version.

## Tips

- Use the **Qualifier** (eyedropper) tool for more precise skin isolation than a LUT can provide. The LUT gets you 80% of the way; the Qualifier handles the remaining 20%.
- Toggle nodes on/off with Alt+D to A/B your corrections.
- Right-click a still in the Gallery → Export → .drx to save your full node tree as a reusable grade.

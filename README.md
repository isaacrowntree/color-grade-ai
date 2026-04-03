# color-grade-ai

Generate targeted .cube 3D LUTs for color correction using AI-assisted frame analysis. Works with **DaVinci Resolve** and **Adobe Premiere Pro**.

Built as a [Claude Code](https://claude.ai/claude-code) skill — Claude analyzes your footage, identifies color problems, and generates precise correction LUTs automatically.

[Documentation](https://isaacrowntree.github.io/color-grade-ai) | [Skill Reference](SKILL.md) | [Getting Started](#getting-started) | [Claude Code Skill](#use-as-a-claude-code-skill)

---

## What It Does

Feed it a video frame. It tells you what's wrong and generates a .cube LUT to fix it.

```bash
# Auto-analyze a frame and get per-node recommendations
python3 auto_grade.py frame_709.png

# Generate a correction LUT
ruby generate_lut.rb red_skin_fix skin_fix.cube

# Bake a creative preset into a single LUT
ruby generate_chain_lut.rb studio_balanced.cube \
  studio_punch@0.8 warm_shift@0.3 sat_boost@0.5 black_crush@0.15

# Preview grades interactively in-browser
python3 -m http.server 8080  # then open preview.html
```

The generated .cube files are standard 3D LUTs compatible with any software that reads the format — Resolve, Premiere, Final Cut, After Effects, etc.

## Getting Started

### Requirements

- Ruby 2.7+
- Python 3 with [Pillow](https://pillow.readthedocs.io/) + NumPy (for auto_grade.py)
- [ffmpeg](https://ffmpeg.org/) (for frame extraction and video encoding)

### Install

```bash
git clone https://github.com/isaacrowntree/color-grade-ai.git
cd color-grade-ai
pip3 install Pillow numpy
```

### Generate Your First LUT

```bash
# Extract a frame from your footage
ffmpeg -i your_video.mov -ss 00:00:30 -frames:v 1 frame.png

# Generate a LUT (pick the type that matches your problem)
ruby generate_lut.rb yellow_fix yellow_fix.cube

# Adjust strength if needed (0.0 = no effect, 1.0 = full)
ruby generate_lut.rb yellow_fix yellow_fix_mild.cube --strength=0.5
```

### Apply in Your NLE

**DaVinci Resolve:** Add a serial node after your conversion LUT → right-click → LUT → browse to .cube file.

**Adobe Premiere Pro:** Lumetri Color → Creative tab → Look dropdown → browse to .cube file.

**ffmpeg:**
```bash
ffmpeg -i input.mp4 \
  -vf "lut3d='conversion.cube':interp=tetrahedral,lut3d='correction.cube':interp=tetrahedral" \
  output.mp4
```

## Tools

| Tool | Purpose |
|------|---------|
| `generate_lut.rb` | Generate a single correction LUT from a preset |
| `generate_chain_lut.rb` | Bake multiple presets into one LUT |
| `auto_grade.py` | Analyze a frame and recommend per-node corrections |
| `analyze_frame.rb` | Get HSV/RGB stats for a specific region |
| `preview.html` | Interactive in-browser node chain previewer |

## LUT Presets

### Correction LUTs

| Type | What it fixes |
|------|--------------|
| `night_warm_fix` | Underexposed warm/red scenes — lift + skin fix + black crush |
| `night_purple_fix` | Underexposed purple/magenta stage lighting |
| `yellow_fix` | Yellow/amber cast from stage lighting |
| `red_skin_fix` | Red/flushed skin from warm practicals |
| `pink_cast_fix` | Pink/magenta cast from stage lighting |
| `overexposure_fix` | ~1 stop reduction with highlight rolloff |
| `underexposure_fix` | ~1.2 stop lift with shadow recovery |
| `black_crush` | Crush milky/lifted blacks to true black |
| `skin_highlight_fix` | Skin-only highlight rolloff |

### Node Chain Building Blocks

| Type | Node | What it does |
|------|------|-------------|
| `studio_punch` | Contrast | Subtle contrast boost |
| `film_contrast` | Contrast | Stronger filmic contrast |
| `flat_lift` | Contrast | Lift shadows for softer look |
| `warm_shift` | Temperature | Subtle warm shift |
| `cool_shift` | Temperature | Subtle cool shift |
| `led_green_fix` | Temperature | Fix green tint from LEDs |
| `sat_boost` | Saturation | Global +15% saturation |
| `sat_reduce` | Saturation | Global -15% saturation |
| `sgamut3_to_cine` | Gamut | S-Gamut3 → Cine compensation |
| `black_lift` | Black Level | Faded/vintage blacks |

### Creative Presets

| Preset | Look | Chain |
|--------|------|-------|
| Studio Clean | Natural bright | studio_punch(50%) + sat_boost(50%) |
| Studio Balanced | Warm natural | studio_punch(80%) + warm_shift(30%) + sat_boost(50%) + black_crush(15%) |
| Studio Dance | Warm cinematic | studio_punch(100%) + warm_shift(40%) + sat_boost(60%) + black_crush(25%) |
| Studio Film | Moody cinematic | film_contrast(60%) + warm_shift(20%) + sat_reduce(30%) + black_crush(40%) |

Pre-baked .cube files for all creative presets are in `correction_luts/`.

## Use as a Claude Code Skill

This repo is designed to work as a [Claude Code](https://claude.ai/claude-code) skill. When installed, Claude can analyze your footage and generate LUTs conversationally. The full skill reference is in [SKILL.md](SKILL.md).

### Install the Skill

```bash
# Project-level (for one project)
git clone https://github.com/isaacrowntree/color-grade-ai.git .claude/skills/color-grade

# Personal-level (available everywhere)
git clone https://github.com/isaacrowntree/color-grade-ai.git ~/.claude/skills/color-grade
```

### Use It

Once installed, just talk to Claude naturally:

```
> The skin in my dance video looks sunburnt and red. Can you fix it?

> This stage footage is overexposed and has a yellow cast from the lights

> Analyze the frame at 30 seconds and tell me what corrections I need
```

Or invoke directly:

```
> /color-grade red_skin_fix output.cube
```

## Documentation

The [documentation site](https://isaacrowntree.github.io/color-grade-ai) is auto-generated from [SKILL.md](SKILL.md), which is the single source of truth for all presets, workflows, and color science notes.

To rebuild the docs:

```bash
ruby generate_docs.rb    # regenerate from SKILL.md
cd docs && npm run build  # build the site (runs generate_docs.rb automatically)
```

## Related Projects

- [ButterCut](https://github.com/barefootford/buttercut) — Ruby gem for generating video editing timelines (FCP, Premiere, Resolve) with AI-powered rough cuts.

## License

MIT

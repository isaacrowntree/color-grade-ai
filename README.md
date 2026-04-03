# color-grade-ai

Generate targeted .cube 3D LUTs for color correction using AI-assisted frame analysis. Works with **DaVinci Resolve** and **Adobe Premiere Pro**.

Built as a [Claude Code](https://claude.ai/claude-code) skill — Claude analyzes your footage, identifies color problems, and generates precise correction LUTs automatically.

[Documentation](https://isaacrowntree.github.io/color-grade-ai) | [Skill Reference](SKILL.md)

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
```

### Interactive Preview

Drag-and-drop a frame, load your conversion LUT, and dial in corrections across a 6-node chain — all in the browser.

![Preview UI](docs/public/preview-screenshot.png)

`python3 -m http.server 8080` then open `http://localhost:8080/preview.html`

## Getting Started

### Requirements

- Ruby 2.7+
- Python 3 with [Pillow](https://pillow.readthedocs.io/) + NumPy
- [ffmpeg](https://ffmpeg.org/)

### Install

```bash
git clone https://github.com/isaacrowntree/color-grade-ai.git
cd color-grade-ai
pip3 install Pillow numpy
```

### Quick Example

```bash
# Extract a frame from your footage
ffmpeg -i your_video.mov -ss 00:00:30 -frames:v 1 frame.png

# Generate a LUT
ruby generate_lut.rb yellow_fix yellow_fix.cube

# Apply in ffmpeg
ffmpeg -i input.mp4 \
  -vf "lut3d='conversion.cube':interp=tetrahedral,lut3d='yellow_fix.cube':interp=tetrahedral" \
  output.mp4
```

**DaVinci Resolve:** Add a serial node → right-click → LUT → browse to .cube file.

**Adobe Premiere Pro:** Lumetri Color → Creative → Look dropdown → browse to .cube file.

See [SKILL.md](SKILL.md) for the full list of presets, node chain building blocks, creative presets, auto-grade workflow, and video export recipes.

## Use as a Claude Code Skill

```bash
# Project-level
git clone https://github.com/isaacrowntree/color-grade-ai.git .claude/skills/color-grade

# Personal-level (available everywhere)
git clone https://github.com/isaacrowntree/color-grade-ai.git ~/.claude/skills/color-grade
```

Then just talk to Claude:

```
> The skin in my dance video looks sunburnt and red. Can you fix it?
> Analyze the frame at 30 seconds and tell me what corrections I need
> /color-grade red_skin_fix output.cube
```

## Documentation

The [docs site](https://isaacrowntree.github.io/color-grade-ai) is auto-generated from [SKILL.md](SKILL.md). To rebuild: `ruby generate_docs.rb && cd docs && npm run build`

## Related Projects

- [ButterCut](https://github.com/barefootford/buttercut) — AI-powered video editing timelines for FCP, Premiere, and Resolve.

## License

MIT

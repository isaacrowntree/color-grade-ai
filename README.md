# color-grade-ai

Generate targeted .cube 3D LUTs for color correction using AI-assisted frame analysis. Works with **DaVinci Resolve** and **Adobe Premiere Pro**.

Built as a [Claude Code](https://claude.ai/claude-code) skill — Claude analyzes your footage, identifies color problems, and generates precise correction LUTs automatically.

[Documentation](https://isaacrowntree.github.io/color-grade-ai) | [Getting Started](#getting-started) | [LUT Types](#lut-types) | [Claude Code Skill](#use-as-a-claude-code-skill)

---

## What It Does

Feed it a video frame. It tells you what's wrong and generates a .cube LUT to fix it.

```bash
# Analyze a frame region
ruby analyze_frame.rb frame.png 1500,600,2000,900 skin
# => H=12.3° S=0.38 V=0.45 — red/flushed skin from warm practical light

# Generate a targeted fix
ruby generate_lut.rb warm_skin_cast_fix skin_fix.cube
# => 33x33x33 3D LUT targeting H=354-30°, skin luminance only
```

The generated .cube files are standard 3D LUTs compatible with any software that reads the format — Resolve, Premiere, Final Cut, After Effects, etc.

## Getting Started

### Requirements

- Ruby 2.7+
- Python 3 with [Pillow](https://pillow.readthedocs.io/) (for frame analysis only)
- [ffmpeg](https://ffmpeg.org/) (for frame extraction)

### Platform Setup

<details>
<summary><strong>macOS</strong></summary>

```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install dependencies
brew install ruby python ffmpeg
pip3 install Pillow
```
</details>

<details>
<summary><strong>Linux (Ubuntu/Debian)</strong></summary>

```bash
sudo apt update
sudo apt install ruby python3 python3-pip ffmpeg
pip3 install Pillow
```
</details>

<details>
<summary><strong>Windows (WSL recommended)</strong></summary>

Video editors on Windows should use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) (Windows Subsystem for Linux). This gives you a full Linux terminal alongside your Windows NLE.

```powershell
# 1. Install WSL (run PowerShell as Administrator)
wsl --install

# 2. Restart your computer, then open "Ubuntu" from the Start menu

# 3. Inside WSL, install dependencies
sudo apt update
sudo apt install ruby python3 python3-pip ffmpeg
pip3 install Pillow
```

Your Windows drives are accessible from WSL at `/mnt/c/`, `/mnt/d/`, etc. So if your footage is at `D:\Videos\`, you can access it from WSL at `/mnt/d/Videos/`.

```bash
# Example: extract a frame from footage on your D: drive
ffmpeg -i /mnt/d/Videos/my_clip.mov -ss 00:00:30 -frames:v 1 frame.png

# Generate a LUT and save it where Premiere/Resolve can find it
ruby generate_lut.rb yellow_fix /mnt/d/Videos/LUTs/yellow_fix.cube
```
</details>

### Install

```bash
git clone https://github.com/isaacrowntree/color-grade-ai.git
cd color-grade-ai
```

No gems or packages to install. The scripts run standalone.

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

**DaVinci Resolve:**
1. Go to the Color page
2. Add a serial node after your conversion LUT
3. Right-click the node → LUT → browse to the .cube file

**Adobe Premiere Pro:**
1. Add an adjustment layer above your clip
2. Apply Lumetri Color effect
3. Creative tab → Look dropdown → browse to the .cube file

## LUT Types

| Type | Problem | What It Does |
|------|---------|-------------|
| `yellow_fix` | Yellow/amber cast from stage or practical lights | Desaturates H=10-60° by 55%, shifts hue toward neutral |
| `warm_skin_cast_fix` | Sunburnt/flushed red skin | Shifts red skin hues toward peach. Three-way window (hue + sat + lum) targets only skin, leaves lights and objects alone |
| `overexposure_fix` | Blown highlights, washed out scene | ~1 stop global reduction + highlight rolloff from 55% + extra skin protection |
| `underexposure_fix` | Too dark, lost shadow detail | ~1.2 stop lift + shadow recovery + highlight protection |
| `black_crush` | Milky/lifted blacks | Crushes shadows below 12% luminance with smooth transition |
| `skin_highlight_fix` | Minor skin overexposure | Subtle rolloff above 70% luminance, skin hues only |

Every type supports `--strength=N` (0.0-1.0) and `--size=N` (LUT grid size, default 33).

## Stacking LUTs

LUTs stack on separate adjustment layers or nodes. Apply your camera conversion LUT first, then stack fixes:

**Overexposed footage:**
```
1. ARRI LogC → Rec.709 (or your camera LUT)
2. Yellow Cast Fix
3. Overexposure Fix (-1 stop)
4. Black Crush
```

**Underexposed footage:**
```
1. Camera conversion LUT
2. Yellow Cast Fix
3. Underexposure Fix (+1.2 stops)
```

**Skin correction only:**
```
1. Camera conversion LUT
2. Warm Skin Cast Fix (leaves everything else alone)
```

## Frame Analysis

Analyze specific regions of a frame to get precise HSV/RGB stats:

```bash
# Extract a frame
ffmpeg -i video.mov -ss 00:00:30 -frames:v 1 frame.png

# Analyze the skin area (coordinates: x1,y1,x2,y2)
ruby analyze_frame.rb frame.png 1800,500,2000,900 skin

# Output:
# === SKIN ===
# Avg RGB: R=77.3 G=67.6 B=56.6
# Avg HSV: H=31.9° S=0.268 V=0.303
# Hue range: 0.0°-358.5° (std=48.1°)
```

Use this to understand what correction is needed before generating a LUT.

## Use as a Claude Code Skill

This repo is designed to work as a [Claude Code](https://claude.ai/claude-code) skill. When installed, Claude can analyze your footage and generate LUTs conversationally.

### What is Claude Code?

[Claude Code](https://claude.ai/claude-code) is Anthropic's CLI tool that lets Claude (AI) work directly with your files and terminal. Think of it as having an assistant that can see your project, run commands, and generate files — all from a chat interface in your terminal.

If you're a video editor who hasn't used it before, here's how to get going:

**1. Install Node.js** (if you don't have it):
- macOS: `brew install node`
- Ubuntu/WSL: `sudo apt install nodejs npm`
- Or download from [nodejs.org](https://nodejs.org/)

**2. Install Claude Code:**
```bash
npm install -g @anthropic-ai/claude-code
```

**3. Set up your API key:**
- Create an account at [console.anthropic.com](https://console.anthropic.com)
- Go to API Keys and create one
- Claude Code will prompt you for it on first run

**4. Run it:**
```bash
cd /path/to/your/video/project
claude
```

You're now in a conversation with Claude. It can see your files, run ffmpeg, generate LUTs, and talk to you about color correction like a colleague sitting next to you.

**Skills** are like plugins that give Claude specialized knowledge. When you install this skill, Claude knows how to analyze footage and generate correction LUTs without you having to explain the process.

### Install the Skill

Clone this repo into your project's Claude skills directory:

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

> Generate LUTs to fix the exposure and color on this clip
```

Claude will use the skill to analyze frames, identify problems, and generate the right LUTs.

You can also invoke it directly:

```
> /color-grade warm_skin_cast_fix output.cube
```

## How It Works

The LUT generator works in HSL color space. For each point in a 33x33x33 RGB grid:

1. Convert input RGB to HSL
2. Check if the pixel falls within the correction's targeting window (hue range, saturation range, luminance range)
3. Apply the correction (hue shift, desaturation, exposure change) proportionally
4. Convert back to RGB
5. Write the result to a standard .cube file

This means corrections are mathematically precise and repeatable. The same LUT produces the same result every time on the same footage.

## Related Projects

- [ButterCut](https://github.com/barefootford/buttercut) — Ruby gem for generating video editing timelines (FCP, Premiere, Resolve) with AI-powered rough cuts. Color-grade-ai was originally developed as part of ButterCut's color grading pipeline.

## Contributing

PRs welcome. Areas that could use help:

- Additional LUT presets for common correction scenarios
- Support for 1D LUT generation
- ACES/OCIO color space transforms
- Integration with DaVinci Resolve's scripting API

## License

MIT

---
title: Getting Started
description: Install color-grade-ai and generate your first LUT
---

## Requirements

- **Ruby** 2.7+
- **Python 3** with Pillow (for frame analysis only)
- **ffmpeg** (for frame extraction)

## Platform Setup

### macOS

```bash
brew install ruby python ffmpeg
pip3 install Pillow
```

### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install ruby python3 python3-pip ffmpeg
pip3 install Pillow
```

### Windows (WSL)

Video editors on Windows should use [WSL](https://learn.microsoft.com/en-us/windows/wsl/install) (Windows Subsystem for Linux). This gives you a full Linux terminal alongside your Windows NLE.

```powershell
# Run PowerShell as Administrator
wsl --install
```

Restart your computer, then open "Ubuntu" from the Start menu:

```bash
sudo apt update
sudo apt install ruby python3 python3-pip ffmpeg
pip3 install Pillow
```

Your Windows drives are accessible from WSL at `/mnt/c/`, `/mnt/d/`, etc. So if your footage is at `D:\Videos\`, access it at `/mnt/d/Videos/`.

## Install

```bash
git clone https://github.com/isaacrowntree/color-grade-ai.git
cd color-grade-ai
```

No gems or packages to install. The scripts run standalone.

## Generate Your First LUT

### 1. Extract a frame

```bash
ffmpeg -i your_video.mov -ss 00:00:30 -frames:v 1 frame.png
```

### 2. Generate a LUT

Pick the type that matches your problem:

```bash
ruby generate_lut.rb yellow_fix yellow_fix.cube
```

### 3. Adjust strength (optional)

All LUTs support a `--strength` flag from 0.0 (no effect) to 1.0 (full):

```bash
ruby generate_lut.rb yellow_fix yellow_fix_mild.cube --strength=0.5
```

### 4. Apply in your NLE

**DaVinci Resolve:** Color page → add a serial node after your conversion LUT → right-click → LUT → browse to the .cube file.

**Premiere Pro:** Adjustment layer → Lumetri Color → Creative → Look dropdown → browse to the .cube file.

## Next Steps

- [LUT Types Reference](/color-grade-ai/reference/lut-types/) — see all available presets
- [DaVinci Resolve Guide](/color-grade-ai/guides/davinci-resolve/) — detailed Resolve workflow
- [Premiere Pro Guide](/color-grade-ai/guides/premiere-pro/) — detailed Premiere workflow
- [Using with Claude Code](/color-grade-ai/guides/claude-code/) — let AI generate LUTs for you

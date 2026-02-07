---
title: Using with Claude Code
description: Install color-grade-ai as a Claude Code skill for AI-assisted color grading
---

## What is Claude Code?

[Claude Code](https://claude.ai/claude-code) is Anthropic's CLI tool that lets Claude (AI) work directly with your files and terminal. You type in natural language, and Claude can read files, run commands, and generate output.

For video editors, this means you can describe a color problem in plain English and Claude will analyze frames, identify the issue, and generate the right correction LUT.

## Install Claude Code

### 1. Install Node.js

- **macOS:** `brew install node`
- **Ubuntu/WSL:** `sudo apt install nodejs npm`
- **Or download:** [nodejs.org](https://nodejs.org/)

### 2. Install Claude Code

```bash
npm install -g @anthropic-ai/claude-code
```

### 3. Get an API Key

1. Create an account at [console.anthropic.com](https://console.anthropic.com)
2. Go to **API Keys** and create one
3. Claude Code will prompt you for it on first run

### 4. Run It

```bash
cd /path/to/your/video/project
claude
```

You're now in a chat with Claude in your terminal.

## Install the Skill

Clone this repo into Claude's skills directory:

```bash
# For one project
git clone https://github.com/isaacrowntree/color-grade-ai.git .claude/skills/color-grade

# Or for all your projects (personal skill)
git clone https://github.com/isaacrowntree/color-grade-ai.git ~/.claude/skills/color-grade
```

## Using It

Once installed, just describe what you need. Claude will figure out which tools to use:

### Describe the problem
```
> The dancer in my stage video looks overexposed and there's a yellow
  cast from the lights. Can you fix it?
```

Claude will:
1. Ask you for the video file path
2. Extract frames with ffmpeg
3. Analyze color regions with `analyze_frame.rb`
4. Identify the correction needed
5. Generate the right .cube LUT with `generate_lut.rb`
6. Tell you how to apply it

### Ask for analysis
```
> Look at frame.png and tell me what color corrections this footage needs
```

### Generate specific LUTs
```
> Generate a strong overexposure fix and a mild yellow cast fix for this clip
```

### Invoke directly
```
> /color-grade overexposure_fix output.cube --strength=0.8
```

## Example Session

```
you: I have a dance performance shot on Sony A7IV with S-Log3.
     The skin on the performer looks sunburnt red from the warm
     stage lights. The video is at /mnt/d/Videos/performance.mov

claude: Let me extract a frame and analyze the skin tones.
        [extracts frame at 30s, crops to performer, runs analyze_frame.rb]

        The skin is sitting at H=12° S=0.38 — pushed deep into the red
        range. Natural skin should be around H=25° (peach). I'll generate
        a targeted fix.

        [runs generate_lut.rb red_skin_fix]

        Generated: /mnt/d/Videos/LUTs/Red_Skin_Fix.cube

        Apply it in Resolve on a node after your conversion LUT,
        or in Premiere on an adjustment layer via Creative > Look.
```

## Tips

- Claude can see screenshots. Paste a screenshot of your Premiere/Resolve viewer and say "what's wrong with this and how do I fix it."
- If a LUT is too strong or too weak, just say "that's too aggressive, try half strength" and Claude will regenerate it.
- Claude remembers context within a session, so you can iterate: "now do the same for the underexposed section at 2 minutes."

#!/usr/bin/env ruby
# generate_docs.rb - Auto-generate Starlight docs from presets.yml
#
# Reads presets.yml and generates:
#   docs/src/content/docs/reference/lut-types.md
#   docs/src/content/docs/reference/presets-config.md
#
# Run: ruby generate_docs.rb

require 'yaml'

PRESETS_PATH = File.join(__dir__, 'presets.yml')
DOCS_DIR = File.join(__dir__, 'docs', 'src', 'content', 'docs', 'reference')

presets = YAML.load_file(PRESETS_PATH)

# ── Step type documentation ──────────────────────────────────────────

STEP_DOCS = {
  'rgb_rebalance' => {
    desc: 'Per-channel RGB gain adjustment, scaled by luminance to avoid wild hue swings in dark pixels.',
    params: { 'r_gain' => 'Red channel multiplier (1.0 = neutral)', 'g_gain' => 'Green channel multiplier', 'b_gain' => 'Blue channel multiplier', 'gain_ramp' => 'Luminance threshold for full gain (below this, gains are reduced)' }
  },
  'exposure' => {
    desc: 'Global exposure adjustment via gamma curve with optional shadow floor lift.',
    params: { 'gamma' => 'Gamma value at full strength (>1.0 darkens, <1.0 brightens)', 'shadow_lift' => 'Shadow floor lift amount (0.0-0.05 typical)' }
  },
  'highlight_protect' => {
    desc: 'Soft knee highlight compression to prevent clipping.',
    params: { 'knee_start' => 'Luminance where compression begins (0.0-1.0)', 'knee_ceiling' => 'Maximum output luminance' }
  },
  'black_crush' => {
    desc: 'Steepens shadow ramp to push milky blacks toward true black.',
    params: { 'black_threshold' => 'Luminance below which full crush applies', 'crush_gamma' => 'Gamma at full strength (higher = steeper crush)', 'transition_end' => 'Luminance where crush blends back to identity' }
  },
  'hue_desat' => {
    desc: 'Hue-targeted desaturation with optional hue shift. Good for neutralizing color casts.',
    params: { 'hue_center' => 'Center hue angle (0-360)', 'hue_width' => 'Half-width of hue window in degrees', 'softness' => 'Feathering of hue window edges', 'sat_reduce' => 'Target saturation ratio (0.45 = reduce to 45%)', 'hue_shift' => 'Hue rotation in degrees (optional, default 0)', 'min_sat' => 'Minimum saturation to trigger (optional)', 'sat_scaling_ref' => 'Saturation reference for scaling effect (optional)' }
  },
  'skin_correction' => {
    desc: 'Targeted hue shift using 3-way window (hue + luminance + saturation) to isolate skin tones.',
    params: { 'hue_center' => 'Center of skin hue range', 'hue_width' => 'Half-width of hue window', 'hue_soft' => 'Hue window feathering', 'hue_shift' => 'Degrees to shift hue toward natural skin', 'lum_low' => 'Lower luminance bound', 'lum_high' => 'Upper luminance bound', 'lum_soft' => 'Luminance window feathering', 'sat_low' => 'Lower saturation bound', 'sat_high' => 'Upper saturation bound', 'sat_soft' => 'Saturation window feathering', 'adaptive_desat' => 'Enable adaptive desaturation (true/false)' }
  },
  'shadow_sat_boost' => {
    desc: 'Saturation boost in shadows to counteract washed-out lifted darks.',
    params: { 'boost' => 'Saturation boost amount (0.10 = +10%)', 'range_low' => 'Lower luminance bound', 'range_high' => 'Upper luminance bound' }
  },
  'skin_highlight' => {
    desc: 'Skin-targeted highlight rolloff with desaturation, plus gentle global highlight protection.',
    params: { 'skin_hue_center' => 'Center of skin hue range', 'skin_hue_width' => 'Half-width', 'skin_softness' => 'Feathering', 'knee_start' => 'Skin highlight knee', 'knee_ceiling' => 'Skin max luminance', 'global_knee' => 'Global highlight knee', 'global_ceiling' => 'Global max luminance', 'hot_desat' => 'Desaturation ratio for blown skin', 'min_sat_ratio' => 'Minimum saturation for skin detection' }
  },
  'skin_rolloff' => {
    desc: 'Skin-targeted luminance rolloff blended by skin strength. Used for overexposure correction.',
    params: { 'skin_hue_center' => 'Center of skin hue range', 'skin_hue_width' => 'Half-width', 'skin_softness' => 'Feathering', 'knee_start' => 'Rolloff start luminance', 'knee_ceiling' => 'Max luminance for skin', 'min_sat' => 'Minimum saturation gate' }
  },
  'global_highlight_desat' => {
    desc: 'Desaturate blown highlights across the entire image.',
    params: { 'threshold' => 'Luminance above which desat begins', 'desat_amount' => 'Maximum desat ratio' }
  }
}

# ── Generate lut-types.md ────────────────────────────────────────────

Dir.mkdir(DOCS_DIR) unless Dir.exist?(DOCS_DIR)

File.open(File.join(DOCS_DIR, 'lut-types.md'), 'w') do |f|
  f.puts <<~HEADER
    ---
    title: LUT Types
    description: Reference for all available LUT presets
    ---

    All LUTs are generated with `generate_lut.rb` and support these options:

    - `--strength=N` — Effect intensity from 0.0 (no change) to 1.0 (full). Default: 1.0
    - `--size=N` — LUT grid resolution. Default: 33 (33x33x33 = 35,937 sample points)

    Presets are defined in [`presets.yml`](/color-grade-ai/reference/presets-config/). Add new LUT types by editing the YAML.
  HEADER

  presets.each do |name, cfg|
    f.puts ""
    f.puts "## #{name}"
    f.puts ""

    # Title and comments as description
    f.puts "**#{cfg['title']}**"
    f.puts ""
    if cfg['comments']
      cfg['comments'].each { |c| f.puts "> #{c}" }
      f.puts ""
    end

    f.puts "```bash"
    f.puts "ruby generate_lut.rb #{name} output.cube"
    f.puts "```"
    f.puts ""

    # Pipeline steps
    f.puts "### Pipeline"
    f.puts ""
    cfg['pipeline'].each_with_index do |step, i|
      step_type = step['step']
      doc = STEP_DOCS[step_type]
      f.puts "#{i + 1}. **#{step_type}** — #{doc ? doc[:desc] : 'Custom step'}"

      # Show key parameters
      params = step.reject { |k, _| k == 'step' }
      unless params.empty?
        f.puts ""
        f.puts "   | Parameter | Value |"
        f.puts "   |-----------|-------|"
        params.each { |k, v| f.puts "   | #{k} | #{v} |" }
        f.puts ""
      end
    end
  end
end

puts "Generated: docs/src/content/docs/reference/lut-types.md"

# ── Generate presets-config.md ────────────────────────────────────────

File.open(File.join(DOCS_DIR, 'presets-config.md'), 'w') do |f|
  f.puts <<~HEADER
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
  HEADER

  STEP_DOCS.each do |step_name, doc|
    f.puts ""
    f.puts "### #{step_name}"
    f.puts ""
    f.puts doc[:desc]
    f.puts ""
    f.puts "| Parameter | Description |"
    f.puts "|-----------|-------------|"
    doc[:params].each { |param, desc| f.puts "| `#{param}` | #{desc} |" }
  end

  f.puts ""
  f.puts <<~FOOTER
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
  FOOTER
end

puts "Generated: docs/src/content/docs/reference/presets-config.md"

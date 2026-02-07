#!/usr/bin/env ruby
# generate_lut.rb - Generate 3D .cube LUT files for color correction
#
# Works with both DaVinci Resolve and Adobe Premiere Pro.
# Apply AFTER a LogC->Rec.709 conversion LUT in your node/effect chain.
#
# Presets are defined in presets.yml. Each preset is a pipeline of ordered
# steps. Adding a new LUT type means adding a YAML entry, not writing Ruby.
#
# Usage:
#   ruby generate_lut.rb <type> <output_path> [options]
#
# Types (from presets.yml):
#   yellow_fix         - Remove warm amber/yellow cast from stage lighting
#   red_skin_fix       - Fix red/flushed/blotchy skin, shifts hue to peach
#   night_warm_fix     - All-in-one: underexp lift + skin hue fix + black crush (no desat)
#   night_purple_fix   - All-in-one: purple cast removal + ~2 stop lift + skin fix + black crush
#   overexposure_fix   - Scene-wide overexposure correction (~1 stop, all hues)
#   underexposure_fix  - Scene-wide underexposure lift (~1.2 stops, shadow recovery)
#   black_crush        - Crush milky/lifted blacks to true black
#   skin_highlight_fix - Roll off overexposed skin highlights only (subtle)
#
# Examples:
#   ruby generate_lut.rb yellow_fix /mnt/h/yellow_cast_fix.cube
#   ruby generate_lut.rb overexposure_fix /mnt/h/overexposure_fix.cube
#   ruby generate_lut.rb black_crush /mnt/h/black_crush.cube
#   ruby generate_lut.rb overexposure_fix /mnt/h/mild.cube --strength=0.5
#
# Options:
#   --strength=N   Overall strength 0.0-1.0 (default: 1.0)
#   --size=N       LUT grid size (default: 33)

require 'optparse'
require 'yaml'

LUT_DEFAULT_SIZE = 33

# ── Color space helpers ──────────────────────────────────────────────

def rgb_to_hsl(r, g, b)
  max = [r, g, b].max
  min = [r, g, b].min
  l = (max + min) / 2.0

  if max == min
    return [0.0, 0.0, l]
  end

  d = max - min
  s = l > 0.5 ? d / (2.0 - max - min) : d / (max + min)

  h = case max
      when r then (g - b) / d + (g < b ? 6.0 : 0.0)
      when g then (b - r) / d + 2.0
      when b then (r - g) / d + 4.0
      end
  h *= 60.0

  [h, s, l]
end

def hsl_to_rgb(h, s, l)
  return [l, l, l] if s == 0.0

  q = l < 0.5 ? l * (1.0 + s) : l + s - l * s
  p = 2.0 * l - q
  hk = h / 360.0

  [hk + 1.0/3.0, hk, hk - 1.0/3.0].map do |t|
    t += 1.0 if t < 0
    t -= 1.0 if t > 1
    if    t < 1.0/6.0 then p + (q - p) * 6.0 * t
    elsif t < 0.5     then q
    elsif t < 2.0/3.0 then p + (q - p) * (2.0/3.0 - t) * 6.0
    else  p
    end
  end
end

# Smooth interpolation for hue-based targeting
def hue_strength(hue, center, width, softness)
  diff = (hue - center).abs
  diff = 360.0 - diff if diff > 180.0

  if diff <= width - softness
    1.0
  elsif diff <= width + softness
    t = (diff - (width - softness)) / (2.0 * softness)
    (1.0 + Math.cos(t * Math::PI)) / 2.0
  else
    0.0
  end
end

# Soft knee highlight rolloff. Maps input luminance to compressed output.
# knee_start: where rolloff begins (0.0-1.0)
# knee_end: maximum output value (ceiling)
def soft_knee_rolloff(value, knee_start, knee_end)
  return value if value <= knee_start

  # Quadratic rolloff above knee
  range = 1.0 - knee_start
  overshoot = (value - knee_start) / range
  compressed = knee_start + (knee_end - knee_start) * (1.0 - (1.0 - overshoot) ** 0.5)
  # Simpler: use a power curve for gentle compression
  t = (value - knee_start) / range
  knee_start + (knee_end - knee_start) * (2.0 * t - t * t)
end

def clamp(v, lo = 0.0, hi = 1.0)
  [[v, lo].max, hi].min
end

# Luminance window helper — returns 0.0-1.0 based on position in window
def lum_window(l, low, high, soft)
  if l < low
    0.0
  elsif l < low + soft
    (l - low) / soft
  elsif l > high
    0.0
  elsif l > high - soft
    (high - l) / soft
  else
    1.0
  end
end

# Saturation window helper — returns 0.0-1.0 based on position in window
def sat_window(s, low, high, soft)
  if s < low
    0.0
  elsif s < low + soft
    (s - low) / soft
  elsif s > high
    0.0
  elsif s > high - soft
    (high - s) / soft
  else
    1.0
  end
end

# ── Preset loader ────────────────────────────────────────────────────

def load_presets(path = nil)
  path ||= File.join(File.dirname(__FILE__), 'presets.yml')
  YAML.load_file(path)
end

def load_preset(name, path = nil)
  presets = load_presets(path)
  preset = presets[name]
  abort "Unknown preset: #{name}\nAvailable: #{presets.keys.join(', ')}" unless preset
  preset
end

# ── Pipeline step handlers ───────────────────────────────────────────
#
# Each handler receives (r, g, b, state, step_config, strength) where
# state = { h:, s:, l:, orig_l: }. Returns [r, g, b, state].
#
# state[:h], state[:s], state[:l] track the current HSL values.
# state[:orig_l] holds the luminance from the last full HSL recomputation
# (initial or after rgb_rebalance). Luminance-only steps (exposure,
# highlight_protect, black_crush) update :l but NOT :orig_l.
# Window-based steps (skin_correction, shadow_sat_boost) use :orig_l
# for their luminance windows, matching the original monolithic functions.

def step_rgb_rebalance(r, g, b, st, cfg, strength)
  r_gain = 1.0 + (cfg['r_gain'] - 1.0) * strength
  g_gain = 1.0 + (cfg['g_gain'] - 1.0) * strength
  b_gain = 1.0 + (cfg['b_gain'] - 1.0) * strength
  gain_ramp = cfg['gain_ramp']

  lum = [r, g, b].max
  gain_scale = [[lum / gain_ramp, 1.0].min, 0.0].max

  r = clamp(r * (1.0 + (r_gain - 1.0) * gain_scale))
  g = clamp(g * (1.0 + (g_gain - 1.0) * gain_scale))
  b = clamp(b * (1.0 + (b_gain - 1.0) * gain_scale))

  h, s, l = rgb_to_hsl(r, g, b)
  [r, g, b, { h: h, s: s, l: l, orig_l: l }]
end

def step_exposure(r, g, b, st, cfg, strength)
  h, s, l = st[:h], st[:s], st[:l]
  gamma = 1.0 + (cfg['gamma'] - 1.0) * strength
  shadow_lift = cfg['shadow_lift'] * strength

  new_l = l + shadow_lift * (1.0 - l)
  new_l = new_l ** gamma

  r, g, b = hsl_to_rgb(h, s, new_l)
  [r, g, b, st.merge(l: new_l)]
end

def step_highlight_protect(r, g, b, st, cfg, strength)
  h, s, l = st[:h], st[:s], st[:l]
  knee_start = cfg['knee_start']
  knee_ceiling = cfg['knee_ceiling']

  if l > knee_start
    over = (l - knee_start) / (1.0 - knee_start)
    new_l = knee_start + (knee_ceiling - knee_start) * (2.0 * over - over * over)
    r, g, b = hsl_to_rgb(h, s, new_l)
    [r, g, b, st.merge(l: new_l)]
  else
    [r, g, b, st]
  end
end

def step_black_crush(r, g, b, st, cfg, strength)
  h, s, l = st[:h], st[:s], st[:l]
  black_threshold = cfg['black_threshold']
  crush_gamma = 1.0 + (cfg['crush_gamma'] - 1.0) * strength
  transition_end = cfg['transition_end']

  if l < transition_end
    crushed_l = l ** crush_gamma
    if l < black_threshold
      new_l = crushed_l
    else
      t = (l - black_threshold) / (transition_end - black_threshold)
      t = t * t * (3.0 - 2.0 * t)
      new_l = crushed_l + (l - crushed_l) * t
    end
    r, g, b = hsl_to_rgb(h, s, new_l)
    [r, g, b, st.merge(l: new_l)]
  else
    [r, g, b, st]
  end
end

def step_hue_desat(r, g, b, st, cfg, strength)
  h, s, l = st[:h], st[:s], st[:l]
  hue_center = cfg['hue_center']
  hue_width = cfg['hue_width']
  softness = cfg['softness']
  sat_reduce = cfg['sat_reduce']
  hue_shift_val = cfg['hue_shift'] || 0.0
  min_sat = cfg['min_sat'] || 0.0
  sat_scaling_ref = cfg['sat_scaling_ref']

  if s > min_sat
    str = hue_strength(h, hue_center, hue_width, softness)
    if str > 0
      if sat_scaling_ref
        sat_factor = [s / sat_scaling_ref, 1.0].min
        effective = str * sat_factor * strength
      else
        effective = str * strength
      end

      new_s = s * (1.0 - effective * (1.0 - sat_reduce))
      new_h = h + hue_shift_val * effective
      new_h += 360.0 if new_h < 0
      new_h -= 360.0 if new_h >= 360.0

      r, g, b = hsl_to_rgb(new_h, new_s, l)
      return [r, g, b, st.merge(h: new_h, s: new_s)]
    end
  end

  [r, g, b, st]
end

def step_skin_correction(r, g, b, st, cfg, strength)
  h, s, l = st[:h], st[:s], st[:l]
  orig_l = st[:orig_l]

  hue_center = cfg['hue_center']
  hue_width = cfg['hue_width']
  hue_soft = cfg['hue_soft']
  hue_shift_val = cfg['hue_shift']

  lum_low = cfg['lum_low']
  lum_high = cfg['lum_high']
  lum_soft = cfg['lum_soft']
  sat_low = cfg['sat_low']
  sat_high = cfg['sat_high']
  sat_soft = cfg['sat_soft']

  adaptive_desat = cfg['adaptive_desat']
  min_sat = cfg['min_sat'] || 0.04

  hue_str = hue_strength(h, hue_center, hue_width, hue_soft)

  if hue_str > 0 && s > min_sat
    # Use orig_l for luminance window (matches original monolithic code)
    lum_str = lum_window(orig_l, lum_low, lum_high, lum_soft)
    sat_str = sat_window(s, sat_low, sat_high, sat_soft)

    effective = hue_str * lum_str * sat_str * strength

    if effective > 0.01
      new_h = h + hue_shift_val * effective
      new_h += 360.0 if new_h < 0
      new_h -= 360.0 if new_h >= 360.0

      new_s = s
      if adaptive_desat
        desat_baseline = cfg['desat_baseline']
        desat_range = cfg['desat_range']
        desat_sat_ref = cfg['desat_sat_ref']
        desat_sat_range = cfg['desat_sat_range']

        excess_sat = [s - desat_sat_ref, 0.0].max / desat_sat_range
        sat_reduce = desat_baseline - desat_range * excess_sat
        new_s = s * (1.0 - effective * (1.0 - sat_reduce))
      end

      r, g, b = hsl_to_rgb(new_h, new_s, l)
      return [r, g, b, st.merge(h: new_h, s: new_s)]
    end
  end

  [r, g, b, st]
end

def step_shadow_sat_boost(r, g, b, st, cfg, strength)
  h, s, l = st[:h], st[:s], st[:l]
  orig_l = st[:orig_l]
  boost = cfg['boost']
  range_low = cfg['range_low']
  range_high = cfg['range_high']

  # Use orig_l for range check (matches original code)
  if orig_l > range_low && orig_l < range_high
    shadow_boost = [(range_high - orig_l) / (range_high - range_low), 1.0].min
    new_s = s * (1.0 + boost * shadow_boost * strength)
    new_s = [new_s, 1.0].min
    r, g, b = hsl_to_rgb(h, new_s, l)
    [r, g, b, st.merge(s: new_s)]
  else
    [r, g, b, st]
  end
end

def step_skin_highlight(r, g, b, st, cfg, strength)
  h, s, l = st[:h], st[:s], st[:l]
  skin_hue_center = cfg['skin_hue_center']
  skin_hue_width = cfg['skin_hue_width']
  skin_softness = cfg['skin_softness']
  knee_start = cfg['knee_start']
  knee_ceiling = cfg['knee_ceiling']
  global_knee = cfg['global_knee']
  global_ceiling = cfg['global_ceiling']
  hot_desat = cfg['hot_desat']
  min_sat_ratio = cfg['min_sat_ratio']

  skin_str = hue_strength(h, skin_hue_center, skin_hue_width, skin_softness)
  effective_skin = skin_str * [s / min_sat_ratio, 1.0].min * strength

  if l > knee_start && effective_skin > 0.1
    new_l = soft_knee_rolloff(l, knee_start, knee_ceiling)
    blended_l = l + (new_l - l) * effective_skin

    hot_amount = [(l - knee_start) / (1.0 - knee_start), 1.0].min
    desat_factor = 1.0 - (1.0 - hot_desat) * hot_amount * effective_skin
    new_s = s * desat_factor

    r, g, b = hsl_to_rgb(h, new_s, blended_l)
    [r, g, b, st.merge(s: new_s, l: blended_l)]
  elsif l > global_knee
    new_l = soft_knee_rolloff(l, global_knee, global_ceiling)
    blended_l = l + (new_l - l) * strength * (1.0 - effective_skin)
    r, g, b = hsl_to_rgb(h, s, blended_l)
    [r, g, b, st.merge(l: blended_l)]
  else
    [r, g, b, st]
  end
end

def step_skin_rolloff(r, g, b, st, cfg, strength)
  # Skin-targeted luminance rolloff (used by overexposure_fix).
  # Unlike skin_highlight, this uses a simple blend without threshold gating.
  h, s, l = st[:h], st[:s], st[:l]
  skin_hue_center = cfg['skin_hue_center']
  skin_hue_width = cfg['skin_hue_width']
  skin_softness = cfg['skin_softness']
  knee_start = cfg['knee_start']
  knee_ceiling = cfg['knee_ceiling']
  min_sat = cfg['min_sat'] || 0.03

  skin_str = s > min_sat ? hue_strength(h, skin_hue_center, skin_hue_width, skin_softness) : 0.0
  if skin_str > 0 && l > knee_start
    skin_target = soft_knee_rolloff(l, knee_start, knee_ceiling)
    new_l = l + (skin_target - l) * skin_str * [s / 0.1, 1.0].min
    r, g, b = hsl_to_rgb(h, s, new_l)
    [r, g, b, st.merge(l: new_l)]
  else
    [r, g, b, st]
  end
end

def step_global_highlight_desat(r, g, b, st, cfg, strength)
  h, s, l = st[:h], st[:s], st[:l]
  threshold = cfg['threshold']
  desat_amount = cfg['desat_amount']

  if l > threshold
    hot = [(l - threshold) / (1.0 - threshold), 1.0].min
    new_s = s * (1.0 - hot * desat_amount * strength)
    r, g, b = hsl_to_rgb(h, new_s, l)
    [r, g, b, st.merge(s: new_s)]
  else
    [r, g, b, st]
  end
end

# ── Pipeline runner ──────────────────────────────────────────────────

STEP_HANDLERS = {
  'rgb_rebalance'        => method(:step_rgb_rebalance),
  'exposure'             => method(:step_exposure),
  'highlight_protect'    => method(:step_highlight_protect),
  'black_crush'          => method(:step_black_crush),
  'hue_desat'            => method(:step_hue_desat),
  'skin_correction'      => method(:step_skin_correction),
  'shadow_sat_boost'     => method(:step_shadow_sat_boost),
  'skin_highlight'       => method(:step_skin_highlight),
  'skin_rolloff'         => method(:step_skin_rolloff),
  'global_highlight_desat' => method(:step_global_highlight_desat),
}

def apply_pipeline(r, g, b, pipeline, strength)
  h, s, l = rgb_to_hsl(r, g, b)
  state = { h: h, s: s, l: l, orig_l: l }

  pipeline.each do |step_cfg|
    step_type = step_cfg['step']
    handler = STEP_HANDLERS[step_type]
    abort "Unknown step type: #{step_type}" unless handler
    r, g, b, state = handler.call(r, g, b, state, step_cfg, strength)
  end

  [r, g, b]
end

# ── LUT file writer ──────────────────────────────────────────────────

def generate_lut(size, &transform)
  table = []
  size.times do |bi|
    size.times do |gi|
      size.times do |ri|
        r = ri.to_f / (size - 1)
        g = gi.to_f / (size - 1)
        b = bi.to_f / (size - 1)

        ro, go, bo = transform.call(r, g, b)
        table << [clamp(ro), clamp(go), clamp(bo)]
      end
    end
  end
  table
end

def write_cube(path, table, size, title, comments = [])
  File.open(path, 'w') do |f|
    comments.each { |c| f.puts "# #{c}" }
    f.puts "TITLE \"#{title}\""
    f.puts "LUT_3D_SIZE #{size}"
    f.puts ""
    table.each do |r, g, b|
      f.printf("%.6f %.6f %.6f\n", r, g, b)
    end
  end
end

# ── CLI ──────────────────────────────────────────────────────────────

if __FILE__ == $0
  lut_type = ARGV.shift
  presets = load_presets

  unless lut_type
    abort <<~USAGE
      Usage: ruby generate_lut.rb <type> <output_path> [--strength=N] [--size=N]

      Types:
      #{presets.map { |name, cfg| "  %-22s %s" % [name, cfg['title']] }.join("\n")}

      Options:
        --strength=N   Overall strength 0.0-1.0 (default: 1.0)
        --size=N       LUT grid size (default: 33)
    USAGE
  end

  output_path = ARGV.shift || abort("Specify output path")
  strength = 1.0
  size = LUT_DEFAULT_SIZE

  ARGV.each do |arg|
    if arg =~ /--strength=([\d.]+)/
      strength = $1.to_f
    elsif arg =~ /--size=(\d+)/
      size = $1.to_i
    end
  end

  preset = load_preset(lut_type)
  title = preset['title']
  comments = (preset['comments'] || []) + ["Strength: #{strength}"]
  pipeline = preset['pipeline']

  puts "Generating #{lut_type} LUT..."

  table = generate_lut(size) do |r, g, b|
    apply_pipeline(r, g, b, pipeline, strength)
  end

  write_cube(output_path, table, size, title, comments)

  puts "Generated: #{output_path}"
  puts "LUT size: #{size}x#{size}x#{size}"
  puts "Strength: #{strength}"
  puts ""
  puts "Usage in DaVinci Resolve:"
  puts "  Add a node AFTER your main conversion LUT"
  puts "  Right-click node -> LUT -> Browse -> select this .cube file"
  puts ""
  puts "Usage in Premiere Pro:"
  puts "  Lumetri Color -> Creative -> Look dropdown -> Browse"
end

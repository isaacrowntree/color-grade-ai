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

# ── Transfer functions ───────────────────────────────────────────────
#
# Correction LUTs are applied to display-referred Rec.709 footage, after the
# camera's log->709 conversion. The matching decode is the BT.1886 display
# EOTF: a pure 2.4 power law. (Not the sRGB curve, which is a different
# standard for computer displays, and not the Rec.709 OETF, which is the
# camera-side encode.)
#
# Tone operations belong in linear light: doubling a linear value is doubling
# the light, whereas doubling a gamma-encoded value is not a meaningful
# photographic operation.

DISPLAY_GAMMA = 2.4

def to_linear(v)
  return 0.0 if v <= 0.0
  return 1.0 if v >= 1.0
  v ** DISPLAY_GAMMA
end

def from_linear(v)
  return 0.0 if v <= 0.0
  return 1.0 if v >= 1.0
  v ** (1.0 / DISPLAY_GAMMA)
end

# Rec.709 luminance coefficients — the same definition auto_grade.py measures
# with, so the analyzer and the generator describe the same quantity.
def luma_709(r, g, b)
  0.2126 * r + 0.7152 * g + 0.0722 * b
end

# Steps whose maths is tonal, and therefore belongs in linear light.
# Hue and saturation steps stay in HSL, where perceptual behaviour is what
# is actually wanted.
LINEAR_TONE_STEPS = %w[
  exposure
  black_crush
  highlight_protect
  skin_rolloff
  skin_highlight
].freeze

# Apply a tone curve to an image's luminance while preserving its chromaticity.
#
# The curve is expressed in the *encoded* domain (0-1, perceptually spaced) so
# that preset constants tuned against v1's HSL lightness remain meaningful.
# The resulting change is then applied as a scale in linear light, which keeps
# the ratios between R, G and B fixed — so hue and saturation come out
# unchanged by construction, instead of being quietly rewritten by hsl_to_rgb.
#
# Yields the current encoded luminance; expects the new encoded luminance back.
def apply_luma_curve(r, g, b)
  lin_r, lin_g, lin_b = to_linear(r), to_linear(g), to_linear(b)
  y_lin = luma_709(lin_r, lin_g, lin_b)

  new_y_enc = yield(from_linear(y_lin))
  new_y_lin = to_linear(new_y_enc)

  return [r, g, b] if (new_y_lin - y_lin).abs < 1e-12

  if y_lin <= 1e-12
    # Pure black has no chromaticity to preserve and cannot be scaled;
    # lift it as a neutral instead of dividing by zero.
    v = from_linear(new_y_lin)
    return [v, v, v]
  end

  scale = new_y_lin / y_lin
  sr, sg, sb = lin_r * scale, lin_g * scale, lin_b * scale

  # Brightening can push a saturated colour outside the cube. Clamping each
  # channel independently would skew the ratios and therefore the hue, which is
  # exactly what this function exists to avoid. Instead desaturate toward the
  # target luminance until the colour fits: that holds luminance exactly, keeps
  # the hue angle, and reads as a natural highlight rolloff.
  peak = [sr, sg, sb].max
  if peak > 1.0 && peak > new_y_lin
    k = (1.0 - new_y_lin) / (peak - new_y_lin)
    sr = new_y_lin + (sr - new_y_lin) * k
    sg = new_y_lin + (sg - new_y_lin) * k
    sb = new_y_lin + (sb - new_y_lin) * k
  end

  [
    from_linear(clamp(sr)),
    from_linear(clamp(sg)),
    from_linear(clamp(sb)),
  ]
end

# Recompute HSL state after a tone step so downstream hue/saturation steps see
# consistent values. orig_l is deliberately left alone: the luminance-window
# steps are tuned against it and are out of scope for the linear refactor.
def resync_state(r, g, b, st)
  h, s, l = rgb_to_hsl(r, g, b)
  st.merge(h: h, s: s, l: l)
end

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

def step_global_sat(r, g, b, st, cfg, strength)
  h, s, l = st[:h], st[:s], st[:l]
  boost = 1.0 + (cfg['boost'] - 1.0) * strength
  new_s = clamp(s * boost)
  r, g, b = hsl_to_rgb(h, new_s, l)
  [r, g, b, st.merge(s: new_s)]
end

# ── Linear-light tone steps (v2) ─────────────────────────────────────
#
# Same curves as their HSL counterparts above, but applied to luminance in
# linear light via apply_luma_curve, so chromaticity survives the operation.
# The legacy handlers are kept untouched so --legacy reproduces v1 exactly.

def step_exposure_linear(r, g, b, st, cfg, strength)
  gamma = 1.0 + (cfg['gamma'] - 1.0) * strength
  shadow_lift = cfg['shadow_lift'] * strength

  ro, go, bo = apply_luma_curve(r, g, b) do |y|
    lifted = y + shadow_lift * (1.0 - y)
    lifted ** gamma
  end

  [ro, go, bo, resync_state(ro, go, bo, st)]
end

def step_highlight_protect_linear(r, g, b, st, cfg, strength)
  knee_start = cfg['knee_start']
  knee_ceiling = cfg['knee_ceiling']

  ro, go, bo = apply_luma_curve(r, g, b) do |y|
    if y > knee_start
      over = (y - knee_start) / (1.0 - knee_start)
      knee_start + (knee_ceiling - knee_start) * (2.0 * over - over * over)
    else
      y
    end
  end

  [ro, go, bo, resync_state(ro, go, bo, st)]
end

def step_black_crush_linear(r, g, b, st, cfg, strength)
  black_threshold = cfg['black_threshold']
  crush_gamma = 1.0 + (cfg['crush_gamma'] - 1.0) * strength
  transition_end = cfg['transition_end']

  ro, go, bo = apply_luma_curve(r, g, b) do |y|
    if y < transition_end
      crushed = y ** crush_gamma
      if y < black_threshold
        crushed
      else
        t = (y - black_threshold) / (transition_end - black_threshold)
        t = t * t * (3.0 - 2.0 * t)
        crushed + (y - crushed) * t
      end
    else
      y
    end
  end

  [ro, go, bo, resync_state(ro, go, bo, st)]
end

def step_skin_rolloff_linear(r, g, b, st, cfg, strength)
  h, s = st[:h], st[:s]
  min_sat = cfg['min_sat'] || 0.03

  skin_str = s > min_sat ? hue_strength(h, cfg['skin_hue_center'],
                                        cfg['skin_hue_width'],
                                        cfg['skin_softness']) : 0.0
  return [r, g, b, st] if skin_str <= 0

  knee_start = cfg['knee_start']
  knee_ceiling = cfg['knee_ceiling']
  weight = skin_str * [s / 0.1, 1.0].min

  ro, go, bo = apply_luma_curve(r, g, b) do |y|
    if y > knee_start
      y + (soft_knee_rolloff(y, knee_start, knee_ceiling) - y) * weight
    else
      y
    end
  end

  [ro, go, bo, resync_state(ro, go, bo, st)]
end

def step_skin_highlight_linear(r, g, b, st, cfg, strength)
  h, s = st[:h], st[:s]

  skin_str = hue_strength(h, cfg['skin_hue_center'], cfg['skin_hue_width'],
                          cfg['skin_softness'])
  effective_skin = skin_str * [s / cfg['min_sat_ratio'], 1.0].min * strength

  knee_start = cfg['knee_start']
  global_knee = cfg['global_knee']

  # Captured inside the curve block so the desaturation matches the branch
  # that actually fired.
  hot_amount = nil

  ro, go, bo = apply_luma_curve(r, g, b) do |y|
    if y > knee_start && effective_skin > 0.1
      hot_amount = [(y - knee_start) / (1.0 - knee_start), 1.0].min
      target = soft_knee_rolloff(y, knee_start, cfg['knee_ceiling'])
      y + (target - y) * effective_skin
    elsif y > global_knee
      target = soft_knee_rolloff(y, global_knee, cfg['global_ceiling'])
      y + (target - y) * strength * (1.0 - effective_skin)
    else
      y
    end
  end

  state = resync_state(ro, go, bo, st)

  # Hot skin also loses saturation — that part stays an HSL operation.
  if hot_amount
    desat_factor = 1.0 - (1.0 - cfg['hot_desat']) * hot_amount * effective_skin
    new_s = state[:s] * desat_factor
    ro, go, bo = hsl_to_rgb(state[:h], new_s, state[:l])
    state = state.merge(s: new_s)
  end

  [ro, go, bo, state]
end

LINEAR_STEP_HANDLERS = {
  'exposure'          => method(:step_exposure_linear),
  'highlight_protect' => method(:step_highlight_protect_linear),
  'black_crush'       => method(:step_black_crush_linear),
  'skin_rolloff'      => method(:step_skin_rolloff_linear),
  'skin_highlight'    => method(:step_skin_highlight_linear),
}.freeze

STEP_HANDLERS = {
  'global_sat'           => method(:step_global_sat),
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

DEFAULT_COLOR_MODEL = :linear

# color_model: :linear (default, v2) routes tone steps through linear light.
#              :hsl               reproduces v1 exactly, for --legacy.
def apply_pipeline(r, g, b, pipeline, strength, color_model: DEFAULT_COLOR_MODEL)
  h, s, l = rgb_to_hsl(r, g, b)
  state = { h: h, s: s, l: l, orig_l: l }

  pipeline.each do |step_cfg|
    step_type = step_cfg['step']

    handler = if color_model == :linear && LINEAR_TONE_STEPS.include?(step_type)
                LINEAR_STEP_HANDLERS[step_type]
              else
                STEP_HANDLERS[step_type]
              end
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
        --legacy       Use the v1 HSL tone model instead of linear light
    USAGE
  end

  output_path = ARGV.shift || abort("Specify output path")
  strength = 1.0
  size = LUT_DEFAULT_SIZE
  color_model = DEFAULT_COLOR_MODEL

  ARGV.each do |arg|
    if arg =~ /--strength=([\d.]+)/
      strength = $1.to_f
    elsif arg =~ /--size=(\d+)/
      size = $1.to_i
    elsif arg == '--legacy'
      color_model = :hsl
    end
  end

  preset = load_preset(lut_type)
  title = preset['title']
  model_note = color_model == :linear ? 'linear-light tone (v2)' : 'legacy HSL tone (v1)'
  comments = (preset['comments'] || []) + ["Strength: #{strength}", "Color model: #{model_note}"]
  pipeline = preset['pipeline']

  puts "Generating #{lut_type} LUT..."

  table = generate_lut(size) do |r, g, b|
    apply_pipeline(r, g, b, pipeline, strength, color_model: color_model)
  end

  write_cube(output_path, table, size, title, comments)

  puts "Generated: #{output_path}"
  puts "LUT size: #{size}x#{size}x#{size}"
  puts "Strength: #{strength}"
  puts "Color model: #{model_note}"
  puts ""
  puts "Usage in DaVinci Resolve:"
  puts "  Add a node AFTER your main conversion LUT"
  puts "  Right-click node -> LUT -> Browse -> select this .cube file"
  puts ""
  puts "Usage in Premiere Pro:"
  puts "  Lumetri Color -> Creative -> Look dropdown -> Browse"
end

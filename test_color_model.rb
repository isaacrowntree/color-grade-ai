#!/usr/bin/env ruby
# test_color_model.rb - Tests for the linear-light tone pipeline (v2)
#
# v1 applied every tone operation to HSL lightness, L = (max + min) / 2, on
# gamma-encoded Rec.709 values. That is wrong in two ways:
#
#   1. HSL lightness is not luminance. A saturated red and a neutral grey that
#      look equally bright have very different L, so an exposure or black-crush
#      step moved them by different amounts — colours drifted relative to greys.
#   2. Rewriting L and converting back through hsl_to_rgb does not preserve
#      hue or saturation, so tone steps quietly shifted colour.
#
# v2 decodes to linear light, applies the tone curve to Rec.709 luma, and
# scales RGB by the resulting ratio. Hue and saturation are preserved by
# construction, and equal-luma colours move together.
#
# Run: ruby test_color_model.rb

require_relative 'generate_lut'

$pass = 0
$fail = 0

def assert(test_name, condition, message = "")
  if condition
    $pass += 1
    puts "  PASS: #{test_name}"
  else
    $fail += 1
    puts "  FAIL: #{test_name} — #{message}"
  end
end

def section(name)
  puts "\n=== #{name} ==="
end

def close?(a, b, tol)
  (a - b).abs <= tol
end

# Reference implementations the production code must agree with.
def ref_luma(r, g, b)
  0.2126 * r + 0.7152 * g + 0.0722 * b
end

# ── Test 1: Transfer functions ────────────────────────────────────────

section "Transfer Functions"

assert "to_linear(0) == 0", close?(to_linear(0.0), 0.0, 1e-12)
assert "to_linear(1) == 1", close?(to_linear(1.0), 1.0, 1e-12)
assert "from_linear(0) == 0", close?(from_linear(0.0), 0.0, 1e-12)
assert "from_linear(1) == 1", close?(from_linear(1.0), 1.0, 1e-12)

roundtrip_max = 0.0
(0..1000).each do |i|
  v = i / 1000.0
  d = (from_linear(to_linear(v)) - v).abs
  roundtrip_max = d if d > roundtrip_max
end
assert "encode/decode round-trips (max err=#{format('%.2e', roundtrip_max)})",
       roundtrip_max < 1e-9, "max error #{roundtrip_max}"

assert "to_linear is monotonic",
       (1..500).all? { |i| to_linear(i / 500.0) > to_linear((i - 1) / 500.0) }

assert "mid-grey decodes darker than it encodes (gamma > 1)",
       to_linear(0.5) < 0.5,
       "to_linear(0.5)=#{to_linear(0.5)}"

# 18% scene grey sits near code value 0.5 under a ~2.4 display gamma.
assert "linear 0.18 encodes near 0.5",
       close?(from_linear(0.18), 0.5, 0.03),
       "got #{from_linear(0.18)}"

# ── Test 2: Luma agrees with the analyzer ─────────────────────────────

section "Luma Definition"

# auto_grade.py measures Rec.709 luma. The generator must use the same
# definition or the analyzer's recommendations describe a different image
# than the one the LUT operates on.
[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0],
 [0.5, 0.5, 0.5], [0.2, 0.7, 0.4]].each do |r, g, b|
  assert "luma_709(#{r},#{g},#{b}) matches Rec.709 coefficients",
         close?(luma_709(r, g, b), ref_luma(r, g, b), 1e-12)
end

assert "luma of saturated red is far below its HSL lightness",
       luma_709(1.0, 0.0, 0.0) < 0.3 && rgb_to_hsl(1.0, 0.0, 0.0)[2] == 0.5,
       "this gap is the v1 bug"

# ── Test 3: Tone steps preserve hue and saturation ────────────────────

section "Tone Step Chromaticity"

TONE_PIPELINES = {
  'exposure'          => [{ 'step' => 'exposure', 'gamma' => 0.8, 'shadow_lift' => 0.1 }],
  'black_crush'       => [{ 'step' => 'black_crush', 'black_threshold' => 0.05,
                            'crush_gamma' => 1.4, 'transition_end' => 0.35 }],
  'highlight_protect' => [{ 'step' => 'highlight_protect', 'knee_start' => 0.7,
                            'knee_ceiling' => 0.9 }],
}.freeze

SAMPLE_COLOURS = [
  [0.8, 0.2, 0.2], [0.2, 0.6, 0.3], [0.3, 0.4, 0.9],
  [0.7, 0.6, 0.2], [0.45, 0.45, 0.45], [0.9, 0.5, 0.7],
].freeze

# Chromaticity is the ratio between the linear channels. A tone step scales all
# three by the same factor, so these ratios — and therefore hue and purity —
# must survive untouched. HSL's own S is not scale-invariant (its denominator
# depends on lightness), so it is the wrong yardstick here.
def chromaticity(r, g, b)
  lin = [to_linear(r), to_linear(g), to_linear(b)]
  peak = lin.max
  return [0.0, 0.0, 0.0] if peak <= 1e-12
  lin.map { |v| v / peak }
end

# Linear purity: 0 for a neutral, 1 for a fully saturated primary. Unlike HSL S
# this is invariant under a uniform scale.
def purity(r, g, b)
  lin = [to_linear(r), to_linear(g), to_linear(b)]
  return 0.0 if lin.max <= 1e-12
  1.0 - (lin.min / lin.max)
end

def clips_under?(r, g, b, pipeline)
  ro, go, bo = apply_pipeline(r, g, b, pipeline, 1.0, color_model: :linear)
  [ro, go, bo].max >= 1.0 - 1e-9
end

TONE_PIPELINES.each do |name, pipeline|
  max_hue_shift = 0.0
  max_chroma_shift = 0.0
  max_purity_gain = 0.0

  SAMPLE_COLOURS.each do |r, g, b|
    next if r == g && g == b # neutrals have undefined hue
    ro, go, bo = apply_pipeline(r, g, b, pipeline, 1.0, color_model: :linear)

    h_in, = rgb_to_hsl(r, g, b)
    h_out, = rgb_to_hsl(ro, go, bo)
    dh = (h_out - h_in).abs
    dh = 360.0 - dh if dh > 180.0
    max_hue_shift = dh if dh > max_hue_shift

    # Purity may legitimately FALL when a brightened colour is desaturated to
    # fit the cube. It must never rise — a tone step has no business adding
    # saturation.
    gain = purity(ro, go, bo) - purity(r, g, b)
    max_purity_gain = gain if gain > max_purity_gain

    next if clips_under?(r, g, b, pipeline)

    d = chromaticity(r, g, b).zip(chromaticity(ro, go, bo))
                             .map { |a, c| (a - c).abs }.max
    max_chroma_shift = d if d > max_chroma_shift
  end

  assert "#{name} preserves hue (max shift=#{format('%.4f', max_hue_shift)}°)",
         max_hue_shift < 3.0, "hue moved #{max_hue_shift}°"
  assert "#{name} preserves chromaticity in gamut " \
         "(max shift=#{format('%.2e', max_chroma_shift)})",
         max_chroma_shift < 1e-9, "chromaticity moved #{max_chroma_shift}"
  assert "#{name} never adds saturation (max gain=#{format('%.2e', max_purity_gain)})",
         max_purity_gain < 1e-9, "purity rose by #{max_purity_gain}"
end

# The legacy model fails the chromaticity invariant — proving the fix is real.
#
# Note hsl_to_rgb is proportional in L below 0.5, so v1 happens to be harmless
# in deep shadow. The damage shows in midtones and highlights, where HSL
# switches to its q = l + s - ls branch. Compare there, with a darkening curve
# so nothing clips and the comparison is clean.
MIDTONE_COLOURS = [[0.90, 0.50, 0.50], [0.60, 0.82, 0.70],
                   [0.85, 0.75, 0.40], [0.55, 0.62, 0.88]].freeze
DARKEN = [{ 'step' => 'exposure', 'gamma' => 1.3, 'shadow_lift' => 0.0 }].freeze

legacy_chroma_shift = 0.0
linear_chroma_shift = 0.0
MIDTONE_COLOURS.each do |r, g, b|
  legacy = apply_pipeline(r, g, b, DARKEN, 1.0, color_model: :hsl)
  lin = apply_pipeline(r, g, b, DARKEN, 1.0, color_model: :linear)
  base = chromaticity(r, g, b)
  dl = base.zip(chromaticity(*legacy)).map { |a, c| (a - c).abs }.max
  dn = base.zip(chromaticity(*lin)).map { |a, c| (a - c).abs }.max
  legacy_chroma_shift = dl if dl > legacy_chroma_shift
  linear_chroma_shift = dn if dn > linear_chroma_shift
end

assert "legacy HSL model shifts chromaticity (max=#{format('%.4f', legacy_chroma_shift)})",
       legacy_chroma_shift > 1e-4,
       "expected v1 to distort chromaticity; got #{legacy_chroma_shift}"
assert "linear model holds chromaticity on the same colours " \
       "(#{format('%.2e', linear_chroma_shift)} vs #{format('%.4f', legacy_chroma_shift)})",
       linear_chroma_shift < 1e-9,
       "linear model shifted chromaticity by #{linear_chroma_shift}"

# ── Test 4: Equal-luma colours move together ──────────────────────────

section "Luma Consistency"

# The headline v1 defect: a saturated colour and a neutral of the same
# luminance should receive the same tonal treatment.
pipeline = TONE_PIPELINES['exposure']

# Build a saturated colour and a grey of the same *luminance* — that is, equal
# linear-light Rec.709 luma, which is what "equally bright" physically means.
def linear_luma(r, g, b)
  luma_709(to_linear(r), to_linear(g), to_linear(b))
end

sat_colour = [0.55, 0.2, 0.2]
target_luma = linear_luma(*sat_colour)
grey_code = from_linear(target_luma)
grey = [grey_code, grey_code, grey_code]

sat_out = apply_pipeline(*sat_colour, pipeline, 1.0, color_model: :linear)
grey_out = apply_pipeline(*grey, pipeline, 1.0, color_model: :linear)

sat_ratio = linear_luma(*sat_out) / linear_luma(*sat_colour)
grey_ratio = linear_luma(*grey_out) / linear_luma(*grey)

assert "equal-luma colour and grey receive the same luma gain " \
       "(#{format('%.4f', sat_ratio)} vs #{format('%.4f', grey_ratio)})",
       close?(sat_ratio, grey_ratio, 0.01),
       "ratios differ by #{(sat_ratio - grey_ratio).abs}"

# And prove the legacy model genuinely fails this — otherwise the fix is a no-op.
sat_out_l = apply_pipeline(*sat_colour, pipeline, 1.0, color_model: :hsl)
grey_out_l = apply_pipeline(*grey, pipeline, 1.0, color_model: :hsl)
legacy_gap = ((linear_luma(*sat_out_l) / linear_luma(*sat_colour)) -
              (linear_luma(*grey_out_l) / linear_luma(*grey))).abs

assert "legacy HSL model fails the same check (gap=#{format('%.4f', legacy_gap)})",
       legacy_gap > 0.01,
       "expected the v1 model to diverge; got #{legacy_gap}"

# ── Test 5: Monotonicity and range ────────────────────────────────────

section "Tone Curve Sanity"

TONE_PIPELINES.each do |name, pipeline|
  prev = -1.0
  monotonic = true
  in_range = true

  (0..200).each do |i|
    v = i / 200.0
    ro, go, bo = apply_pipeline(v, v, v, pipeline, 1.0, color_model: :linear)
    y = luma_709(ro, go, bo)
    monotonic = false if y < prev - 1e-9
    in_range = false if y < -1e-9 || y > 1.0 + 1e-9
    prev = y
  end

  assert "#{name} is monotonic on the neutral ramp", monotonic
  assert "#{name} stays in [0,1] on the neutral ramp", in_range
end

# black_crush has no lift term, so black must survive it untouched.
assert "pure black stays black under black_crush",
       apply_pipeline(0.0, 0.0, 0.0, TONE_PIPELINES['black_crush'], 1.0,
                      color_model: :linear).all? { |v| v.abs < 1e-9 }

# exposure's shadow_lift deliberately raises black — but it must do so as a
# neutral, not with a colour cast.
lifted = apply_pipeline(0.0, 0.0, 0.0, TONE_PIPELINES['exposure'], 1.0,
                        color_model: :linear)
assert "shadow_lift raises black neutrally (#{lifted.map { |v| format('%.4f', v) }.join(', ')})",
       lifted.max - lifted.min < 1e-9 && lifted.max > 0.0,
       "lifted black is not neutral: #{lifted.inspect}"

# ── Test 6: Identity at strength 0 ────────────────────────────────────

section "Identity at Strength 0"

presets = load_presets
%w[yellow_fix red_skin_fix black_crush sat_boost warm_shift].each do |name|
  preset = presets[name]
  next unless preset
  next if preset['pipeline'].any? { |s| s['step'] == 'highlight_protect' }

  max_diff = 0.0
  [[0.1, 0.2, 0.3], [0.5, 0.5, 0.5], [0.9, 0.4, 0.2], [0.0, 0.0, 0.0]].each do |r, g, b|
    ro, go, bo = apply_pipeline(r, g, b, preset['pipeline'], 0.0, color_model: :linear)
    d = [(r - ro).abs, (g - go).abs, (b - bo).abs].max
    max_diff = d if d > max_diff
  end

  assert "#{name} is identity at strength 0 in linear mode " \
         "(max_diff=#{format('%.2e', max_diff)})",
         max_diff < 1e-9, "max_diff=#{max_diff}"
end

# ── Test 7: Legacy mode is byte-for-byte v1 ───────────────────────────

section "Legacy Escape Hatch"

require 'digest'
require 'fileutils'

legacy_baseline_path = File.join(__dir__, 'reference_checksums_legacy.yml')
assert "frozen v1 baseline is committed", File.exist?(legacy_baseline_path)

if File.exist?(legacy_baseline_path)
  legacy_baseline = YAML.load_file(legacy_baseline_path)
  tmp_dir = File.join(__dir__, 'tmp', 'legacy_check')
  FileUtils.mkdir_p(tmp_dir)

  mismatches = []
  presets.each_key do |name|
    expected = legacy_baseline[name]
    next unless expected

    table = generate_lut(33) do |r, g, b|
      apply_pipeline(r, g, b, presets[name]['pipeline'], 1.0, color_model: :hsl)
    end
    path = File.join(tmp_dir, "#{name}.cube")
    write_cube(path, table, 33, presets[name]['title'], [])
    data = File.readlines(path).select { |l| l =~ /^\d/ }.join
    mismatches << name if Digest::SHA256.hexdigest(data) != expected
  end

  assert "--legacy reproduces every v1 LUT exactly", mismatches.empty?,
         "changed: #{mismatches.join(', ')}"
end

# ── Test 8: Linear mode actually differs ──────────────────────────────

section "v2 Differs From v1"

changed = 0
presets.each_key do |name|
  pipeline = presets[name]['pipeline']
  next unless pipeline.any? { |s| LINEAR_TONE_STEPS.include?(s['step']) }

  differs = SAMPLE_COLOURS.any? do |r, g, b|
    a = apply_pipeline(r, g, b, pipeline, 1.0, color_model: :hsl)
    c = apply_pipeline(r, g, b, pipeline, 1.0, color_model: :linear)
    a.zip(c).any? { |x, y| (x - y).abs > 1e-4 }
  end
  changed += 1 if differs
end

assert "linear mode changes output for tone-bearing presets (#{changed} presets)",
       changed > 0, "no preset changed — the refactor is a no-op"

# ── Test 9: Neutrals are untouched by the refactor ───────────────────

section "Neutral Axis Invariance"

# For a neutral, encoded luminance equals the code value, which is exactly what
# HSL lightness was. So v1 and v2 must agree bit-for-bit on the grey axis: the
# refactor moves saturated colours only. If this ever fails, the tone curves
# themselves have changed, not just the space they are applied in.
# Presets that tint before they tone (rgb_rebalance) are excluded: their input
# is no longer neutral by the time the tone step runs, so there is no grey axis
# left to preserve.
tone_presets = presets.select do |_, p|
  p['pipeline'].any? { |s| LINEAR_TONE_STEPS.include?(s['step']) } &&
    p['pipeline'].none? { |s| s['step'] == 'rgb_rebalance' }
end

tone_presets.each do |name, preset|
  max_diff = 0.0
  (0..64).each do |i|
    v = i / 64.0
    legacy = apply_pipeline(v, v, v, preset['pipeline'], 1.0, color_model: :hsl)
    lin = apply_pipeline(v, v, v, preset['pipeline'], 1.0, color_model: :linear)
    d = legacy.zip(lin).map { |a, b| (a - b).abs }.max
    max_diff = d if d > max_diff
  end

  assert "#{name} is unchanged on the neutral axis " \
         "(max_diff=#{format('%.2e', max_diff)})",
         max_diff < 1e-9, "greys moved by #{max_diff}"
end

# ── Summary ───────────────────────────────────────────────────────────

puts "\n#{'=' * 50}"
puts "Results: #{$pass} passed, #{$fail} failed"
puts "#{'=' * 50}"

exit($fail > 0 ? 1 : 0)

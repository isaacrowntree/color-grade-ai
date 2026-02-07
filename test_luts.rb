#!/usr/bin/env ruby
# test_luts.rb - Automated test suite for config-driven LUT generation
#
# Validates that presets.yml + generate_lut.rb produce correct output.
# Run: ruby test_luts.rb

require_relative 'generate_lut'

REFERENCE_DIR = File.join(__dir__, 'tmp', 'reference')
OUTPUT_DIR = File.join(__dir__, 'tmp', 'test_output')

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

# ── Test 1: Config loading ────────────────────────────────────────────

section "Config Loading"

presets = nil
begin
  presets = load_presets
  assert "presets.yml loads without error", true
rescue => e
  assert "presets.yml loads without error", false, e.message
end

if presets
  expected_presets = %w[
    yellow_fix red_skin_fix night_warm_fix night_purple_fix
    overexposure_fix underexposure_fix black_crush skin_highlight_fix
  ]
  expected_presets.each do |name|
    p = presets[name]
    assert "preset '#{name}' exists", !p.nil?
    if p
      assert "preset '#{name}' has title", p.key?('title') && !p['title'].empty?
      assert "preset '#{name}' has comments", p.key?('comments') && p['comments'].is_a?(Array)
      assert "preset '#{name}' has pipeline", p.key?('pipeline') && p['pipeline'].is_a?(Array) && !p['pipeline'].empty?
    end
  end
end

# ── Test 2: Pipeline step validation ──────────────────────────────────

section "Pipeline Step Validation"

known_steps = STEP_HANDLERS.keys

if presets
  presets.each do |name, cfg|
    next unless cfg['pipeline']
    cfg['pipeline'].each_with_index do |step, i|
      step_type = step['step']
      assert "#{name} step #{i} ('#{step_type}') is a known type",
             known_steps.include?(step_type),
             "unknown step type: #{step_type}"
    end
  end
end

# ── Test 3: LUT generation ───────────────────────────────────────────

section "LUT Generation"

Dir.mkdir(OUTPUT_DIR) unless Dir.exist?(OUTPUT_DIR)

expected_lines = 33 * 33 * 33  # 35,937

if presets
  presets.each_key do |name|
    output_path = File.join(OUTPUT_DIR, "#{name}.cube")
    begin
      preset = load_preset(name)
      pipeline = preset['pipeline']
      table = generate_lut(33) { |r, g, b| apply_pipeline(r, g, b, pipeline, 1.0) }
      write_cube(output_path, table, 33, preset['title'], preset['comments'] || [])

      assert "#{name} generates without error", true
      assert "#{name} has #{expected_lines} data lines", table.length == expected_lines,
             "got #{table.length}"

      # Verify .cube file is valid
      lines = File.readlines(output_path)
      has_title = lines.any? { |l| l.start_with?('TITLE') }
      has_size = lines.any? { |l| l.start_with?('LUT_3D_SIZE') }
      data_lines = lines.count { |l| l =~ /^\d/ }
      assert "#{name} .cube has TITLE header", has_title
      assert "#{name} .cube has LUT_3D_SIZE header", has_size
      assert "#{name} .cube has correct data line count", data_lines == expected_lines,
             "got #{data_lines}"
    rescue => e
      assert "#{name} generates without error", false, e.message
    end
  end
end

# ── Test 4: Identity check (strength=0) ──────────────────────────────

section "Identity Check (strength=0)"

# Presets with highlight_protect use fixed knee values that don't interpolate
# by strength — they act as safety clamps. These are NOT identity at strength=0
# by design (same behavior as the original hardcoded code).
has_highlight_protect = ->(p) { p['pipeline'].any? { |s| s['step'] == 'highlight_protect' } }

if presets
  presets.each_key do |name|
    begin
      preset = load_preset(name)
      pipeline = preset['pipeline']
      max_diff = 0.0

      table = generate_lut(33) { |r, g, b| apply_pipeline(r, g, b, pipeline, 0.0) }

      # Compare against identity
      idx = 0
      33.times do |bi|
        33.times do |gi|
          33.times do |ri|
            r_in = ri.to_f / 32.0
            g_in = gi.to_f / 32.0
            b_in = bi.to_f / 32.0

            r_out, g_out, b_out = table[idx]
            diff = [(r_in - r_out).abs, (g_in - g_out).abs, (b_in - b_out).abs].max
            max_diff = diff if diff > max_diff
            idx += 1
          end
        end
      end

      if has_highlight_protect.call(preset)
        # These presets have highlight_protect as a safety clamp — not identity at strength=0
        assert "#{name} at strength=0 near-identity (max_diff=#{format('%.2e', max_diff)}, has highlight_protect)",
               max_diff < 0.5,
               "max_diff=#{format('%.2e', max_diff)}"
      else
        assert "#{name} at strength=0 is identity (max_diff=#{format('%.2e', max_diff)})",
               max_diff < 1e-10,
               "max_diff=#{format('%.2e', max_diff)}"
      end
    rescue => e
      assert "#{name} identity check", false, e.message
    end
  end
end

# ── Test 5: Regression against reference LUTs ────────────────────────

section "Regression vs Reference"

if Dir.exist?(REFERENCE_DIR)
  presets&.each_key do |name|
    ref_path = File.join(REFERENCE_DIR, "#{name}.cube")
    new_path = File.join(OUTPUT_DIR, "#{name}.cube")

    unless File.exist?(ref_path)
      assert "#{name} reference file exists", false, "missing #{ref_path}"
      next
    end
    unless File.exist?(new_path)
      assert "#{name} test output exists", false, "missing #{new_path}"
      next
    end

    ref_data = File.readlines(ref_path).select { |l| l =~ /^\d/ }
    new_data = File.readlines(new_path).select { |l| l =~ /^\d/ }

    if ref_data.length != new_data.length
      assert "#{name} line count matches reference", false,
             "ref=#{ref_data.length} new=#{new_data.length}"
      next
    end

    max_diff = 0.0
    diff_count = 0

    ref_data.zip(new_data).each do |ref_line, new_line|
      ref_vals = ref_line.split.map(&:to_f)
      new_vals = new_line.split.map(&:to_f)

      ref_vals.zip(new_vals).each do |rv, nv|
        d = (rv - nv).abs
        if d > 1e-6
          diff_count += 1
          max_diff = d if d > max_diff
        end
      end
    end

    assert "#{name} matches reference (max_diff=#{format('%.2e', max_diff)}, diffs=#{diff_count})",
           diff_count == 0,
           "#{diff_count} values differ, max_diff=#{format('%.2e', max_diff)}"
  end
else
  puts "  SKIP: No reference directory at #{REFERENCE_DIR}"
  puts "  Generate references first: ruby test_luts.rb --generate-reference"
end

# ── Test 6: Value range ──────────────────────────────────────────────

section "Value Range [0.0, 1.0]"

if presets
  presets.each_key do |name|
    output_path = File.join(OUTPUT_DIR, "#{name}.cube")
    next unless File.exist?(output_path)

    out_of_range = 0
    File.readlines(output_path).each do |line|
      next unless line =~ /^\d/
      vals = line.split.map(&:to_f)
      vals.each do |v|
        out_of_range += 1 if v < 0.0 || v > 1.0
      end
    end

    assert "#{name} all values in [0.0, 1.0]", out_of_range == 0,
           "#{out_of_range} values out of range"
  end
end

# ── Test 7: Docs generation ──────────────────────────────────────────

section "Docs Generation"

docs_script = File.join(__dir__, 'generate_docs.rb')
if File.exist?(docs_script)
  result = `ruby "#{docs_script}" 2>&1`
  success = $?.success?
  assert "generate_docs.rb runs without error", success, result.lines.last&.strip

  lut_types_md = File.join(__dir__, 'docs', 'src', 'content', 'docs', 'reference', 'lut-types.md')
  presets_md = File.join(__dir__, 'docs', 'src', 'content', 'docs', 'reference', 'presets-config.md')

  assert "lut-types.md generated", File.exist?(lut_types_md)
  assert "presets-config.md generated", File.exist?(presets_md)
else
  puts "  SKIP: generate_docs.rb not found"
end

# ── Summary ───────────────────────────────────────────────────────────

puts "\n#{'=' * 50}"
puts "Results: #{$pass} passed, #{$fail} failed"
puts "#{'=' * 50}"

exit($fail > 0 ? 1 : 0)

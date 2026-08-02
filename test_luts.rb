#!/usr/bin/env ruby
# test_luts.rb - Automated test suite for config-driven LUT generation
#
# Validates that presets.yml + generate_lut.rb produce correct output.
# Run: ruby test_luts.rb

require 'fileutils'
require_relative 'generate_lut'

OUTPUT_DIR = File.join(__dir__, 'tmp', 'test_output')

# Golden-file regression baseline. Storing a SHA256 per preset rather than the
# .cube files themselves keeps the baseline at a few KB instead of 25 MB while
# still catching any unintended change to the colour maths.
#
# Regenerate deliberately (and review the diff) with:
#   ruby test_luts.rb --generate-reference
REFERENCE_PATH = File.join(__dir__, 'reference_checksums.yml')

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

# mkdir_p, not mkdir: tmp/ is gitignored, so on a fresh clone the parent
# directory does not exist and a non-recursive mkdir aborts the whole suite.
FileUtils.mkdir_p(OUTPUT_DIR)

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

# Checksum the numeric data lines only, so a title or comment edit does not
# read as a colour-maths regression.
def lut_digest(path)
  require 'digest'
  data = File.readlines(path).select { |l| l =~ /^\d/ }.join
  Digest::SHA256.hexdigest(data)
end

if ARGV.include?('--generate-reference')
  baseline = {}
  presets&.each_key do |name|
    path = File.join(OUTPUT_DIR, "#{name}.cube")
    baseline[name] = lut_digest(path) if File.exist?(path)
  end
  File.write(REFERENCE_PATH, baseline.to_yaml)
  puts "  Wrote #{baseline.length} checksums to #{REFERENCE_PATH}"
  puts "  Review the diff before committing."
elsif File.exist?(REFERENCE_PATH)
  reference = YAML.load_file(REFERENCE_PATH)

  assert "reference baseline covers every preset",
         (presets.keys - reference.keys).empty?,
         "missing baseline for: #{(presets.keys - reference.keys).join(', ')}"

  assert "reference baseline has no stale entries",
         (reference.keys - presets.keys).empty?,
         "baseline references removed presets: #{(reference.keys - presets.keys).join(', ')}"

  presets&.each_key do |name|
    new_path = File.join(OUTPUT_DIR, "#{name}.cube")
    expected = reference[name]

    unless File.exist?(new_path)
      assert "#{name} test output exists", false, "missing #{new_path}"
      next
    end
    next unless expected

    actual = lut_digest(new_path)
    assert "#{name} output matches reference checksum", actual == expected,
           "expected #{expected[0, 12]}… got #{actual[0, 12]}… " \
           "(run `ruby test_luts.rb --generate-reference` if intentional)"
  end
else
  assert "reference checksum baseline exists", false,
         "missing #{REFERENCE_PATH} — run `ruby test_luts.rb --generate-reference`"
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

  # The docs site is a single page generated from SKILL.md (see commit e8a4dc0).
  index_md = File.join(__dir__, 'docs', 'src', 'content', 'docs', 'index.md')
  assert "docs index.md generated", File.exist?(index_md)

  if File.exist?(index_md)
    generated = File.read(index_md)

    assert "index.md has Starlight frontmatter",
           generated.start_with?("---\n") && generated.match?(/^title:\s*\S/)

    # Skill-only frontmatter keys must not leak into the published site.
    header = generated.split("---\n")[1].to_s
    assert "index.md strips skill frontmatter",
           !header.include?('allowed-tools') && !header.include?('argument-hint'),
           "skill frontmatter leaked into docs"

    # The page must actually carry the SKILL.md body, not just a header.
    skill_body = File.read(File.join(__dir__, 'SKILL.md')).split("---\n", 3).last.to_s
    first_heading = skill_body[/^#\s+.+$/]
    assert "index.md carries the SKILL.md body",
           first_heading && generated.include?(first_heading),
           "expected #{first_heading.inspect} in generated page"

    assert "index.md is not truncated",
           generated.length > skill_body.length * 0.9,
           "generated #{generated.length} chars from #{skill_body.length} chars of source"
  end
else
  puts "  SKIP: generate_docs.rb not found"
end

# ── Test 8: Shipped LUTs match their manifest ────────────────────────

section "Shipped LUTs"

manifest_path = File.join(__dir__, 'correction_luts', 'manifest.yml')
assert "correction_luts/manifest.yml exists", File.exist?(manifest_path)

if File.exist?(manifest_path)
  manifest = YAML.load_file(manifest_path)

  shipped = Dir.glob(File.join(__dir__, 'correction_luts', '*.cube'))
               .map { |p| File.basename(p, '.cube') }.sort
  assert "manifest covers every shipped LUT",
         (shipped - manifest.keys).empty?,
         "unlisted: #{(shipped - manifest.keys).join(', ')}"
  assert "manifest has no entries without a file",
         (manifest.keys - shipped).empty?,
         "missing files: #{(manifest.keys - shipped).join(', ')}"

  # The committed .cube files must be exactly what regenerate_luts.rb produces,
  # so they can never silently drift from presets.yml.
  regen = File.join(__dir__, 'regenerate_luts.rb')
  output = `ruby "#{regen}" --check 2>&1`
  assert "shipped LUTs match the current tone model", $?.success?,
         output.lines.map(&:strip).reject(&:empty?).last
end

# ── Summary ───────────────────────────────────────────────────────────

puts "\n#{'=' * 50}"
puts "Results: #{$pass} passed, #{$fail} failed"
puts "#{'=' * 50}"

exit($fail > 0 ? 1 : 0)

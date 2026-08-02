#!/usr/bin/env ruby
# test_repo_hygiene.rb - Repository hygiene checks
#
# Guards the things that break a fresh clone or confuse a first-time user:
# line endings, executable bits, skill/plugin manifests, and CI wiring.
#
# Run: ruby test_repo_hygiene.rb

require 'json'

ROOT = __dir__

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

def tracked_files
  @tracked_files ||= `git -C "#{ROOT}" ls-files -z`.split("\0")
end

TEXT_EXTENSIONS = %w[.rb .py .md .yml .yaml .html .json .mjs .ts .js].freeze

def text_files
  tracked_files.select { |f| TEXT_EXTENSIONS.include?(File.extname(f)) }
end

# ── Test 1: Line endings ──────────────────────────────────────────────

section "Line Endings"

crlf = text_files.select do |f|
  path = File.join(ROOT, f)
  File.exist?(path) && File.binread(path).include?("\r\n")
end

assert "no tracked text file uses CRLF line endings", crlf.empty?,
       "CRLF in: #{crlf.join(', ')}"

gitattributes = File.join(ROOT, '.gitattributes')
assert ".gitattributes exists", File.exist?(gitattributes)
if File.exist?(gitattributes)
  contents = File.read(gitattributes)
  assert ".gitattributes normalises text line endings",
         contents.include?('text=auto'),
         "expected a `* text=auto` rule"
  assert ".gitattributes forces LF on shell/ruby/python scripts",
         contents.match?(/\*\.rb\s+text\s+eol=lf/) &&
         contents.match?(/\*\.py\s+text\s+eol=lf/),
         "expected eol=lf rules for *.rb and *.py"
end

# ── Test 2: Executable bits ───────────────────────────────────────────

section "Executable Bits"

scripts = tracked_files.select { |f| %w[.rb .py].include?(File.extname(f)) }
non_exec = scripts.select do |f|
  path = File.join(ROOT, f)
  next false unless File.exist?(path)
  first = File.open(path, &:readline) rescue ''
  first.start_with?('#!') && !File.executable?(path)
end

assert "every script with a shebang is executable", non_exec.empty?,
       "not executable: #{non_exec.join(', ')}"

# ── Test 3: Skill manifest ────────────────────────────────────────────

section "Skill Manifest"

skill_files = tracked_files.select { |f| File.basename(f) == 'SKILL.md' }

assert "exactly one SKILL.md is tracked", skill_files.length == 1,
       "found #{skill_files.length}: #{skill_files.join(', ')}"
assert "SKILL.md lives at the repository root",
       skill_files.include?('SKILL.md'),
       "found at: #{skill_files.join(', ')}"

skill_path = File.join(ROOT, 'SKILL.md')
frontmatter = nil
if File.exist?(skill_path)
  body = File.read(skill_path)
  if body.start_with?("---\n")
    frontmatter = body.split("---\n")[1].to_s
  end
  assert "SKILL.md has YAML frontmatter", !frontmatter.nil?

  if frontmatter
    name = frontmatter[/^name:\s*(\S+)/, 1]
    assert "SKILL.md declares name: color-grade", name == 'color-grade',
           "got #{name.inspect}"
    assert "SKILL.md declares a description",
           frontmatter.match?(/^description:\s*\S/)
    assert "SKILL.md declares allowed-tools",
           frontmatter.match?(/^allowed-tools:\s*\S/)
  end
end

assert "no stale nested skill directory under .claude/",
       tracked_files.none? { |f| f.start_with?('.claude/skills/') },
       "tracked: #{tracked_files.select { |f| f.start_with?('.claude/skills/') }.join(', ')}"

# ── Test 4: Plugin manifest ───────────────────────────────────────────

section "Plugin Manifest"

plugin_path = File.join(ROOT, '.claude-plugin', 'plugin.json')
assert ".claude-plugin/plugin.json exists", File.exist?(plugin_path)

if File.exist?(plugin_path)
  manifest = nil
  begin
    manifest = JSON.parse(File.read(plugin_path))
    assert "plugin.json is valid JSON", true
  rescue JSON::ParserError => e
    assert "plugin.json is valid JSON", false, e.message
  end

  if manifest
    %w[name description version author].each do |key|
      assert "plugin.json has #{key}", manifest.key?(key) && !manifest[key].to_s.empty?
    end
    assert "plugin.json name matches the skill name",
           manifest['name'] == 'color-grade-ai',
           "got #{manifest['name'].inspect}"
    assert "plugin.json version is semver",
           manifest['version'].to_s.match?(/^\d+\.\d+\.\d+$/),
           "got #{manifest['version'].inspect}"
  end
end

# ── Test 5: CI wiring ─────────────────────────────────────────────────

section "CI Wiring"

workflow_dir = File.join(ROOT, '.github', 'workflows')
workflows = Dir.exist?(workflow_dir) ? Dir.children(workflow_dir) : []
all_workflow_text = workflows.map { |w| File.read(File.join(workflow_dir, w)) }.join("\n")

assert "a CI workflow runs test_luts.rb",
       all_workflow_text.include?('test_luts.rb')
assert "a CI workflow runs test_auto_grade.py",
       all_workflow_text.include?('test_auto_grade.py')
assert "a CI workflow runs test_repo_hygiene.rb",
       all_workflow_text.include?('test_repo_hygiene.rb')
assert "a CI workflow runs test_color_model.rb",
       all_workflow_text.include?('test_color_model.rb')

# ── Test 5b: Version and baselines ────────────────────────────────────

section "Versioning"

assert "the frozen v1 baseline is committed for --legacy",
       File.exist?(File.join(ROOT, 'reference_checksums_legacy.yml'))

if File.exist?(plugin_path) && manifest
  assert "plugin version is 2.x now that the tone model changed",
         manifest['version'].to_s.start_with?('2.'),
         "got #{manifest['version'].inspect}"
end

# ── Test 6: Documentation accuracy ────────────────────────────────────

section "Documentation Accuracy"

require 'yaml'
presets = YAML.load_file(File.join(ROOT, 'presets.yml'))
readme = File.read(File.join(ROOT, 'README.md'))

# Any `ruby generate_lut.rb <name>` invocation in the README must name a real preset.
readme_presets = readme.scan(/generate_lut\.rb\s+(\w+)/).flatten.uniq
readme_presets.each do |name|
  assert "README example preset '#{name}' exists in presets.yml",
         presets.key?(name)
end

skill_body = File.exist?(skill_path) ? File.read(skill_path) : ''
skill_presets = skill_body.scan(/generate_lut\.rb\s+(\w+)/).flatten.uniq
skill_presets.reject { |n| n == '<type>' }.each do |name|
  next if name.start_with?('<')
  assert "SKILL.md example preset '#{name}' exists in presets.yml",
         presets.key?(name)
end

# The generator's own usage comment lists presets — they must exist too.
gen_header = File.read(File.join(ROOT, 'generate_lut.rb'))[0, 2000]
documented = gen_header.scan(/^#\s{3}(\w+)\s+-\s/).flatten
documented.each do |name|
  assert "generate_lut.rb header preset '#{name}' exists in presets.yml",
         presets.key?(name)
end

# ── Test 7: Pre-baked LUT pack ────────────────────────────────────────

section "Pre-baked LUT Pack"

lut_dir = File.join(ROOT, 'correction_luts')
assert "correction_luts/ is present for download-only users", Dir.exist?(lut_dir)

if Dir.exist?(lut_dir)
  cubes = Dir.children(lut_dir).select { |f| f.end_with?('.cube') }
  assert "correction_luts/ contains .cube files", !cubes.empty?

  malformed = cubes.reject do |f|
    head = File.foreach(File.join(lut_dir, f)).first(20).join
    head.include?('TITLE') && head.include?('LUT_3D_SIZE')
  end
  assert "every shipped .cube has TITLE and LUT_3D_SIZE headers",
         malformed.empty?, "malformed: #{malformed.join(', ')}"
end

# ── Summary ───────────────────────────────────────────────────────────

puts "\n#{'=' * 50}"
puts "Results: #{$pass} passed, #{$fail} failed"
puts "#{'=' * 50}"

exit($fail > 0 ? 1 : 0)

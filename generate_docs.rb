#!/usr/bin/env ruby
# generate_docs.rb - Generate single-page Starlight docs from SKILL.md
#
# Reads SKILL.md (the source of truth), strips skill frontmatter,
# and writes a single Starlight-compatible docs page.
#
# Run: ruby generate_docs.rb

SKILL_PATH = File.join(__dir__, 'SKILL.md')
DOCS_DIR = File.join(__dir__, 'docs', 'src', 'content', 'docs')
OUTPUT_PATH = File.join(DOCS_DIR, 'index.md')

skill_content = File.read(SKILL_PATH)

# Strip SKILL.md frontmatter (name, description, argument-hint, allowed-tools)
if skill_content.start_with?('---')
  _frontmatter, body = skill_content.split('---', 3)[1..2]
  body = body.lstrip
else
  body = skill_content
end

# Write Starlight-compatible page
starlight_frontmatter = <<~FRONTMATTER
  ---
  title: color-grade-ai
  description: AI-powered .cube LUT generation for color correction in DaVinci Resolve and Adobe Premiere Pro
  ---
FRONTMATTER

File.open(OUTPUT_PATH, 'w') do |f|
  f.write(starlight_frontmatter)
  f.write("\n")
  f.write(body)
end

puts "Generated: #{OUTPUT_PATH}"
puts "Source: #{SKILL_PATH}"

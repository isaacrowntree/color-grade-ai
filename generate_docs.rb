#!/usr/bin/env ruby
# generate_docs.rb - Generate single-page Starlight docs from SKILL.md
#
# Reads SKILL.md (the source of truth), strips skill frontmatter,
# and writes a single Starlight-compatible docs page.
#
# Usage:
#   ruby generate_docs.rb           # write the page
#   ruby generate_docs.rb --check   # fail if the committed page is stale
#
# The --check mode exists because the published site is what users actually
# read. Regenerating in CI and then asserting on the freshly written file would
# pass even when the committed page had drifted from SKILL.md, so the committed
# state is verified before anything is rewritten.

SKILL_PATH = File.join(__dir__, 'SKILL.md')
DOCS_DIR = File.join(__dir__, 'docs', 'src', 'content', 'docs')
OUTPUT_PATH = File.join(DOCS_DIR, 'index.md')

STARLIGHT_FRONTMATTER = <<~FRONTMATTER
  ---
  title: color-grade-ai
  description: AI-powered .cube LUT generation for color correction in DaVinci Resolve and Adobe Premiere Pro
  ---
FRONTMATTER

def render
  skill_content = File.read(SKILL_PATH)

  # Strip SKILL.md frontmatter (name, description, argument-hint, allowed-tools)
  if skill_content.start_with?('---')
    _frontmatter, body = skill_content.split('---', 3)[1..2]
    body = body.lstrip
  else
    body = skill_content
  end

  STARLIGHT_FRONTMATTER + "\n" + body
end

if __FILE__ == $0
  generated = render

  if ARGV.include?('--check')
    unless File.exist?(OUTPUT_PATH)
      warn "Missing #{OUTPUT_PATH} — run: ruby generate_docs.rb"
      exit 1
    end

    if File.read(OUTPUT_PATH) == generated
      puts "Docs are in sync with SKILL.md."
    else
      warn "#{OUTPUT_PATH} is stale — SKILL.md has changed since it was generated."
      warn "Rebuild with: ruby generate_docs.rb"
      exit 1
    end
  else
    File.write(OUTPUT_PATH, generated)
    puts "Generated: #{OUTPUT_PATH}"
    puts "Source: #{SKILL_PATH}"
  end
end

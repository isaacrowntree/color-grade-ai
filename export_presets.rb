#!/usr/bin/env ruby
# export_presets.rb - Emit presets.yml as JSON for the browser
#
# presets.yml stays the single source of truth. The browser cannot parse YAML
# without pulling in a dependency, and the preview is deliberately dependency
# free beyond Preact, so the data is exported instead.
#
# test_repo_hygiene.rb fails if the export has drifted from the YAML.
#
# Run: ruby export_presets.rb

require 'json'
require 'yaml'

SOURCE = File.join(__dir__, 'presets.yml')
OUTPUT = File.join(__dir__, 'presets.json')

presets = YAML.load_file(SOURCE)
File.write(OUTPUT, JSON.pretty_generate(presets) + "\n")

puts "Generated: #{OUTPUT} (#{presets.length} presets)"

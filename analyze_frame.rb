#!/usr/bin/env ruby
# analyze_frame.rb - Extract color statistics from a region of a video frame
#
# Usage: ruby analyze_frame.rb <image_path> <x1,y1,x2,y2> [label]
#
# A thin wrapper over analyze_region.py, which does the measuring. This used to
# embed the Python as a heredoc, write it to a tempfile, and run it with
# `2>&1` — so when Pillow deprecated Image.getdata(), the warning landed on the
# same stream as the JSON and the tool broke outright. Keeping the Python in a
# real file means it can be tested, and keeping stderr separate means a warning
# can never masquerade as data again.
#
# Requires Python 3 with Pillow and NumPy.
#
# Example:
#   ruby analyze_frame.rb frame.png 400,200,600,350 skin
#   ruby analyze_frame.rb frame.png 350,400,550,600 costume

require 'json'
require 'open3'

image_path = ARGV[0] || abort("Usage: ruby analyze_frame.rb <image_path> <x1,y1,x2,y2> [label]")
region = ARGV[1] || abort("Specify region as x1,y1,x2,y2")
label = ARGV[2] || 'sample'

script = File.join(__dir__, 'analyze_region.py')

# Capture stdout and stderr separately: stdout is JSON, stderr is diagnostics.
stdout, stderr, status = Open3.capture3(
  'python3', script, image_path, region, label
)

unless status.success?
  warn stderr unless stderr.empty?
  abort "analyze_region.py failed (exit #{status.exitstatus})"
end

# Surface warnings without letting them corrupt the parse.
warn stderr unless stderr.strip.empty?

begin
  data = JSON.parse(stdout)
rescue JSON::ParserError => e
  abort "Could not parse analyze_region.py output: #{e.message}\n#{stdout}"
end

puts "=== #{data['label'].upcase} ==="
puts "Region: #{data['region'].inspect} (#{data['pixel_count']} pixels)"
puts "Avg RGB: R=#{data['avg_rgb']['r']} G=#{data['avg_rgb']['g']} B=#{data['avg_rgb']['b']}"
puts "Avg HSV: H=#{data['avg_hsv']['h']}° S=#{data['avg_hsv']['s']} V=#{data['avg_hsv']['v']}"
puts "Hue:     mean=#{data['hue']['mean']}° spread=#{data['hue']['spread']}° " \
     "(#{data['hue']['min']}°-#{data['hue']['max']}°)"
puts "Sat:     mean=#{data['s_range']['mean']} (#{data['s_range']['min']}-#{data['s_range']['max']})"
puts "Value:   mean=#{data['v_range']['mean']} (#{data['v_range']['min']}-#{data['v_range']['max']})"
puts "Luma:    #{data['luminance']}"
puts "Skin:    #{(data['skin_fraction'] * 100).round(1)}% of the region"
puts
puts JSON.pretty_generate(data)

#!/usr/bin/env ruby
# analyze_frame.rb - Extract color statistics from a region of a video frame
#
# Usage: ruby analyze_frame.rb <image_path> <x1,y1,x2,y2> [label]
#
# Requires Python3 with Pillow. Outputs HSV/RGB statistics for the sampled region.
# Use multiple calls with different regions to build a color profile.
#
# Example:
#   ruby analyze_frame.rb /tmp/frame.png 400,200,600,350 skin
#   ruby analyze_frame.rb /tmp/frame.png 350,400,550,600 pants

require 'json'
require 'tempfile'

image_path = ARGV[0] || abort("Usage: ruby analyze_frame.rb <image_path> <x1,y1,x2,y2> [label]")
region = ARGV[1] || abort("Specify region as x1,y1,x2,y2")
label = ARGV[2] || "sample"

x1, y1, x2, y2 = region.split(',').map(&:to_i)

script = <<~PYTHON
import sys, json
from PIL import Image
import colorsys

img = Image.open("#{image_path}")
crop = img.crop((#{x1}, #{y1}, #{x2}, #{y2}))
pixels = list(crop.getdata())

r_vals = [p[0] for p in pixels]
g_vals = [p[1] for p in pixels]
b_vals = [p[2] for p in pixels]

avg_r = sum(r_vals) / len(r_vals)
avg_g = sum(g_vals) / len(g_vals)
avg_b = sum(b_vals) / len(b_vals)

h, s, v = colorsys.rgb_to_hsv(avg_r/255, avg_g/255, avg_b/255)

# Also compute distribution
hsv_pixels = [colorsys.rgb_to_hsv(r/255, g/255, b/255) for r, g, b in pixels]
h_vals = [p[0]*360 for p in hsv_pixels]
s_vals = [p[1] for p in hsv_pixels]
v_vals = [p[2] for p in hsv_pixels]

result = {
    "label": "#{label}",
    "region": [#{x1}, #{y1}, #{x2}, #{y2}],
    "pixel_count": len(pixels),
    "avg_rgb": {"r": round(avg_r, 1), "g": round(avg_g, 1), "b": round(avg_b, 1)},
    "avg_hsv": {"h": round(h*360, 1), "s": round(s, 3), "v": round(v, 3)},
    "h_range": {"min": round(min(h_vals), 1), "max": round(max(h_vals), 1),
                "std": round((sum((x - h*360)**2 for x in h_vals) / len(h_vals))**0.5, 1)},
    "s_range": {"min": round(min(s_vals), 3), "max": round(max(s_vals), 3)},
    "v_range": {"min": round(min(v_vals), 3), "max": round(max(v_vals), 3)}
}
print(json.dumps(result, indent=2))
PYTHON

Tempfile.create(['analyze', '.py']) do |f|
  f.write(script)
  f.flush
  output = `python3 #{f.path} 2>&1`
  if $?.success?
    data = JSON.parse(output)
    puts "=== #{data['label'].upcase} ==="
    puts "Region: #{data['region'].inspect} (#{data['pixel_count']} pixels)"
    puts "Avg RGB: R=#{data['avg_rgb']['r']} G=#{data['avg_rgb']['g']} B=#{data['avg_rgb']['b']}"
    puts "Avg HSV: H=#{data['avg_hsv']['h']}° S=#{data['avg_hsv']['s']} V=#{data['avg_hsv']['v']}"
    puts "Hue range: #{data['h_range']['min']}°-#{data['h_range']['max']}° (std=#{data['h_range']['std']}°)"
    puts "Sat range: #{data['s_range']['min']}-#{data['s_range']['max']}"
    puts "Lum range: #{data['v_range']['min']}-#{data['v_range']['max']}"
    puts JSON.pretty_generate(data)
  else
    abort "Error: #{output}"
  end
end

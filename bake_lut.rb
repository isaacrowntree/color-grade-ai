#!/usr/bin/env ruby
# bake_lut.rb - Generate LUTs from arbitrary pipelines described as JSON
#
# The solver needs to synthesise corrections rather than pick from the fixed
# preset library: a 4% cool_shift cannot neutralise a 22% cast no matter what
# strength it is applied at. It also needs many LUTs per frame, so batching them
# into one Ruby invocation matters more than convenience.
#
# Ruby remains the single source of truth for the colour maths — nothing here
# reimplements a step, it only assembles them.
#
# Input (stdin), JSON:
#   {
#     "size": 17,
#     "outputs": [
#       { "path": "a.cube",
#         "title": "fitted white balance",
#         "steps": [ { "pipeline": [ {...step...} ], "strength": 0.5 } ] }
#     ]
#   }
#
# Each output's steps are applied in order, exactly as a node chain would be.

require 'json'
require_relative 'generate_lut'

request = JSON.parse(STDIN.read)
size = request['size'] || LUT_DEFAULT_SIZE
color_model = request['legacy'] ? :hsl : DEFAULT_COLOR_MODEL

request['outputs'].each do |output|
  steps = output['steps']

  table = generate_lut(size) do |r, g, b|
    steps.each do |step|
      r, g, b = apply_pipeline(r, g, b, step['pipeline'], step['strength'],
                               color_model: color_model)
    end
    [r, g, b]
  end

  comments = output['comments'] || []
  write_cube(output['path'], table, size, output['title'] || 'fitted', comments)
end

puts JSON.generate({ 'written' => request['outputs'].map { |o| o['path'] } })

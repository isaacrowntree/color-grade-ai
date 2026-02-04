#!/usr/bin/env ruby
# generate_lut.rb - Generate 3D .cube LUT files for color correction
#
# Works with both DaVinci Resolve and Adobe Premiere Pro.
# Apply AFTER a LogC→Rec.709 conversion LUT in your node/effect chain.
#
# Usage:
#   ruby generate_lut.rb <type> <output_path> [options]
#
# Types:
#   yellow_fix         - Remove warm amber/yellow cast from stage lighting
#   warm_skin_cast_fix - Fix red/orange cast on skin from warm practical lights
#   overexposure_fix   - Scene-wide overexposure correction (~1 stop, all hues)
#   underexposure_fix  - Scene-wide underexposure lift (~1.2 stops, shadow recovery)
#   black_crush        - Crush milky/lifted blacks to true black
#   skin_highlight_fix - Roll off overexposed skin highlights only (subtle)
#
# Examples:
#   ruby generate_lut.rb yellow_fix /mnt/h/yellow_cast_fix.cube
#   ruby generate_lut.rb overexposure_fix /mnt/h/overexposure_fix.cube
#   ruby generate_lut.rb black_crush /mnt/h/black_crush.cube
#   ruby generate_lut.rb overexposure_fix /mnt/h/mild.cube --strength=0.5
#
# Options:
#   --strength=N   Overall strength 0.0-1.0 (default: 1.0)
#   --size=N       LUT grid size (default: 33)

require 'optparse'

LUT_DEFAULT_SIZE = 33

# ── Color space helpers ──────────────────────────────────────────────

def rgb_to_hsl(r, g, b)
  max = [r, g, b].max
  min = [r, g, b].min
  l = (max + min) / 2.0

  if max == min
    return [0.0, 0.0, l]
  end

  d = max - min
  s = l > 0.5 ? d / (2.0 - max - min) : d / (max + min)

  h = case max
      when r then (g - b) / d + (g < b ? 6.0 : 0.0)
      when g then (b - r) / d + 2.0
      when b then (r - g) / d + 4.0
      end
  h *= 60.0

  [h, s, l]
end

def hsl_to_rgb(h, s, l)
  return [l, l, l] if s == 0.0

  q = l < 0.5 ? l * (1.0 + s) : l + s - l * s
  p = 2.0 * l - q
  hk = h / 360.0

  [hk + 1.0/3.0, hk, hk - 1.0/3.0].map do |t|
    t += 1.0 if t < 0
    t -= 1.0 if t > 1
    if    t < 1.0/6.0 then p + (q - p) * 6.0 * t
    elsif t < 0.5     then q
    elsif t < 2.0/3.0 then p + (q - p) * (2.0/3.0 - t) * 6.0
    else  p
    end
  end
end

# Smooth interpolation for hue-based targeting
def hue_strength(hue, center, width, softness)
  diff = (hue - center).abs
  diff = 360.0 - diff if diff > 180.0

  if diff <= width - softness
    1.0
  elsif diff <= width + softness
    t = (diff - (width - softness)) / (2.0 * softness)
    (1.0 + Math.cos(t * Math::PI)) / 2.0
  else
    0.0
  end
end

# Soft knee highlight rolloff. Maps input luminance to compressed output.
# knee_start: where rolloff begins (0.0-1.0)
# knee_end: maximum output value (ceiling)
def soft_knee_rolloff(value, knee_start, knee_end)
  return value if value <= knee_start

  # Quadratic rolloff above knee
  range = 1.0 - knee_start
  overshoot = (value - knee_start) / range
  compressed = knee_start + (knee_end - knee_start) * (1.0 - (1.0 - overshoot) ** 0.5)
  # Simpler: use a power curve for gentle compression
  t = (value - knee_start) / range
  knee_start + (knee_end - knee_start) * (2.0 * t - t * t)
end

def clamp(v, lo = 0.0, hi = 1.0)
  [[v, lo].max, hi].min
end

# ── LUT presets ──────────────────────────────────────────────────────

def generate_yellow_fix(size, strength)
  hue_center  = 35.0   # warm amber center
  hue_width   = 25.0   # ±25° covers 10°-60°
  softness    = 10.0
  sat_reduce  = 0.45   # reduce sat to 45% of original in targeted range
  hue_shift   = -5.0   # shift slightly away from yellow

  generate_lut(size) do |r, g, b|
    h, s, l = rgb_to_hsl(r, g, b)
    if s > 0.02
      str = hue_strength(h, hue_center, hue_width, softness)
      if str > 0
        sat_factor = [s / 0.5, 1.0].min
        effective = str * sat_factor * strength

        new_s = s * (1.0 - effective * (1.0 - sat_reduce))
        new_h = h + hue_shift * effective
        new_h += 360.0 if new_h < 0
        new_h -= 360.0 if new_h >= 360.0

        r, g, b = hsl_to_rgb(new_h, new_s, l)
      end
    end
    [r, g, b]
  end
end

def generate_warm_skin_cast_fix(size, strength)
  # Fix "sunburnt red" skin from warm practical lights.
  # Extremely surgical — uses hue + saturation + luminance windows to isolate
  # ONLY skin tones, leaving light sources, deck, colored objects untouched.
  #
  # Skin occupies a narrow band: H=5-30°, S=0.08-0.45, L=0.25-0.75
  # Light sources: very high luminance or very high saturation (excluded)
  # Dark surfaces: very low luminance (excluded)
  # Saturated objects: S > 0.50 (excluded)
  #
  # The fix: shift red skin hues toward peach (+15°) with gentle desat (15%).

  hue_center   = 12.0    # target the red end of skin
  hue_width    = 18.0    # ±18° covers 354°-30°
  hue_soft     = 6.0

  hue_shift    = 15.0    # push from red/flushed toward peach/natural
  sat_reduce   = 0.85    # gentle 15% desaturation

  # Luminance window — skin brightness only
  lum_low      = 0.22
  lum_high     = 0.78
  lum_soft     = 0.08

  # Saturation window — skin range only
  # Skin: 0.08-0.45. Light sources/deck/colored objects: >0.50
  sat_low      = 0.06
  sat_high     = 0.48
  sat_soft     = 0.06

  generate_lut(size) do |r, g, b|
    h, s, l = rgb_to_hsl(r, g, b)

    # Hue targeting
    hue_str = hue_strength(h, hue_center, hue_width, hue_soft)

    if hue_str > 0
      # Luminance window
      if l < lum_low
        lum_str = 0.0
      elsif l < lum_low + lum_soft
        lum_str = (l - lum_low) / lum_soft
      elsif l > lum_high
        lum_str = 0.0
      elsif l > lum_high - lum_soft
        lum_str = (lum_high - l) / lum_soft
      else
        lum_str = 1.0
      end

      # Saturation window — exclude highly saturated (light sources, objects)
      # and very desaturated (near-neutral greys)
      if s < sat_low
        sat_str = 0.0
      elsif s < sat_low + sat_soft
        sat_str = (s - sat_low) / sat_soft
      elsif s > sat_high
        sat_str = 0.0
      elsif s > sat_high - sat_soft
        sat_str = (sat_high - s) / sat_soft
      else
        sat_str = 1.0
      end

      effective = hue_str * lum_str * sat_str * strength

      if effective > 0.01
        new_h = h + hue_shift * effective
        new_h += 360.0 if new_h < 0
        new_h -= 360.0 if new_h >= 360.0

        new_s = s * (1.0 - effective * (1.0 - sat_reduce))

        r, g, b = hsl_to_rgb(new_h, new_s, l)
      end
    end

    [r, g, b]
  end
end

def generate_skin_highlight_fix(size, strength)
  # Skin tone hue targeting
  skin_hue_center = 25.0    # skin tones in Rec.709
  skin_hue_width  = 25.0    # ±25° covers 0°-50° (peach through warm yellow)
  skin_softness   = 12.0

  # Highlight rolloff parameters
  knee_start     = 0.70     # start compressing above 70% luminance
  knee_ceiling   = 0.92     # max output luminance for skin
  global_knee    = 0.85     # gentle global rolloff for non-skin highlights
  global_ceiling = 0.97

  # Desaturate hot skin slightly
  hot_desat = 0.7           # reduce saturation to 70% in blown highlights

  generate_lut(size) do |r, g, b|
    h, s, l = rgb_to_hsl(r, g, b)

    # Determine skin hue strength
    skin_str = hue_strength(h, skin_hue_center, skin_hue_width, skin_softness)
    effective_skin = skin_str * [s / 0.15, 1.0].min * strength

    if l > knee_start && effective_skin > 0.1
      # Skin highlight rolloff — stronger compression
      new_l = soft_knee_rolloff(l, knee_start, knee_ceiling)
      blended_l = l + (new_l - l) * effective_skin

      # Desaturate hot skin proportionally
      hot_amount = [(l - knee_start) / (1.0 - knee_start), 1.0].min
      desat_factor = 1.0 - (1.0 - hot_desat) * hot_amount * effective_skin
      new_s = s * desat_factor

      r, g, b = hsl_to_rgb(h, new_s, blended_l)
    elsif l > global_knee
      # Gentle global highlight rolloff for everything else
      new_l = soft_knee_rolloff(l, global_knee, global_ceiling)
      blended_l = l + (new_l - l) * strength * (1.0 - effective_skin)
      r, g, b = hsl_to_rgb(h, s, blended_l)
    end

    [r, g, b]
  end
end

def generate_overexposure_fix(size, strength)
  # Scene-wide overexposure correction (~1-1.5 stops)
  # Applies to ALL hues, not just skin.
  #
  # Three components:
  # 1. Global exposure reduction via power curve (gamma up = darken)
  # 2. Highlight compression with soft knee
  # 3. Extra skin-tone highlight compression + desaturation

  gamma         = 1.0 + 0.35 * strength  # 1.35 at full strength (~1 stop down)
  knee_start    = 0.55                     # start highlight rolloff early
  knee_ceiling  = 0.85                     # compress highlights hard
  skin_ceiling  = 0.78                     # even harder for skin

  skin_hue_center = 25.0
  skin_hue_width  = 25.0
  skin_softness   = 12.0

  generate_lut(size) do |r, g, b|
    h, s, l = rgb_to_hsl(r, g, b)

    # Step 1: Global exposure reduction via power curve
    new_l = l ** gamma

    # Step 2: Highlight compression for ALL pixels
    if new_l > knee_start
      new_l = soft_knee_rolloff(new_l, knee_start, knee_ceiling)
    end

    # Step 3: Extra compression for skin tones
    skin_str = s > 0.03 ? hue_strength(h, skin_hue_center, skin_hue_width, skin_softness) : 0.0
    if skin_str > 0 && new_l > 0.50
      skin_target = soft_knee_rolloff(new_l, 0.50, skin_ceiling)
      new_l = new_l + (skin_target - new_l) * skin_str * [s / 0.1, 1.0].min
    end

    # Step 4: Desaturate blown highlights slightly
    if new_l > 0.65
      hot = [(new_l - 0.65) / 0.35, 1.0].min
      s = s * (1.0 - hot * 0.25 * strength)
    end

    r, g, b = hsl_to_rgb(h, s, new_l)
    [r, g, b]
  end
end

def generate_underexposure_fix(size, strength)
  # Scene-wide underexposure correction (~1-1.5 stops lift)
  # Inverse of overexposure_fix.
  #
  # Three components:
  # 1. Global exposure lift via power curve (gamma < 1 = brighten)
  # 2. Shadow lift to recover detail in dark areas
  # 3. Gentle highlight protection so already-bright areas don't blow out

  gamma          = 1.0 - 0.30 * strength  # 0.70 at full strength (~1.2 stops up)
  shadow_lift    = 0.03 * strength         # lift the absolute black floor slightly
  highlight_knee = 0.80                    # start protecting highlights here
  highlight_cap  = 0.95                    # don't let anything exceed 95%

  generate_lut(size) do |r, g, b|
    h, s, l = rgb_to_hsl(r, g, b)

    # Step 1: Lift the black floor
    new_l = l + shadow_lift * (1.0 - l)

    # Step 2: Global exposure lift via power curve
    new_l = new_l ** gamma

    # Step 3: Protect highlights from blowing out
    if new_l > highlight_knee
      over = (new_l - highlight_knee) / (1.0 - highlight_knee)
      compressed = highlight_knee + (highlight_cap - highlight_knee) * (2.0 * over - over * over)
      new_l = compressed
    end

    # Slight saturation boost to counteract the washed-out look of lifted shadows
    if l > 0.05 && l < 0.50
      shadow_boost = [(0.50 - l) / 0.45, 1.0].min
      s = s * (1.0 + 0.1 * shadow_boost * strength)
      s = [s, 1.0].min
    end

    r, g, b = hsl_to_rgb(h, s, new_l)
    [r, g, b]
  end
end

def generate_black_crush(size, strength)
  # Crush milky/lifted blacks to true black.
  # Steepens the shadow ramp so low values map closer to zero.
  #
  # - Below threshold: aggressive darkening
  # - Smooth transition back to identity above threshold
  # - Does not affect midtones or highlights at all

  black_threshold = 0.12    # input values below this get crushed
  crush_gamma     = 1.0 + 1.5 * strength  # 2.5 at full strength — steep shadow curve
  transition_end  = 0.25    # fully blends back to identity by this point

  generate_lut(size) do |r, g, b|
    h, s, l = rgb_to_hsl(r, g, b)

    if l < transition_end
      if l < black_threshold
        # Hard crush: apply steep gamma to shadows
        new_l = l ** crush_gamma
      else
        # Smooth blend from crushed back to identity
        crushed = l ** crush_gamma
        t = (l - black_threshold) / (transition_end - black_threshold)
        # Smooth hermite interpolation
        t = t * t * (3.0 - 2.0 * t)
        new_l = crushed + (l - crushed) * t
      end
      r, g, b = hsl_to_rgb(h, s, new_l)
    end

    [r, g, b]
  end
end

# ── LUT file writer ──────────────────────────────────────────────────

def generate_lut(size, &transform)
  table = []
  size.times do |bi|
    size.times do |gi|
      size.times do |ri|
        r = ri.to_f / (size - 1)
        g = gi.to_f / (size - 1)
        b = bi.to_f / (size - 1)

        ro, go, bo = transform.call(r, g, b)
        table << [clamp(ro), clamp(go), clamp(bo)]
      end
    end
  end
  table
end

def write_cube(path, table, size, title, comments = [])
  File.open(path, 'w') do |f|
    comments.each { |c| f.puts "# #{c}" }
    f.puts "TITLE \"#{title}\""
    f.puts "LUT_3D_SIZE #{size}"
    f.puts ""
    table.each do |r, g, b|
      f.printf("%.6f %.6f %.6f\n", r, g, b)
    end
  end
end

# ── CLI ──────────────────────────────────────────────────────────────

if __FILE__ == $0
  lut_type = ARGV.shift || abort(<<~USAGE)
    Usage: ruby generate_lut.rb <type> <output_path> [--strength=N] [--size=N]

    Types:
      yellow_fix           Remove warm amber/yellow cast from stage lighting
      skin_highlight_fix   Roll off overexposed skin highlights (subtle, skin-only)
      overexposure_fix     Scene-wide overexposure correction (~1 stop, all hues)
      underexposure_fix    Scene-wide underexposure lift (~1.2 stops, shadow recovery)
      black_crush          Crush milky/lifted blacks to true black

    Options:
      --strength=N   Overall strength 0.0-1.0 (default: 1.0)
      --size=N       LUT grid size (default: 33)
  USAGE

  output_path = ARGV.shift || abort("Specify output path")
  strength = 1.0
  size = LUT_DEFAULT_SIZE

  ARGV.each do |arg|
    if arg =~ /--strength=([\d.]+)/
      strength = $1.to_f
    elsif arg =~ /--size=(\d+)/
      size = $1.to_i
    end
  end

  case lut_type
  when 'yellow_fix'
    puts "Generating yellow cast fix LUT..."
    title = "Yellow Cast Fix - Stage Lighting"
    comments = [
      "Yellow/Amber Cast Fix LUT",
      "Targets warm stage lighting cast (H=10-60 degrees)",
      "Apply AFTER LogC to Rec.709 conversion",
      "Compatible with DaVinci Resolve and Adobe Premiere Pro",
      "Strength: #{strength}"
    ]
    table = generate_yellow_fix(size, strength)

  when 'warm_skin_cast_fix'
    puts "Generating warm skin cast fix LUT..."
    title = "Warm Skin Cast Fix - Red/Orange Practical Light"
    comments = [
      "Fixes red/orange cast on skin from warm practical lights",
      "Targets H=355-45 degrees (red through orange), 75% desaturation",
      "Only affects warm saturated tones - cool tones untouched",
      "Apply AFTER LogC to Rec.709 conversion",
      "Compatible with DaVinci Resolve and Adobe Premiere Pro",
      "Strength: #{strength}"
    ]
    table = generate_warm_skin_cast_fix(size, strength)

  when 'skin_highlight_fix'
    puts "Generating skin highlight fix LUT..."
    title = "Skin Highlight Fix - Overexposure Recovery"
    comments = [
      "Skin Highlight Rolloff LUT",
      "Compresses overexposed skin tones with soft knee",
      "Apply AFTER LogC to Rec.709 conversion",
      "Compatible with DaVinci Resolve and Adobe Premiere Pro",
      "Strength: #{strength}"
    ]
    table = generate_skin_highlight_fix(size, strength)

  when 'overexposure_fix'
    puts "Generating scene overexposure fix LUT..."
    title = "Scene Overexposure Fix"
    comments = [
      "Scene-wide overexposure correction (~1 stop reduction)",
      "Global gamma + highlight rolloff + skin protection",
      "Apply AFTER LogC to Rec.709 conversion",
      "Compatible with DaVinci Resolve and Adobe Premiere Pro",
      "Strength: #{strength}"
    ]
    table = generate_overexposure_fix(size, strength)

  when 'underexposure_fix'
    puts "Generating underexposure fix LUT..."
    title = "Scene Underexposure Fix"
    comments = [
      "Scene-wide underexposure lift (~1.2 stops)",
      "Global gamma lift + shadow recovery + highlight protection",
      "Apply AFTER LogC to Rec.709 conversion",
      "Compatible with DaVinci Resolve and Adobe Premiere Pro",
      "Strength: #{strength}"
    ]
    table = generate_underexposure_fix(size, strength)

  when 'black_crush'
    puts "Generating black crush LUT..."
    title = "Black Crush - Shadow Floor"
    comments = [
      "Crushes milky/lifted blacks to true black",
      "Only affects shadows below 25% luminance",
      "Apply AFTER LogC to Rec.709 conversion",
      "Compatible with DaVinci Resolve and Adobe Premiere Pro",
      "Strength: #{strength}"
    ]
    table = generate_black_crush(size, strength)

  else
    abort "Unknown LUT type: #{lut_type}\nAvailable: yellow_fix, warm_skin_cast_fix, overexposure_fix, underexposure_fix, black_crush, skin_highlight_fix"
  end

  write_cube(output_path, table, size, title, comments)

  puts "Generated: #{output_path}"
  puts "LUT size: #{size}x#{size}x#{size}"
  puts "Strength: #{strength}"
  puts ""
  puts "Usage in DaVinci Resolve:"
  puts "  Add a node AFTER your main conversion LUT"
  puts "  Right-click node -> LUT -> Browse -> select this .cube file"
  puts ""
  puts "Usage in Premiere Pro:"
  puts "  Lumetri Color -> Creative -> Look dropdown -> Browse"
end

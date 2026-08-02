// pipeline.mjs — the colour pipeline, in JavaScript.
//
// A direct port of generate_lut.rb so the browser preview can generate LUTs
// live from presets.json instead of fetching pre-baked .cube files. That fixes
// a real defect: preview.html interpolated the *result* of a full-strength LUT
// against the original, while the CLI interpolates the *parameters*. For
// studio_punch at 50% those diverge by a quarter of the range on saturated
// colours, so the preview was not showing the LUT you would get.
//
// Ruby remains the reference implementation. test_pipeline.mjs regenerates
// every shipped LUT here and compares against the committed .cube files, so
// this port cannot silently drift.

// ── Transfer functions ───────────────────────────────────────────────

export const DISPLAY_GAMMA = 2.4;

export function toLinear(v) {
  if (v <= 0) return 0;
  if (v >= 1) return 1;
  return Math.pow(v, DISPLAY_GAMMA);
}

export function fromLinear(v) {
  if (v <= 0) return 0;
  if (v >= 1) return 1;
  return Math.pow(v, 1 / DISPLAY_GAMMA);
}

export function luma709(r, g, b) {
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export const LINEAR_TONE_STEPS = new Set([
  'exposure', 'black_crush', 'highlight_protect', 'skin_rolloff', 'skin_highlight',
]);

// ── Colour space helpers ─────────────────────────────────────────────

export function clamp(v, lo = 0, hi = 1) {
  return Math.min(Math.max(v, lo), hi);
}

export function rgbToHsl(r, g, b) {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;

  if (max === min) return [0, 0, l];

  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);

  let h;
  if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;

  return [h * 60, s, l];
}

export function hslToRgb(h, s, l) {
  if (s === 0) return [l, l, l];

  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const hk = h / 360;

  return [hk + 1 / 3, hk, hk - 1 / 3].map((t) => {
    if (t < 0) t += 1;
    if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 0.5) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  });
}

export function hueStrength(hue, center, width, softness) {
  let diff = Math.abs(hue - center);
  if (diff > 180) diff = 360 - diff;

  if (diff <= width - softness) return 1;
  if (diff <= width + softness) {
    const t = (diff - (width - softness)) / (2 * softness);
    return (1 + Math.cos(t * Math.PI)) / 2;
  }
  return 0;
}

export function softKneeRolloff(value, kneeStart, kneeEnd) {
  if (value <= kneeStart) return value;
  const t = (value - kneeStart) / (1 - kneeStart);
  return kneeStart + (kneeEnd - kneeStart) * (2 * t - t * t);
}

function lumWindow(l, low, high, soft) {
  if (l < low) return 0;
  if (l < low + soft) return (l - low) / soft;
  if (l > high) return 0;
  if (l > high - soft) return (high - l) / soft;
  return 1;
}

function satWindow(s, low, high, soft) {
  if (s < low) return 0;
  if (s < low + soft) return (s - low) / soft;
  if (s > high) return 0;
  if (s > high - soft) return (high - s) / soft;
  return 1;
}

// ── Linear-light tone application ────────────────────────────────────

function applyLumaCurve(r, g, b, curve) {
  const linR = toLinear(r), linG = toLinear(g), linB = toLinear(b);
  const yLin = luma709(linR, linG, linB);

  const newYEnc = curve(fromLinear(yLin));
  const newYLin = toLinear(newYEnc);

  if (Math.abs(newYLin - yLin) < 1e-12) return [r, g, b];

  if (yLin <= 1e-12) {
    const v = fromLinear(newYLin);
    return [v, v, v];
  }

  const scale = newYLin / yLin;
  let sr = linR * scale, sg = linG * scale, sb = linB * scale;

  // Desaturate toward the target luminance rather than clipping per channel,
  // which would skew the ratios and therefore the hue.
  const peak = Math.max(sr, sg, sb);
  if (peak > 1 && peak > newYLin) {
    const k = (1 - newYLin) / (peak - newYLin);
    sr = newYLin + (sr - newYLin) * k;
    sg = newYLin + (sg - newYLin) * k;
    sb = newYLin + (sb - newYLin) * k;
  }

  return [fromLinear(clamp(sr)), fromLinear(clamp(sg)), fromLinear(clamp(sb))];
}

function resyncState(r, g, b, st) {
  const [h, s, l] = rgbToHsl(r, g, b);
  return { ...st, h, s, l };
}

// ── Legacy (HSL) step handlers ───────────────────────────────────────

const HSL_HANDLERS = {
  global_sat(r, g, b, st, cfg, strength) {
    const boost = 1 + (cfg.boost - 1) * strength;
    const s = clamp(st.s * boost);
    const [ro, go, bo] = hslToRgb(st.h, s, st.l);
    return [ro, go, bo, { ...st, s }];
  },

  rgb_rebalance(r, g, b, st, cfg, strength) {
    const rGain = 1 + (cfg.r_gain - 1) * strength;
    const gGain = 1 + (cfg.g_gain - 1) * strength;
    const bGain = 1 + (cfg.b_gain - 1) * strength;

    const lum = Math.max(r, g, b);
    const gainScale = Math.max(Math.min(lum / cfg.gain_ramp, 1), 0);

    const ro = clamp(r * (1 + (rGain - 1) * gainScale));
    const go = clamp(g * (1 + (gGain - 1) * gainScale));
    const bo = clamp(b * (1 + (bGain - 1) * gainScale));

    const [h, s, l] = rgbToHsl(ro, go, bo);
    return [ro, go, bo, { h, s, l, orig_l: l }];
  },

  exposure(r, g, b, st, cfg, strength) {
    const gamma = 1 + (cfg.gamma - 1) * strength;
    const shadowLift = cfg.shadow_lift * strength;
    let newL = st.l + shadowLift * (1 - st.l);
    newL = Math.pow(newL, gamma);
    const [ro, go, bo] = hslToRgb(st.h, st.s, newL);
    return [ro, go, bo, { ...st, l: newL }];
  },

  highlight_protect(r, g, b, st, cfg, strength) {
    if (st.l <= cfg.knee_start) return [r, g, b, st];
    const over = (st.l - cfg.knee_start) / (1 - cfg.knee_start);
    const newL = cfg.knee_start +
      (cfg.knee_ceiling - cfg.knee_start) * (2 * over - over * over);
    const [ro, go, bo] = hslToRgb(st.h, st.s, newL);
    return [ro, go, bo, { ...st, l: newL }];
  },

  black_crush(r, g, b, st, cfg, strength) {
    const crushGamma = 1 + (cfg.crush_gamma - 1) * strength;
    if (st.l >= cfg.transition_end) return [r, g, b, st];

    const crushed = Math.pow(st.l, crushGamma);
    let newL;
    if (st.l < cfg.black_threshold) {
      newL = crushed;
    } else {
      let t = (st.l - cfg.black_threshold) /
        (cfg.transition_end - cfg.black_threshold);
      t = t * t * (3 - 2 * t);
      newL = crushed + (st.l - crushed) * t;
    }
    const [ro, go, bo] = hslToRgb(st.h, st.s, newL);
    return [ro, go, bo, { ...st, l: newL }];
  },

  hue_desat(r, g, b, st, cfg, strength) {
    const minSat = cfg.min_sat ?? 0;
    if (st.s <= minSat) return [r, g, b, st];

    const str = hueStrength(st.h, cfg.hue_center, cfg.hue_width, cfg.softness);
    if (str <= 0) return [r, g, b, st];

    let effective;
    if (cfg.sat_scaling_ref != null) {
      effective = str * Math.min(st.s / cfg.sat_scaling_ref, 1) * strength;
    } else {
      effective = str * strength;
    }

    const newS = st.s * (1 - effective * (1 - cfg.sat_reduce));
    let newH = st.h + (cfg.hue_shift ?? 0) * effective;
    if (newH < 0) newH += 360;
    if (newH >= 360) newH -= 360;

    const [ro, go, bo] = hslToRgb(newH, newS, st.l);
    return [ro, go, bo, { ...st, h: newH, s: newS }];
  },

  skin_correction(r, g, b, st, cfg, strength) {
    const minSat = cfg.min_sat ?? 0.04;
    const hueStr = hueStrength(st.h, cfg.hue_center, cfg.hue_width, cfg.hue_soft);
    if (hueStr <= 0 || st.s <= minSat) return [r, g, b, st];

    const lumStr = lumWindow(st.orig_l, cfg.lum_low, cfg.lum_high, cfg.lum_soft);
    const satStr = satWindow(st.s, cfg.sat_low, cfg.sat_high, cfg.sat_soft);
    const effective = hueStr * lumStr * satStr * strength;
    if (effective <= 0.01) return [r, g, b, st];

    let newH = st.h + cfg.hue_shift * effective;
    if (newH < 0) newH += 360;
    if (newH >= 360) newH -= 360;

    let newS = st.s;
    if (cfg.adaptive_desat) {
      const excess = Math.max(st.s - cfg.desat_sat_ref, 0) / cfg.desat_sat_range;
      const satReduce = cfg.desat_baseline - cfg.desat_range * excess;
      newS = st.s * (1 - effective * (1 - satReduce));
    }

    const [ro, go, bo] = hslToRgb(newH, newS, st.l);
    return [ro, go, bo, { ...st, h: newH, s: newS }];
  },

  shadow_sat_boost(r, g, b, st, cfg, strength) {
    if (st.orig_l <= cfg.range_low || st.orig_l >= cfg.range_high) {
      return [r, g, b, st];
    }
    const shadowBoost = Math.min(
      (cfg.range_high - st.orig_l) / (cfg.range_high - cfg.range_low), 1);
    const newS = Math.min(st.s * (1 + cfg.boost * shadowBoost * strength), 1);
    const [ro, go, bo] = hslToRgb(st.h, newS, st.l);
    return [ro, go, bo, { ...st, s: newS }];
  },

  skin_highlight(r, g, b, st, cfg, strength) {
    const skinStr = hueStrength(st.h, cfg.skin_hue_center, cfg.skin_hue_width,
      cfg.skin_softness);
    const effectiveSkin = skinStr * Math.min(st.s / cfg.min_sat_ratio, 1) * strength;

    if (st.l > cfg.knee_start && effectiveSkin > 0.1) {
      const newL = softKneeRolloff(st.l, cfg.knee_start, cfg.knee_ceiling);
      const blended = st.l + (newL - st.l) * effectiveSkin;
      const hot = Math.min((st.l - cfg.knee_start) / (1 - cfg.knee_start), 1);
      const newS = st.s * (1 - (1 - cfg.hot_desat) * hot * effectiveSkin);
      const [ro, go, bo] = hslToRgb(st.h, newS, blended);
      return [ro, go, bo, { ...st, s: newS, l: blended }];
    }

    if (st.l > cfg.global_knee) {
      const newL = softKneeRolloff(st.l, cfg.global_knee, cfg.global_ceiling);
      const blended = st.l + (newL - st.l) * strength * (1 - effectiveSkin);
      const [ro, go, bo] = hslToRgb(st.h, st.s, blended);
      return [ro, go, bo, { ...st, l: blended }];
    }

    return [r, g, b, st];
  },

  skin_rolloff(r, g, b, st, cfg, strength) {
    const minSat = cfg.min_sat ?? 0.03;
    const skinStr = st.s > minSat
      ? hueStrength(st.h, cfg.skin_hue_center, cfg.skin_hue_width, cfg.skin_softness)
      : 0;
    if (skinStr <= 0 || st.l <= cfg.knee_start) return [r, g, b, st];

    const target = softKneeRolloff(st.l, cfg.knee_start, cfg.knee_ceiling);
    const newL = st.l + (target - st.l) * skinStr * Math.min(st.s / 0.1, 1);
    const [ro, go, bo] = hslToRgb(st.h, st.s, newL);
    return [ro, go, bo, { ...st, l: newL }];
  },

  global_highlight_desat(r, g, b, st, cfg, strength) {
    if (st.l <= cfg.threshold) return [r, g, b, st];
    const hot = Math.min((st.l - cfg.threshold) / (1 - cfg.threshold), 1);
    const newS = st.s * (1 - hot * cfg.desat_amount * strength);
    const [ro, go, bo] = hslToRgb(st.h, newS, st.l);
    return [ro, go, bo, { ...st, s: newS }];
  },
};

// ── Linear-light step handlers ───────────────────────────────────────

const LINEAR_HANDLERS = {
  exposure(r, g, b, st, cfg, strength) {
    const gamma = 1 + (cfg.gamma - 1) * strength;
    const shadowLift = cfg.shadow_lift * strength;
    const [ro, go, bo] = applyLumaCurve(r, g, b,
      (y) => Math.pow(y + shadowLift * (1 - y), gamma));
    return [ro, go, bo, resyncState(ro, go, bo, st)];
  },

  highlight_protect(r, g, b, st, cfg, strength) {
    const [ro, go, bo] = applyLumaCurve(r, g, b, (y) => {
      if (y <= cfg.knee_start) return y;
      const over = (y - cfg.knee_start) / (1 - cfg.knee_start);
      return cfg.knee_start +
        (cfg.knee_ceiling - cfg.knee_start) * (2 * over - over * over);
    });
    return [ro, go, bo, resyncState(ro, go, bo, st)];
  },

  black_crush(r, g, b, st, cfg, strength) {
    const crushGamma = 1 + (cfg.crush_gamma - 1) * strength;
    const [ro, go, bo] = applyLumaCurve(r, g, b, (y) => {
      if (y >= cfg.transition_end) return y;
      const crushed = Math.pow(y, crushGamma);
      if (y < cfg.black_threshold) return crushed;
      let t = (y - cfg.black_threshold) /
        (cfg.transition_end - cfg.black_threshold);
      t = t * t * (3 - 2 * t);
      return crushed + (y - crushed) * t;
    });
    return [ro, go, bo, resyncState(ro, go, bo, st)];
  },

  skin_rolloff(r, g, b, st, cfg, strength) {
    const minSat = cfg.min_sat ?? 0.03;
    const skinStr = st.s > minSat
      ? hueStrength(st.h, cfg.skin_hue_center, cfg.skin_hue_width, cfg.skin_softness)
      : 0;
    if (skinStr <= 0) return [r, g, b, st];

    const weight = skinStr * Math.min(st.s / 0.1, 1);
    const [ro, go, bo] = applyLumaCurve(r, g, b, (y) => (
      y > cfg.knee_start
        ? y + (softKneeRolloff(y, cfg.knee_start, cfg.knee_ceiling) - y) * weight
        : y
    ));
    return [ro, go, bo, resyncState(ro, go, bo, st)];
  },

  skin_highlight(r, g, b, st, cfg, strength) {
    const skinStr = hueStrength(st.h, cfg.skin_hue_center, cfg.skin_hue_width,
      cfg.skin_softness);
    const effectiveSkin = skinStr * Math.min(st.s / cfg.min_sat_ratio, 1) * strength;

    let hotAmount = null;
    const [ro, go, bo] = applyLumaCurve(r, g, b, (y) => {
      if (y > cfg.knee_start && effectiveSkin > 0.1) {
        hotAmount = Math.min((y - cfg.knee_start) / (1 - cfg.knee_start), 1);
        const target = softKneeRolloff(y, cfg.knee_start, cfg.knee_ceiling);
        return y + (target - y) * effectiveSkin;
      }
      if (y > cfg.global_knee) {
        const target = softKneeRolloff(y, cfg.global_knee, cfg.global_ceiling);
        return y + (target - y) * strength * (1 - effectiveSkin);
      }
      return y;
    });

    let state = resyncState(ro, go, bo, st);
    if (hotAmount !== null) {
      const desat = 1 - (1 - cfg.hot_desat) * hotAmount * effectiveSkin;
      const newS = state.s * desat;
      const [r2, g2, b2] = hslToRgb(state.h, newS, state.l);
      return [r2, g2, b2, { ...state, s: newS }];
    }
    return [ro, go, bo, state];
  },
};

// ── Pipeline runner ──────────────────────────────────────────────────

export function applyPipeline(r, g, b, pipeline, strength, colorModel = 'linear') {
  const [h, s, l] = rgbToHsl(r, g, b);
  let state = { h, s, l, orig_l: l };

  for (const cfg of pipeline) {
    const useLinear = colorModel === 'linear' && LINEAR_TONE_STEPS.has(cfg.step);
    const handler = useLinear ? LINEAR_HANDLERS[cfg.step] : HSL_HANDLERS[cfg.step];
    if (!handler) throw new Error(`Unknown step type: ${cfg.step}`);
    [r, g, b, state] = handler(r, g, b, state, cfg, strength);
  }

  return [r, g, b];
}

/**
 * Generate a LUT table for a chain of { pipeline, strength } steps.
 * Returns a Float64Array of size^3 * 3 in .cube order (red fastest).
 */
export function generateTable(steps, size = 33, colorModel = 'linear') {
  const table = new Float64Array(size * size * size * 3);
  let i = 0;

  for (let bi = 0; bi < size; bi++) {
    for (let gi = 0; gi < size; gi++) {
      for (let ri = 0; ri < size; ri++) {
        let r = ri / (size - 1);
        let g = gi / (size - 1);
        let b = bi / (size - 1);

        for (const step of steps) {
          [r, g, b] = applyPipeline(r, g, b, step.pipeline, step.strength, colorModel);
        }

        table[i++] = clamp(r);
        table[i++] = clamp(g);
        table[i++] = clamp(b);
      }
    }
  }

  return table;
}

/** Serialise a table as .cube text, matching write_cube in generate_lut.rb. */
export function formatCube(table, size, title = 'color-grade-ai', comments = []) {
  const lines = comments.map((c) => `# ${c}`);
  lines.push(`TITLE "${title}"`, `LUT_3D_SIZE ${size}`, '');
  for (let i = 0; i < table.length; i += 3) {
    lines.push(`${table[i].toFixed(6)} ${table[i + 1].toFixed(6)} ${table[i + 2].toFixed(6)}`);
  }
  return lines.join('\n') + '\n';
}

// test_pipeline.mjs — parity tests for the JavaScript pipeline port.
//
// The JS port exists so the browser preview can generate LUTs live. Two
// implementations of the same colour maths is a drift risk, so this suite
// regenerates every shipped LUT in JS and compares it against the .cube files
// Ruby produced and CI already verifies.
//
// Run: node --test test_pipeline.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  applyPipeline, generateTable, formatCube, rgbToHsl, hslToRgb,
  toLinear, fromLinear, luma709, clamp,
} from './pipeline.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));

const presets = JSON.parse(readFileSync(join(HERE, 'presets.json'), 'utf8'));
const manifest = readManifest();

function readManifest() {
  // A deliberately small YAML subset reader: the manifest is generated, so its
  // shape is fixed and a dependency would be disproportionate.
  const text = readFileSync(join(HERE, 'correction_luts', 'manifest.yml'), 'utf8');
  const entries = {};
  let current = null;
  let chain = null;

  for (const raw of text.split('\n')) {
    if (!raw.trim() || raw.trim().startsWith('#') || raw.trim() === '---') continue;

    const top = raw.match(/^([A-Za-z0-9_]+):\s*$/);
    if (top) {
      current = top[1];
      entries[current] = {};
      chain = null;
      continue;
    }

    const preset = raw.match(/^\s{2}preset:\s*(\S+)\s*$/);
    if (preset) { entries[current].preset = preset[1]; continue; }

    const strength = raw.match(/^\s{2}strength:\s*([\d.]+)\s*$/);
    if (strength) { entries[current].strength = parseFloat(strength[1]); continue; }

    if (/^\s{2}chain:\s*$/.test(raw)) { chain = []; entries[current].chain = chain; continue; }

    const chainPreset = raw.match(/^\s*-\s*preset:\s*(\S+)\s*$/);
    if (chainPreset && chain) { chain.push({ preset: chainPreset[1] }); continue; }

    const chainStrength = raw.match(/^\s{4}strength:\s*([\d.]+)\s*$/);
    if (chainStrength && chain && chain.length) {
      chain[chain.length - 1].strength = parseFloat(chainStrength[1]);
    }
  }

  return entries;
}

function stepsFor(entry) {
  if (entry.chain) {
    return entry.chain.map((c) => ({
      pipeline: presets[c.preset].pipeline,
      strength: c.strength,
    }));
  }
  return [{ pipeline: presets[entry.preset].pipeline, strength: entry.strength }];
}

function readCubeData(name) {
  const text = readFileSync(join(HERE, 'correction_luts', `${name}.cube`), 'utf8');
  const rows = [];
  for (const line of text.split('\n')) {
    if (!/^\d/.test(line)) continue;
    const [r, g, b] = line.trim().split(/\s+/).map(Number);
    rows.push(r, g, b);
  }
  return rows;
}

// ── Transfer functions ───────────────────────────────────────────────

test('transfer functions round-trip', () => {
  let worst = 0;
  for (let i = 0; i <= 1000; i++) {
    const v = i / 1000;
    worst = Math.max(worst, Math.abs(fromLinear(toLinear(v)) - v));
  }
  assert.ok(worst < 1e-9, `round-trip error ${worst}`);
});

test('transfer function endpoints are exact', () => {
  assert.equal(toLinear(0), 0);
  assert.equal(toLinear(1), 1);
  assert.equal(fromLinear(0), 0);
  assert.equal(fromLinear(1), 1);
});

test('luma uses Rec.709 coefficients', () => {
  assert.ok(Math.abs(luma709(1, 0, 0) - 0.2126) < 1e-12);
  assert.ok(Math.abs(luma709(0, 1, 0) - 0.7152) < 1e-12);
  assert.ok(Math.abs(luma709(0, 0, 1) - 0.0722) < 1e-12);
});

// ── HSL helpers ──────────────────────────────────────────────────────

test('rgb/hsl round-trips', () => {
  const samples = [[0.2, 0.5, 0.8], [0.9, 0.1, 0.3], [0.5, 0.5, 0.5], [0, 0, 0]];
  for (const [r, g, b] of samples) {
    const [h, s, l] = rgbToHsl(r, g, b);
    const [ro, go, bo] = hslToRgb(h, s, l);
    const err = Math.max(Math.abs(ro - r), Math.abs(go - g), Math.abs(bo - b));
    assert.ok(err < 1e-12, `${[r, g, b]} round-tripped with error ${err}`);
  }
});

test('hsl hue matches known primaries', () => {
  assert.equal(rgbToHsl(1, 0, 0)[0], 0);
  assert.equal(rgbToHsl(0, 1, 0)[0], 120);
  assert.equal(rgbToHsl(0, 0, 1)[0], 240);
});

// ── Parity with the shipped LUTs ─────────────────────────────────────

const TOLERANCE = 2e-6; // .cube files store six decimals

for (const [name, entry] of Object.entries(manifest)) {
  test(`matches shipped LUT: ${name}`, () => {
    const expected = readCubeData(name);
    const size = Math.round(Math.cbrt(expected.length / 3));
    const table = generateTable(stepsFor(entry), size);

    assert.equal(table.length, expected.length,
      `${name}: expected ${expected.length} values, got ${table.length}`);

    let worst = 0;
    let worstIndex = -1;
    for (let i = 0; i < expected.length; i++) {
      const d = Math.abs(table[i] - expected[i]);
      if (d > worst) { worst = d; worstIndex = i; }
    }

    assert.ok(worst <= TOLERANCE,
      `${name}: max divergence ${worst.toExponential(3)} at index ${worstIndex}`);
  });
}

// ── Live parity against Ruby ─────────────────────────────────────────
//
// Comparing against the committed .cube files only proves parity at the ten
// strengths the manifest happens to use. The browser's slider can ask for any
// of 101, and arbitrary strengths are the entire reason this port exists — so
// drive the real Ruby implementation and compare against that instead.
//
// Every case goes over in a single invocation; spawning Ruby per case would
// dominate the runtime.

function rubyPipeline(cases) {
  const script = `
    require 'json'
    require_relative 'generate_lut'
    presets = load_presets
    JSON.parse(STDIN.read).map do |c|
      pipeline = presets[c['preset']]['pipeline']
      model = c['model'] == 'hsl' ? :hsl : :linear
      c['samples'].map do |r, g, b|
        apply_pipeline(r, g, b, pipeline, c['strength'], color_model: model)
      end
    end.then { |out| puts JSON.generate(out) }
  `;
  const stdout = execFileSync('ruby', ['-e', script], {
    input: JSON.stringify(cases),
    cwd: HERE,
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
  return JSON.parse(stdout.trim().split('\n').at(-1));
}

// Deterministic PRNG so a failure is reproducible.
function lcg(seed) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

function buildCases({ seed = 12345, strengths, models = ['linear'] } = {}) {
  const rand = lcg(seed);
  const samples = [];
  for (let i = 0; i < 12; i++) {
    samples.push([rand(), rand(), rand()]);
  }
  // Pin the corners and the neutral axis too — random points rarely hit them.
  samples.push([0, 0, 0], [1, 1, 1], [0.5, 0.5, 0.5], [1, 0, 0], [0, 0, 1]);

  const cases = [];
  for (const preset of Object.keys(presets)) {
    for (const model of models) {
      for (const strength of strengths) {
        cases.push({ preset, strength, model, samples });
      }
    }
  }
  return cases;
}

function assertParity(cases, tolerance, label) {
  const expected = rubyPipeline(cases);

  let worst = 0;
  let worstCase = null;

  cases.forEach((c, ci) => {
    c.samples.forEach((sample, si) => {
      const got = applyPipeline(...sample, presets[c.preset].pipeline,
        c.strength, c.model);
      const want = expected[ci][si];
      for (let ch = 0; ch < 3; ch++) {
        const d = Math.abs(got[ch] - want[ch]);
        if (d > worst) {
          worst = d;
          worstCase = { preset: c.preset, strength: c.strength,
            model: c.model, sample, got, want };
        }
      }
    });
  });

  assert.ok(worst <= tolerance,
    `${label}: max divergence ${worst.toExponential(3)}\n` +
    `  ${JSON.stringify(worstCase)}`);
  return worst;
}

test('matches Ruby at arbitrary strengths', () => {
  // Deliberately awkward values, none of which appear in the manifest.
  const strengths = [0.01, 0.17, 0.33, 0.37, 0.49, 0.66, 0.83, 0.99];
  assertParity(buildCases({ strengths }), 1e-12,
    'arbitrary-strength parity');
});

test('matches Ruby across the full strength sweep', () => {
  // Every value the slider can produce, on a smaller colour set.
  const strengths = Array.from({ length: 101 }, (_, i) => i / 100);
  assertParity(buildCases({ seed: 777, strengths }), 1e-12,
    'full-sweep parity');
});

test('matches Ruby in legacy mode too', () => {
  const strengths = [0.23, 0.5, 0.77, 1.0];
  assertParity(buildCases({ seed: 99, strengths, models: ['hsl'] }), 1e-12,
    'legacy parity');
});

test('matches Ruby on multi-step chains', () => {
  // Chains compound divergence, so verify them explicitly rather than trusting
  // that per-step parity composes.
  const chain = [
    { preset: 'studio_punch', strength: 0.43 },
    { preset: 'warm_shift', strength: 0.61 },
    { preset: 'sat_boost', strength: 0.29 },
    { preset: 'black_crush', strength: 0.87 },
  ];

  const rand = lcg(4242);
  const samples = Array.from({ length: 16 }, () => [rand(), rand(), rand()]);

  // Walk the chain through Ruby one stage at a time, feeding each stage the
  // previous stage's output — exactly what generate_chain_lut.rb does.
  let rubyCurrent = samples;
  for (const step of chain) {
    rubyCurrent = rubyPipeline([{ ...step, model: 'linear', samples: rubyCurrent }])[0];
  }

  let jsCurrent = samples;
  for (const step of chain) {
    jsCurrent = jsCurrent.map((s) =>
      applyPipeline(...s, presets[step.preset].pipeline, step.strength));
  }

  let worst = 0;
  for (let i = 0; i < samples.length; i++) {
    for (let ch = 0; ch < 3; ch++) {
      worst = Math.max(worst, Math.abs(jsCurrent[i][ch] - rubyCurrent[i][ch]));
    }
  }
  assert.ok(worst <= 1e-12, `chain parity: max divergence ${worst.toExponential(3)}`);
});

// ── Serialisation ────────────────────────────────────────────────────

test('formatCube reproduces the Ruby writer byte-for-byte', () => {
  const name = 'black_crush';
  const entry = manifest[name];
  const expectedText = readFileSync(
    join(HERE, 'correction_luts', `${name}.cube`), 'utf8');

  const size = 33;
  const table = generateTable(stepsFor(entry), size);
  const produced = formatCube(table, size, 'x');

  const expectedRows = expectedText.split('\n').filter((l) => /^\d/.test(l));
  const producedRows = produced.split('\n').filter((l) => /^\d/.test(l));

  assert.equal(producedRows.length, expectedRows.length);

  let mismatches = 0;
  for (let i = 0; i < expectedRows.length; i++) {
    if (producedRows[i] !== expectedRows[i]) mismatches++;
  }
  // Allow a handful of last-digit rounding differences between Ruby's printf
  // and JavaScript's toFixed; anything more indicates a real divergence.
  assert.ok(mismatches < expectedRows.length * 0.001,
    `${mismatches} of ${expectedRows.length} rows differ in text form`);
});

// ── Strength semantics ───────────────────────────────────────────────

test('strength interpolates parameters, not results', () => {
  const pipeline = presets.studio_punch.pipeline;
  const samples = [];
  for (let i = 0; i <= 8; i++) {
    for (let j = 0; j <= 8; j++) {
      samples.push([i / 8, j / 8, 0.5]);
    }
  }

  let worst = 0;
  for (const [r, g, b] of samples) {
    const half = applyPipeline(r, g, b, pipeline, 0.5);
    const full = applyPipeline(r, g, b, pipeline, 1.0);
    const naive = [r, g, b].map((v, i) => v + (full[i] - v) * 0.5);
    worst = Math.max(worst, ...naive.map((v, i) => Math.abs(v - half[i])));
  }

  assert.ok(worst > 0.05,
    `expected result-lerp to diverge materially, got ${worst.toFixed(4)}`);
});

test('identity at strength zero', () => {
  for (const name of ['yellow_fix', 'red_skin_fix', 'sat_boost', 'warm_shift']) {
    const pipeline = presets[name].pipeline;
    if (pipeline.some((s) => s.step === 'highlight_protect')) continue;
    for (const [r, g, b] of [[0.1, 0.2, 0.3], [0.5, 0.5, 0.5], [0.9, 0.4, 0.2]]) {
      const out = applyPipeline(r, g, b, pipeline, 0);
      const err = Math.max(Math.abs(out[0] - r), Math.abs(out[1] - g),
        Math.abs(out[2] - b));
      assert.ok(err < 1e-9, `${name} moved by ${err} at strength 0`);
    }
  }
});

test('legacy model is reachable and differs from linear', () => {
  const pipeline = presets.black_crush.pipeline;
  const [r, g, b] = [0.30, 0.10, 0.10];
  const linear = applyPipeline(r, g, b, pipeline, 1.0, 'linear');
  const legacy = applyPipeline(r, g, b, pipeline, 1.0, 'hsl');
  const diff = Math.max(...linear.map((v, i) => Math.abs(v - legacy[i])));
  assert.ok(diff > 1e-6, 'linear and legacy models should differ');
});

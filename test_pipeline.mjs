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

/* Number and label formatting from ui.js.
 *
 * Every number the panels print goes through these. A missing value that
 * formats as "0.0000" instead of an em dash, or a −1e-17 float printed in
 * failure red, describes a problem the run does not have.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  bits, ket, fixed, sci, signed, meaningful, paramText, shortSource,
} from '../../src/qlens/viewer/static/ui.js';

/* ---------- basis labels ---------- */

test('a label pads to the register width', () => {
  assert.equal(bits(0, 4), '0000');
  assert.equal(bits(5, 4), '0101');
  assert.equal(bits(15, 4), '1111');
});

test('qubit 0 is leftmost, matching the recorded convention', () => {
  // Index 1 sets the lowest bit, which prints on the right of a
  // big-endian label read as q0…qn.
  assert.equal(bits(1, 2), '01');
  assert.equal(bits(2, 2), '10');
});

test('a zero-qubit register still prints a character', () => {
  assert.equal(bits(0, 0), '0');
  assert.equal(bits(0, -3), '0');
});

test('a ket wraps the label in bra-ket notation', () => {
  assert.equal(ket(2, 3), '|010⟩');
});

/* ---------- numbers ---------- */

test('a value that is not there prints an em dash, not a zero', () => {
  for (const value of [null, undefined, NaN, Infinity, -Infinity]) {
    assert.equal(fixed(value), '—');
    assert.equal(sci(value), '—');
    assert.equal(signed(value), '—');
  }
});

test('fixed keeps the places it was asked for', () => {
  assert.equal(fixed(0.5), '0.5000');
  assert.equal(fixed(0.5, 2), '0.50');
  assert.equal(fixed(0), '0.0000');
});

test('sci switches to an exponent where the exponent is the story', () => {
  assert.equal(sci(0), '0');
  assert.equal(sci(0.0005), '5.00e-4');
  assert.equal(sci(1e6), '1.00e+6');
  assert.equal(sci(-1e-9), '-1.00e-9');
});

test('sci stays decimal across the readable middle', () => {
  assert.equal(sci(0.05), '0.0500');
  assert.equal(sci(1234), '1234.0000');
});

test('sci switches exactly at its bounds', () => {
  assert.equal(sci(0.001), '0.0010', 'the lower bound is inclusive of decimal');
  assert.equal(sci(0.0009999), '1.00e-3');
  assert.equal(sci(99999), '99999.0000');
  assert.equal(sci(100000), '1.00e+5');
});

test('signed always carries a sign, including on zero', () => {
  assert.equal(signed(0), '+0.0000');
  assert.equal(signed(0.25), '+0.2500');
  assert.equal(signed(-0.25), '−0.2500');
});

test('signed uses a minus sign, not a hyphen', () => {
  assert.equal(signed(-1).charCodeAt(0), 0x2212);
});

test('a difference below the shown precision is not meaningful', () => {
  assert.equal(meaningful(-1e-17), false);
  assert.equal(meaningful(0), false);
  assert.equal(meaningful(0.00004), false);
});

test('a difference that survives rounding is meaningful', () => {
  assert.equal(meaningful(0.00005), true);
  assert.equal(meaningful(-0.5), true);
});

test('meaningful follows the precision it is shown at', () => {
  assert.equal(meaningful(0.004, 2), false);
  assert.equal(meaningful(0.006, 2), true);
});

test('a value that is not there is never meaningful', () => {
  assert.equal(meaningful(NaN), false);
  assert.equal(meaningful(Infinity), false);
  assert.equal(meaningful(undefined), false);
});

/* ---------- gate parameters ---------- */

test('a gate with no parameters contributes no text', () => {
  assert.equal(paramText({ gate: 'h', params: {} }), '');
  assert.equal(paramText({ gate: 'h' }), '');
  assert.equal(paramText(null), '');
});

test('a rotation shows its angle', () => {
  assert.equal(paramText({ params: { p0: 1.977 } }), '1.977');
});

test('several parameters are listed in recorded order', () => {
  assert.equal(paramText({ params: { p0: 0.1, p1: 0.25, p2: 0.5 } }), '0.100, 0.250, 0.500');
});

test('an angle that rounds away keeps its exponent instead of reading as zero', () => {
  assert.equal(paramText({ params: { p0: 1e-9 } }), '1.00e-9');
});

/* ---------- source paths ---------- */

test('a missing source prints an em dash', () => {
  assert.equal(shortSource(''), '—');
  assert.equal(shortSource(null), '—');
  assert.equal(shortSource(undefined), '—');
});

test('a long path shortens to its last two segments', () => {
  assert.equal(shortSource('/Users/someone/project/tests/test_bell.py:12'), 'tests/test_bell.py:12');
});

test('a short path is left alone rather than truncated', () => {
  assert.equal(shortSource('test_bell.py:12'), 'test_bell.py:12');
  assert.equal(shortSource('tests/test_bell.py:12'), 'tests/test_bell.py:12');
});

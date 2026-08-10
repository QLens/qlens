/* Colour mapping and pointer arithmetic from draw.js.
 *
 * The canvas painting itself needs a browser, but everything that decides
 * what colour a cell gets, and which bar a pointer is over, is arithmetic
 * and belongs under test. A hue that wraps to the wrong side of the wheel
 * or a bar index off by one is invisible in a screenshot of a run nobody
 * has ground truth for.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  oklchToRgb, phaseColor, decodePlane, barAtPointer,
} from '../../src/qlens/viewer/static/draw.js';

const canvas = (left, width) => ({ getBoundingClientRect: () => ({ left, width }) });

/* ---------- OKLCH ---------- */

test('every channel lands in byte range, including out of gamut input', () => {
  for (const hue of [0, 45, 120, 210, 359]) {
    for (const chroma of [0, 0.13, 0.4]) {
      for (const lightness of [0, 0.5, 1]) {
        for (const channel of oklchToRgb(lightness, chroma, hue)) {
          assert.ok(Number.isInteger(channel), `${channel} is not an integer`);
          assert.ok(channel >= 0 && channel <= 255, `${channel} out of range`);
        }
      }
    }
  }
});

test('zero lightness and no chroma is black whatever the hue', () => {
  for (const hue of [0, 90, 180, 270]) {
    assert.deepEqual(oklchToRgb(0, 0, hue), [0, 0, 0]);
  }
});

test('zero chroma is grey: the channels agree', () => {
  const [r, g, b] = oklchToRgb(0.6, 0, 200);
  assert.equal(r, g);
  assert.equal(g, b);
  assert.ok(r > 0 && r < 255, 'a mid lightness should not clip');
});

test('the hue wheel wraps, so 0 and 360 are the same colour', () => {
  assert.deepEqual(oklchToRgb(0.7, 0.13, 0), oklchToRgb(0.7, 0.13, 360));
});

test('hue moves the colour: 0 and 180 are not the same', () => {
  assert.notDeepEqual(oklchToRgb(0.7, 0.13, 0), oklchToRgb(0.7, 0.13, 180));
});

test('the wheel lands each hue on the channel it names', () => {
  // A guard against a sign flip in the a/b axes, which would still
  // produce colours that look plausible one at a time.
  const dominant = (hue) => {
    const rgb = oklchToRgb(0.7, 0.13, hue);
    return rgb.indexOf(Math.max(...rgb));
  };
  assert.equal(dominant(30), 0, 'hue 30 should be reddest');
  assert.equal(dominant(150), 1, 'hue 150 should be greenest');
  assert.equal(dominant(270), 2, 'hue 270 should be bluest');
});

test('more lightness is a brighter colour at fixed hue', () => {
  const dim = oklchToRgb(0.3, 0.1, 200).reduce((a, b) => a + b, 0);
  const bright = oklchToRgb(0.9, 0.1, 200).reduce((a, b) => a + b, 0);
  assert.ok(bright > dim);
});

test('phaseColor emits the token values it was handed, not its own', () => {
  const tokens = { css: { lightness: '78%', chroma: '0.13' } };
  assert.equal(phaseColor(210, tokens), 'oklch(78% 0.13 210)');
});

/* ---------- plane decoding ---------- */

test('an empty plane decodes to an empty array rather than throwing', () => {
  assert.equal(decodePlane('').length, 0);
});

test('a plane decodes to the bytes the server encoded', () => {
  const bytes = [0, 1, 127, 128, 254, 255];
  const base64 = Buffer.from(bytes).toString('base64');
  assert.deepEqual([...decodePlane(base64)], bytes);
});

test('decoded bytes are unsigned, so 255 is not -1', () => {
  const plane = decodePlane(Buffer.from([255]).toString('base64'));
  assert.ok(plane instanceof Uint8Array);
  assert.equal(plane[0], 255);
});

/* ---------- pointer to bar ---------- */

test('a collapsed canvas has no bar under the pointer', () => {
  assert.equal(barAtPointer({ clientX: 50 }, canvas(0, 0), 8), null);
});

test('a canvas with no bars has none under the pointer', () => {
  assert.equal(barAtPointer({ clientX: 50 }, canvas(0, 100), 0), null);
});

test('a pointer outside either end is off the chart', () => {
  assert.equal(barAtPointer({ clientX: -5 }, canvas(0, 100), 4), null);
  assert.equal(barAtPointer({ clientX: 150 }, canvas(0, 100), 4), null);
});

test('the ends of the chart are the first and last bar', () => {
  assert.equal(barAtPointer({ clientX: 0 }, canvas(0, 100), 4), 0);
  assert.equal(barAtPointer({ clientX: 99.9 }, canvas(0, 100), 4), 3);
});

test('a bar is picked by position across the canvas', () => {
  const at = (x) => barAtPointer({ clientX: x }, canvas(0, 100), 4);
  assert.equal(at(10), 0);
  assert.equal(at(30), 1);
  assert.equal(at(60), 2);
  assert.equal(at(80), 3);
});

test('the canvas offset is subtracted, not ignored', () => {
  // The same pointer x over a canvas that starts at 200 is the first bar,
  // not the one 200 pixels in.
  assert.equal(barAtPointer({ clientX: 205 }, canvas(200, 100), 4), 0);
});

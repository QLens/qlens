/* The viewer's decisions about recorded data.
 *
 * Failure and edge cases first: an empty run, checks with no position,
 * two checks on one position, a stale selection. Those are the states a
 * screenshot of a healthy run never shows.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  assertionDetail, isUnreliable, gateText, alongside, sortValue, sortRows,
  rankExpectations, chooseExpectation, expectationLabel, expectedVector,
  rankDivergences, coveragePercent, besideAnchor,
  positionAxis, columnX, inView, columnIndex, zoomRange, panRange, rangeFromFractions,
} from '../../src/qlens/viewer/static/logic.js';

const check = (overrides = {}) => ({
  assertion: 'assert_distribution',
  status: 'completed',
  position: 0,
  ...overrides,
});

/* ---------- gate labels ---------- */

test('a column with no gate reads as absent, not as a crash', () => {
  assert.equal(gateText(null), '—');
  assert.equal(gateText(undefined), '—');
});

test('a gate is labelled with the wires it acted on', () => {
  assert.equal(gateText({ gate: 'h', qubits: [0] }), 'h(q0)');
  assert.equal(gateText({ gate: 'cx', qubits: [3, 4] }), 'cx(q3,q4)');
  assert.equal(gateText({ gate: 'ccx', qubits: [0, 1, 2] }), 'ccx(q0,q1,q2)');
});

test('control order is preserved, since cx(q3,q4) is not cx(q4,q3)', () => {
  assert.equal(gateText({ gate: 'cx', qubits: [4, 3] }), 'cx(q4,q3)');
});

test('a gate on no wires is just its name', () => {
  assert.equal(gateText({ gate: 'initial', qubits: [] }), 'initial');
  assert.equal(gateText({ gate: 'initial' }), 'initial');
});

/* ---------- what runs together ---------- */

const layer = (positions) => ({
  index: 0,
  gates: positions.map((position) => ({ gate: 'h', qubits: [position], position })),
});

test('a position with no layer has nothing running alongside it', () => {
  assert.deepEqual(alongside(null, 3), []);
  assert.deepEqual(alongside(undefined, 3), []);
  assert.deepEqual(alongside({}, 3), []);
});

test('the gate under the cursor is not listed as running alongside itself', () => {
  const others = alongside(layer([0, 1, 2]), 1);
  assert.deepEqual(others.map((g) => g.position), [0, 2]);
});

test('a lone gate in its layer runs alongside nothing', () => {
  assert.deepEqual(alongside(layer([7]), 7), []);
});

test('a position from another layer leaves the whole layer listed', () => {
  assert.equal(alongside(layer([0, 1, 2]), 99).length, 3);
});

/* ---------- ranking expectations ---------- */

test('a run with no assertions ranks nothing', () => {
  assert.deepEqual(rankExpectations([], 0), []);
  assert.deepEqual(rankExpectations(undefined, 0), []);
});

test('checks that recorded no expectation are not candidates', () => {
  const ranked = rankExpectations([check(), check({ expected: { '0': 1 } })], 0);
  assert.equal(ranked.length, 1);
  assert.equal(ranked[0].key, 1, 'the key must index the original array, not the filtered one');
});

test('two checks on one position put the failing one first', () => {
  const passing = check({ position: 208, status: 'completed', expected: { '000000': 1 } });
  const failing = check({ position: 208, status: 'failed', expected: { '000000': 0.5 } });
  const ranked = rankExpectations([passing, failing], 208);
  assert.equal(ranked[0].a, failing);
  assert.equal(ranked[0].key, 1);
});

test('the failing check wins even when it was recorded first', () => {
  const failing = check({ position: 4, status: 'failed', expected: { '00': 1 } });
  const passing = check({ position: 4, status: 'completed', expected: { '00': 1 } });
  assert.equal(rankExpectations([failing, passing], 4)[0].a, failing);
});

test('a nearer passing check outranks a distant failing one', () => {
  const near = check({ position: 10, status: 'completed', expected: { '00': 1 } });
  const far = check({ position: 90, status: 'failed', expected: { '00': 1 } });
  assert.equal(rankExpectations([far, near], 12)[0].a, near);
});

test('distance is absolute, so a check just behind the cursor can win', () => {
  const behind = check({ position: 9, expected: { '00': 1 } });
  const ahead = check({ position: 30, expected: { '00': 1 } });
  assert.equal(rankExpectations([ahead, behind], 10)[0].a, behind);
});

test('a check with no position ranks last rather than as position zero', () => {
  const positioned = check({ position: 500, expected: { '00': 1 } });
  const floating = check({ position: null, expected: { '00': 1 } });
  const ranked = rankExpectations([floating, positioned], 0);
  assert.equal(ranked[0].a, positioned);
  assert.equal(ranked[1].a, floating);
});

test('recorded order breaks a tie nothing else settles', () => {
  const first = check({ position: 3, expected: { '00': 1 } });
  const second = check({ position: 3, expected: { '11': 1 } });
  const ranked = rankExpectations([first, second], 3);
  assert.deepEqual(ranked.map((r) => r.key), [0, 1]);
});

/* ---------- choosing one ---------- */

test('nothing to choose from is null, not a crash', () => {
  assert.equal(chooseExpectation([], 0), null);
});

test('a stale key falls back to the best candidate', () => {
  const candidates = rankExpectations([check({ expected: { '0': 1 } })], 0);
  assert.equal(chooseExpectation(candidates, 99), candidates[0]);
});

test('a live key wins over the automatic pick', () => {
  const passing = check({ position: 208, expected: { '000000': 1 } });
  const failing = check({ position: 208, status: 'failed', expected: { '000000': 0.5 } });
  const candidates = rankExpectations([passing, failing], 208);
  assert.equal(chooseExpectation(candidates, 0).a, passing);
});

test('the picker names the method, since two checks can share a position', () => {
  assert.equal(
    expectationLabel({ a: check({ method: 'chi_square', status: 'failed' }) }),
    'chi_square · failed',
  );
  assert.equal(
    expectationLabel({ a: check({ method: 'tvd' }) }),
    'tvd',
  );
  assert.equal(
    expectationLabel({ a: check({ assertion: 'assert_state' }) }),
    'assert_state',
    'a check with no recorded method falls back to its name',
  );
});

/* ---------- expanding an expectation ---------- */

test('a check that recorded no expectation expands to null', () => {
  assert.equal(expectedVector(check(), 2), null);
  assert.equal(expectedVector(undefined, 2), null);
});

test('labels map big-endian, qubit 0 leftmost', () => {
  // "01" is qubit 0 low, qubit 1 high, which is basis index 1.
  assert.deepEqual(expectedVector(check({ expected: { '01': 1 } }), 2), [0, 1, 0, 0]);
  assert.deepEqual(expectedVector(check({ expected: { '10': 1 } }), 2), [0, 0, 1, 0]);
});

test('a sparse expectation fills the rest with zero, not undefined', () => {
  const vector = expectedVector(check({ expected: { '000': 0.5, '111': 0.5 } }), 3);
  assert.equal(vector.length, 8);
  assert.deepEqual(vector, [0.5, 0, 0, 0, 0, 0, 0, 0.5]);
  assert.ok(vector.every((v) => typeof v === 'number'));
});

test('a label too wide for the basis is dropped rather than wrapping', () => {
  const vector = expectedVector(check({ expected: { '1111': 1, '01': 0.5 } }), 2);
  assert.deepEqual(vector, [0, 0.5, 0, 0]);
});

test('a label that is not binary is ignored', () => {
  assert.deepEqual(expectedVector(check({ expected: { zzz: 1 } }), 2), [0, 0, 0, 0]);
});

/* ---------- divergences ---------- */

test('with no expectation the rows rank by probability', () => {
  const rows = rankDivergences([0.1, 0.7, 0.2], null, null);
  assert.deepEqual(rows.map((r) => r.index), [1, 2, 0]);
  assert.ok(rows.every((r) => r.delta === null));
});

test('with an expectation the rows rank by absolute divergence', () => {
  const rows = rankDivergences([0.1, 0.4, 0.5], [0.1, 0.9, 0.5], null);
  assert.equal(rows[0].index, 1);
  assert.equal(rows[0].delta, -0.5);
});

test('a negative divergence outranks a smaller positive one', () => {
  const rows = rankDivergences([0.0, 0.3], [0.6, 0.0], null);
  assert.deepEqual(rows.map((r) => r.index), [0, 1]);
});

test('probability breaks ties when a check matched the run exactly', () => {
  // Every delta is zero, which used to leave the list in index order and
  // read as a broken panel.
  const rows = rankDivergences([0.1, 0.6, 0.3], [0.1, 0.6, 0.3], null);
  assert.deepEqual(rows.map((r) => r.index), [1, 2, 0]);
});

test('the row list is capped', () => {
  const many = Array.from({ length: 64 }, (unused, i) => i / 64);
  assert.equal(rankDivergences(many, null, null).length, 16);
  assert.equal(rankDivergences(many, null, null, 4).length, 4);
});

/* ---------- sorting the table ---------- */

test('no sort key keeps the recorded order', () => {
  const rows = sortRows([check({ position: 9 }), check({ position: 1 })], {});
  assert.deepEqual(rows.map((r) => r.index), [0, 1]);
});

test('position sorts numerically, not as text', () => {
  const rows = sortRows(
    [check({ position: 100 }), check({ position: 9 })],
    { key: 'position', direction: 1 },
  );
  assert.deepEqual(rows.map((r) => r.a.position), [9, 100]);
});

test('an unpositioned check stays last in both directions', () => {
  const list = [check({ position: null }), check({ position: 5 }), check({ position: 1 })];
  assert.deepEqual(
    sortRows(list, { key: 'position', direction: 1 }).map((r) => r.a.position),
    [1, 5, null],
  );
  assert.deepEqual(
    sortRows(list, { key: 'position', direction: -1 }).map((r) => r.a.position),
    [5, 1, null],
  );
});

test('sorting is stable, so equal rows keep recorded order', () => {
  const list = [
    check({ position: 1, source: 'b.py:1' }),
    check({ position: 1, source: 'a.py:1' }),
    check({ position: 1, source: 'c.py:1' }),
  ];
  const rows = sortRows(list, { key: 'position', direction: 1 });
  assert.deepEqual(rows.map((r) => r.index), [0, 1, 2]);
});

test('text columns compare case-insensitively', () => {
  const rows = sortRows(
    [check({ source: 'Zeta.py:1' }), check({ source: 'alpha.py:1' })],
    { key: 'source', direction: 1 },
  );
  assert.deepEqual(rows.map((r) => r.a.source), ['alpha.py:1', 'Zeta.py:1']);
});

test('a missing source sorts as empty rather than the string "undefined"', () => {
  assert.equal(sortValue(check(), 'source'), '');
  assert.equal(sortValue(check(), 'method'), '');
});

test('the detail column sorts on the text the table shows', () => {
  const failing = check({ status: 'failed', error: { message: 'Alpha mismatch' } });
  assert.equal(sortValue(failing, 'detail'), 'alpha mismatch');
});

/* ---------- detail text ---------- */

test('a failure shows its own message rather than a generic line', () => {
  assert.equal(
    assertionDetail(check({ status: 'failed', error: { message: 'p-value 0 < 0.05' } })),
    'p-value 0 < 0.05',
  );
});

test('each passing check gets a line describing what it proved', () => {
  assert.match(assertionDetail(check()), /distribution/);
  assert.match(assertionDetail(check({ assertion: 'assert_unitary' })), /identity/);
  assert.match(assertionDetail(check({ assertion: 'assert_equivalent' })), /same unitary/);
  assert.equal(assertionDetail(check({ assertion: 'assert_state' })), 'passed');
});

test('unreliable means the verdict said so, not that the field is absent', () => {
  assert.equal(isUnreliable(check()), false);
  assert.equal(isUnreliable(undefined), false);
  assert.equal(isUnreliable(check({ reliability: { reliable: true } })), false);
  assert.equal(isUnreliable(check({ reliability: { reliable: false } })), true);
});

/* ---------- geometry ---------- */

test('a mark at either end stays inside the track', () => {
  assert.equal(coveragePercent(0, 10), 'calc(2px + 0% - 0px)');
  assert.equal(coveragePercent(10, 10), 'calc(2px + 100% - 4px)');
});

test('a note beside an anchor sits to the right when there is room', () => {
  assert.equal(besideAnchor(100, 200, 1000), 128);
});

test('an anchor near the right edge flips its note to the left', () => {
  assert.equal(besideAnchor(950, 200, 1000), 722);
});

test('a note wider than the frame clamps rather than going off-screen', () => {
  assert.equal(besideAnchor(10, 900, 400), 8);
});

/* ---------- viewport ---------- */

const wf = (over = {}) => ({ num_positions: 100, kept_rows: 64, ...over });

test('a payload with no viewport covers the whole run', () => {
  const axis = positionAxis(wf());
  assert.deepEqual(
    { from: axis.from, to: axis.to, columns: axis.columns, zoomed: axis.zoomed },
    { from: 0, to: 100, columns: 100, zoomed: false },
  );
});

test('a missing payload does not throw, it just spans nothing', () => {
  const axis = positionAxis(null);
  assert.equal(axis.total, 0);
  assert.equal(axis.columns, 1, 'never zero, since callers divide by it');
});

test('a served viewport is the axis, not the run', () => {
  const axis = positionAxis(wf({ view: { pos_from: 40, pos_to: 60 } }));
  assert.equal(axis.columns, 20);
  assert.equal(axis.zoomed, true);
  assert.equal(axis.total, 100, 'the run is still 100 positions long');
});

test('the first and last columns of a zoomed field sit inside it', () => {
  const axis = positionAxis(wf({ view: { pos_from: 40, pos_to: 60 } }));
  assert.equal(columnX(40, axis, 200), 5, 'first column, half a slot in');
  assert.equal(columnX(59, axis, 200), 195);
});

test('a position outside the viewport is not drawn', () => {
  const axis = positionAxis(wf({ view: { pos_from: 40, pos_to: 60 } }));
  assert.equal(inView(39, axis), false);
  assert.equal(inView(40, axis), true);
  assert.equal(inView(59, axis), true);
  assert.equal(inView(60, axis), false, 'the range is half-open');
});

test('a column of the served field maps back to a run-wide position', () => {
  const axis = positionAxis(wf({ view: { pos_from: 40, pos_to: 60 } }));
  assert.equal(columnIndex(0, axis), 40);
  assert.equal(columnIndex(19, axis), 59);
});

/* ---------- zooming ---------- */

test('zooming in holds the point under the cursor still', () => {
  // The cursor is a quarter across a 100-wide run, so position 25 stays
  // a quarter across the 50 that remain.
  const next = zoomRange({ from: 0, to: 100, total: 100, factor: 0.5, at: 0.25 });
  assert.deepEqual(next, { from: 13, to: 63 });
  assert.ok(Math.abs((25 - next.from) / (next.to - next.from) - 0.25) < 0.02);
});

test('zooming out past the run snaps back to the whole run', () => {
  const next = zoomRange({ from: 40, to: 60, total: 100, factor: 10, at: 0.5 });
  assert.deepEqual(next, { from: 0, to: 100 });
});

test('zooming in never goes below a readable span', () => {
  const next = zoomRange({ from: 0, to: 100, total: 100, factor: 0.001, at: 0.5, minimum: 4 });
  assert.equal(next.to - next.from, 4);
});

test('zooming at the very start does not run off the front', () => {
  const next = zoomRange({ from: 0, to: 100, total: 100, factor: 0.5, at: 0 });
  assert.equal(next.from, 0);
  assert.equal(next.to, 50);
});

test('zooming at the very end does not run off the back', () => {
  const next = zoomRange({ from: 0, to: 100, total: 100, factor: 0.5, at: 1 });
  assert.equal(next.to, 100);
  assert.equal(next.from, 50);
});

test('zooming out near the start does not open a range before position zero', () => {
  // Widening about the right-hand edge of a range that starts at zero
  // wants to grow backwards past the beginning of the run.
  const next = zoomRange({ from: 0, to: 20, total: 100, factor: 2, at: 1 });
  assert.equal(next.from, 0);
  assert.equal(next.to, 40);
});

test('zooming out near the end does not open a range past the last position', () => {
  const next = zoomRange({ from: 80, to: 100, total: 100, factor: 2, at: 0 });
  assert.equal(next.to, 100);
  assert.equal(next.from, 60);
});

test('zooming a run shorter than the minimum span stays inside it', () => {
  const next = zoomRange({ from: 0, to: 3, total: 3, factor: 0.5, at: 0.5, minimum: 4 });
  assert.deepEqual(next, { from: 0, to: 3 });
});

/* ---------- panning ---------- */

test('panning keeps the width and stops at the ends', () => {
  assert.deepEqual(panRange({ from: 40, to: 60, total: 100, by: 10 }), { from: 50, to: 70 });
  assert.deepEqual(panRange({ from: 40, to: 60, total: 100, by: -100 }), { from: 0, to: 20 });
  assert.deepEqual(panRange({ from: 40, to: 60, total: 100, by: 900 }), { from: 80, to: 100 });
});

/* ---------- framing a region ---------- */

test('a drag right to left frames the same region as left to right', () => {
  const forward = rangeFromFractions({ from: 0, to: 100, total: 100, a: 0.2, b: 0.6 });
  const backward = rangeFromFractions({ from: 0, to: 100, total: 100, a: 0.6, b: 0.2 });
  assert.deepEqual(forward, backward);
  assert.deepEqual(forward, { from: 20, to: 60 });
});

test('framing inside an already zoomed field is relative to that field', () => {
  const next = rangeFromFractions({ from: 40, to: 60, total: 100, a: 0, b: 0.5 });
  assert.deepEqual(next, { from: 40, to: 50 });
});

test('a flick rather than a drag grows to a span worth showing', () => {
  const next = rangeFromFractions({ from: 0, to: 100, total: 100, a: 0.5, b: 0.502, minimum: 4 });
  assert.equal(next.to - next.from, 4);
});

test('a flick at the very end still yields a span inside the run', () => {
  const next = rangeFromFractions({ from: 0, to: 100, total: 100, a: 1, b: 1, minimum: 4 });
  assert.equal(next.to, 100);
  assert.equal(next.from, 96);
});

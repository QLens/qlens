/* Decisions the viewer makes about recorded data, with no DOM in sight.
 *
 * Ordering assertions, choosing which recorded expectation to measure a
 * statevector against, expanding a sparse expectation onto the basis:
 * these are the parts that can be wrong in ways a screenshot does not
 * show. Keeping them here, taking plain data and returning plain data,
 * is what lets `node --test` cover them without a browser.
 */

/* ---------- gates ---------- */

/** A gate written the way a circuit diagram would label it: the canonical
 *  name with the wires it acted on. */
export function gateText(gate) {
  if (!gate) return '—';
  const qubits = (gate.qubits || []).map((q) => `q${q}`).join(',');
  return qubits ? `${gate.gate}(${qubits})` : gate.gate;
}

/** The gates in a layer other than the one at `position`.
 *
 *  A layer's gates share no qubit and so run together, which makes them
 *  the answer to what else is happening at a point in the run rather than
 *  merely what else is nearby. */
export function alongside(layer, position) {
  return (layer?.gates || []).filter((gate) => gate.position !== position);
}

/* ---------- assertions ---------- */

/** The one-line summary a check gets in the table, and what the detail
 *  column sorts on. */
export function assertionDetail(assertion) {
  if (assertion.error?.message) return assertion.error.message;
  if (assertion.assertion === 'assert_distribution') return 'observed distribution within tolerance';
  if (assertion.assertion === 'assert_unitary') return 'U†U is the identity within tolerance';
  if (assertion.assertion === 'assert_equivalent') return 'both circuits compute the same unitary';
  return 'passed';
}

export const isUnreliable = (assertion) => assertion?.reliability?.reliable === false;

/** The value a column sorts on. Position sorts numerically; an absent
 *  position sorts last rather than as zero, which would put unpositioned
 *  checks among the earliest gates. */
export function sortValue(assertion, key) {
  if (key === 'position') {
    const value = assertion.position;
    return value === null || value === undefined ? Number.POSITIVE_INFINITY : value;
  }
  if (key === 'detail') return assertionDetail(assertion).toLowerCase();
  if (key === 'source') return (assertion.source || '').toLowerCase();
  return String(assertion[key] ?? '').toLowerCase();
}

/** Rows in display order, each keeping the index it was recorded under so
 *  a sorted table can still address the underlying check.
 *
 *  Rows that compare equal keep recorded order, which re-sorting the same
 *  column therefore never reshuffles. That comes from Array.prototype.sort
 *  being stable, required since ES2019; a comparator tiebreak on the
 *  recorded index would only restate it.
 */
export function sortRows(assertions, { key, direction } = {}) {
  const rows = assertions.map((a, index) => ({ a, index }));
  if (!key) return rows;
  // A check with no position is absent from the run's axis, not late in
  // it, so it belongs at the end whichever way the column points.
  const missing = (row) => key === 'position'
    && (row.a.position === null || row.a.position === undefined);
  rows.sort((x, y) => {
    if (missing(x) !== missing(y)) return missing(x) ? 1 : -1;
    const left = sortValue(x.a, key);
    const right = sortValue(y.a, key);
    if (left < right) return -direction;
    if (left > right) return direction;
    return 0;
  });
  return rows;
}

/* ---------- expectations ---------- */

/** Every check that recorded an expected distribution, in the order the
 *  State tab prefers to overlay them: nearest the cursor first, and among
 *  checks at one position the failing one first.
 *
 *  The tiebreak is the point. Two checks can sit on the same position —
 *  one passing, one failing — and overlaying the passing one prints a
 *  column of +0.0000 deltas that read as a broken panel rather than as a
 *  check the run agreed with. Whoever opened the State tab after a
 *  failure came to see the divergence.
 */
export function rankExpectations(assertions, cursorPosition) {
  const distance = (a) => (
    a.position === null || a.position === undefined
      ? Infinity
      : Math.abs(a.position - cursorPosition)
  );
  return (assertions || [])
    .map((a, key) => ({ a, key }))
    .filter(({ a }) => a.expected)
    // Recorded order breaks whatever these two do not, by way of a stable
    // sort rather than a third comparator term.
    .sort((x, y) => (
      distance(x.a) - distance(y.a)
      || (y.a.status === 'failed') - (x.a.status === 'failed')
    ));
}

/** The ranked candidate the reader chose, falling back to the best one.
 *  A stale choice — a key from a run that is no longer on screen — falls
 *  back rather than blanking the overlay. */
export function chooseExpectation(candidates, chosenKey) {
  if (!candidates.length) return null;
  return candidates.find(({ key }) => key === chosenKey) || candidates[0];
}

/** Names a candidate in the overlay picker, distinguishing checks that
 *  share a position by the method that produced them. */
export const expectationLabel = ({ a }) =>
  `${a.method || a.assertion}${a.status === 'failed' ? ' · failed' : ''}`;

/** A recorded expectation expanded onto the full basis so it lines up
 *  with the observed bars. Labels are big-endian bitstrings, matching the
 *  convention every backend converts to. */
export function expectedVector(assertion, numQubits) {
  const expected = assertion?.expected;
  if (!expected) return null;
  const size = 1 << numQubits;
  const vector = new Array(size).fill(0);
  for (const [label, probability] of Object.entries(expected)) {
    const index = parseInt(label, 2);
    if (Number.isInteger(index) && index >= 0 && index < size) vector[index] = probability;
  }
  return vector;
}

/** The rows under the bars: biggest divergence from the overlaid
 *  expectation first, or biggest amplitude when nothing is overlaid.
 *  Probability breaks ties on delta, so a check the run agreed with lists
 *  its largest outcomes rather than an arbitrary handful. */
export function rankDivergences(probabilities, expected, hues, limit = 16) {
  return probabilities
    .map((probability, index) => ({
      index,
      hue: hues ? hues[index] : 0,
      probability,
      delta: expected ? probability - expected[index] : null,
    }))
    .sort((a, b) => (expected
      ? Math.abs(b.delta) - Math.abs(a.delta) || b.probability - a.probability
      : b.probability - a.probability))
    .slice(0, limit);
}

/* ---------- viewport ---------- */

/** The slice of the run the served waterfall covers, as an axis the
 *  drawing code can map through.
 *
 *  The run's own position list stays whole regardless: the transport
 *  spans the run, and only the field is zoomed. So everything drawn over
 *  the field converts a run-wide index through here rather than assuming
 *  column 0 is position 0.
 */
export function positionAxis(waterfall) {
  const total = waterfall?.num_positions ?? 0;
  const from = waterfall?.view?.pos_from ?? 0;
  const to = waterfall?.view?.pos_to ?? total;
  return { from, to, total, columns: Math.max(to - from, 1), zoomed: to - from < total };
}

/** Where a run-wide position index falls across a field of `width`. */
export const columnX = (index, axis, width) =>
  ((index - axis.from + 0.5) / axis.columns) * width;

export const inView = (index, axis) => index >= axis.from && index < axis.to;

/** The run-wide index a column of the served field stands for. */
export const columnIndex = (column, axis) => axis.from + column;

/** Zoom a range about a point, keeping that point under the cursor.
 *
 *  `at` is a fraction across the current span, so zooming holds whatever
 *  the pointer is over still rather than drifting toward the middle.
 *  Never returns a span below `minimum`, since a field of half a column
 *  is not a view of anything.
 */
export function zoomRange({ from, to, total, factor, at = 0.5, minimum = 4 }) {
  const span = to - from;
  const wanted = Math.max(minimum, Math.min(total, Math.round(span * factor)));
  if (wanted >= total) return { from: 0, to: total };
  const anchor = from + span * at;
  let start = Math.round(anchor - wanted * at);
  start = Math.max(0, Math.min(start, total - wanted));
  return { from: start, to: start + wanted };
}

/** Slide a range without changing its width, stopping at the ends. */
export function panRange({ from, to, total, by }) {
  const span = to - from;
  const start = Math.max(0, Math.min(Math.round(from + by), total - span));
  return { from: start, to: start + span };
}

/** A range from two fractions of the current span, in either drag order. */
export function rangeFromFractions({ from, to, total, a, b, minimum = 4 }) {
  const span = to - from;
  const low = from + span * Math.min(a, b);
  const high = from + span * Math.max(a, b);
  let start = Math.max(0, Math.round(low));
  let stop = Math.min(total, Math.round(high));
  if (stop - start < minimum) {
    // A flick rather than a drag. Grow about its middle rather than
    // zooming to a sliver nobody could have meant.
    const middle = (start + stop) / 2;
    start = Math.max(0, Math.round(middle - minimum / 2));
    stop = Math.min(total, start + minimum);
    start = Math.max(0, stop - minimum);
  }
  return { from: start, to: stop };
}

/* ---------- geometry ---------- */

/** Marks at 0 and 100 percent would sit half outside the frame, so the
 *  track is inset by a mark's width at each end. */
export const coveragePercent = (index, last) =>
  `calc(2px + ${(index / last) * 100}% - ${(index / last) * 4}px)`;

/** Left edge for a note sitting beside an anchor, on whichever side has
 *  room. An anchor near a frame edge would otherwise pin its note against
 *  that edge, away from the thing it points at. */
export function besideAnchor(anchorX, width, frameWidth, gutter = 28) {
  const toTheRight = anchorX + gutter;
  if (toTheRight + width + 8 <= frameWidth) return toTheRight;
  return Math.max(8, anchorX - gutter - width);
}

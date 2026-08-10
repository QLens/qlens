/* A recorder for what the viewer actually did.
 *
 * The Python side records itself through TraceAct, and the frontend had
 * nothing equivalent: when an interaction misbehaved the only way to find
 * out why was to add a console.log, reproduce, and take it out again.
 * Every bug in the field surfaces get found that way costs a round of
 * guessing first, and guesses about event ordering are usually wrong —
 * three separate defects here came down to an element being replaced
 * between two events, which no amount of reading the code makes obvious.
 *
 * So every handler records instead. The cost is a push onto a bounded
 * ring; nothing is formatted until someone asks for it. It is always on,
 * because instrumentation you have to switch on is instrumentation you
 * do not have when the thing you needed it for happened.
 *
 * From the console:
 *
 *     qlens.debug()              the last 200 events
 *     qlens.debug('scrub')       only events whose kind contains 'scrub'
 *     qlens.debug.table()        the same, as a table
 *     qlens.debug.clear()
 *     qlens.debug.watch(fn)      call fn on every event as it happens
 */

const LIMIT = 200;
const events = [];
const watchers = new Set();
let sequence = 0;

/** Record one thing that happened.
 *
 * `kind` is a dotted name (`scrub.pointer`, `zoom.wheel`, `state.open`),
 * and `fields` is whatever would answer the next question about it. Keep
 * fields to plain values: they are held until they age out of the ring,
 * and holding a DOM node here would keep a detached tree alive.
 */
export function trace(kind, fields = {}) {
  const event = { n: sequence++, t: Math.round(performance.now()), kind, ...fields };
  events.push(event);
  if (events.length > LIMIT) events.shift();
  for (const watcher of watchers) {
    try { watcher(event); } catch { /* a broken watcher must not break the app */ }
  }
  return event;
}

/** Record the outcome of something that can fail, without the caller
 *  wrapping every handler in its own try/catch. */
export function traced(kind, fields, fn) {
  try {
    const value = fn();
    trace(kind, fields);
    return value;
  } catch (error) {
    trace(`${kind}.threw`, { ...fields, error: String(error) });
    throw error;
  }
}

const match = (filter) => (filter
  ? events.filter((e) => e.kind.includes(filter))
  : events.slice());

export function install(target) {
  const dump = (filter) => match(filter);
  dump.table = (filter) => {
    // eslint-disable-next-line no-console
    console.table(match(filter));
    return match(filter).length;
  };
  dump.clear = () => { events.length = 0; return 0; };
  dump.watch = (fn) => { watchers.add(fn); return () => watchers.delete(fn); };
  dump.last = (kind) => [...events].reverse().find((e) => e.kind.includes(kind)) || null;
  target.qlens = { ...(target.qlens || {}), debug: dump };
  return dump;
}

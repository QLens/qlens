/* Qlens viewer.
 *
 * Four views over one recorded circuit run: the amplitude waterfall with
 * a transport, the statevector at the cursor, an A/B comparison, and the
 * assertions. The server does the heavy reduction; this file is layout,
 * interaction, and the fetching that feeds the canvases in draw.js.
 *
 * Runs arriving while the page is open come in over Server-Sent Events,
 * so a test suite running in another terminal populates the view live.
 */

import {
  h, svg, clear, panel, tag, micro, val, button, iconButton, status, toggle,
  segmented, phaseQ, bits, ket, fixed, sci, signed, meaningful, shortSource,
} from './ui.js';
import {
  buildHeatmap, drawWaterfall, drawBars, drawDeltaBars, phaseTokens, phaseColor,
} from './draw.js';
import { guideOverlay, settingsOverlay, copyButton } from './guide.js';

const TABS = ['Timeline', 'State', 'Diff', 'Assertions'];
const STORAGE_KEY = 'qlens.viewer.v1';
const THRESHOLDS = [
  { value: 0, label: 'off' },
  { value: 0.001, label: '1e-3' },
  { value: 0.005, label: '5e-3' },
  { value: 0.02, label: '2e-2' },
];
const SPEEDS = [1, 4, 12];
// A statevector fetch per scrub step would be one request per frame.
// Coalescing to the trailing edge keeps the playhead responsive while
// the panels below settle a beat later.
const SCRUB_DEBOUNCE_MS = 60;
const MAX_WATERFALL_ROWS = 1024;

const saved = (() => {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; } catch { return {}; }
})();

const state = {
  tab: TABS.includes(saved.tab) ? saved.tab : 'Timeline',
  threshold: saved.threshold ?? 0,
  overlay: saved.overlay !== false,
  helpSeen: !!saved.helpSeen,
  helpOpen: false,
  guideTopic: null,
  settingsOpen: false,
  prefs: {
    showTour: saved.prefs?.showTour !== false,
    overlayExpected: saved.prefs?.overlayExpected !== false,
  },
  runs: [],
  traceId: null,
  detail: null,
  waterfall: null,
  heatmap: null,
  index: 0,
  pinA: 0,
  pinB: 0,
  playing: false,
  speed: 4,
  openAssertion: null,
  error: null,
  loading: true,
  health: null,
};

const stateCache = new Map();
const tokens = phaseTokens();
const root = document.getElementById('app');

/* ---------- derived ---------- */

const positions = () => state.waterfall?.positions || [];
const positionCount = () => positions().length;
const currentPosition = () => positions()[state.index] ?? null;
const numQubits = () => state.detail?.num_qubits || state.waterfall?.num_qubits || 0;

/** Every gate in execution order, flattened out of the layer events. In
 *  layers mode one trace event carries several gates; the waterfall axis
 *  is per gate either way, so the strip needs them flat. */
function gateList() {
  const gates = [];
  for (const layer of state.detail?.layers || []) {
    for (const gate of layer.gates || []) gates.push(gate);
  }
  gates.sort((a, b) => (a.position ?? 0) - (b.position ?? 0));
  return gates;
}

let gatesByPosition = new Map();

function gateAt(position) {
  return gatesByPosition.get(position) || null;
}

function gateLabel(position) {
  const gate = gateAt(position);
  if (!gate) return '—';
  const qubits = (gate.qubits || []).map((q) => `q${q}`).join(',');
  return qubits ? `${gate.gate}(${qubits})` : gate.gate;
}

/** Assertions carrying a position, resolved onto the waterfall's x axis. */
function markers() {
  const list = positions();
  return (state.detail?.assertions || [])
    .map((assertion) => {
      const index = assertion.position === null || assertion.position === undefined
        ? null : list.indexOf(assertion.position);
      return {
        assertion,
        index: index === -1 ? null : index,
        pass: assertion.status !== 'failed',
      };
    })
    .filter((mark) => mark.index !== null);
}

const failedCount = () =>
  (state.detail?.assertions || []).filter((a) => a.status === 'failed').length;

/** Checks whose statistics do not support their own verdict. Counted
 *  separately from failures: a flagged check may have passed, and its
 *  passing is exactly what cannot be trusted. */
const unreliableCount = () =>
  (state.detail?.assertions || []).filter((a) => a.reliability?.reliable === false).length;

const isUnreliable = (assertion) => assertion?.reliability?.reliable === false;

function openGuide(topicId) {
  state.guideTopic = topicId;
  state.helpOpen = false;
  render();
}

/* ---------- data ---------- */

async function api(path) {
  const response = await fetch(path, { headers: { Accept: 'application/json' } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `${response.status} on ${path}`);
  return payload;
}

async function loadRuns() {
  const { circuits } = await api('/api/circuits');
  state.runs = circuits;
  return circuits;
}

async function openRun(traceId) {
  state.traceId = traceId;
  state.detail = await api(`/api/circuit?trace_id=${encodeURIComponent(traceId)}`);
  gatesByPosition = new Map(gateList().map((gate) => [gate.position, gate]));
  await loadWaterfall();
  stateCache.clear();
  state.index = Math.max(positionCount() - 1, 0);
  state.pinA = 0;
  state.pinB = state.index;
  state.openAssertion = null;
  await ensureState(currentPosition());
  await ensureState(positions()[state.pinA]);
}

async function loadWaterfall() {
  const query = new URLSearchParams({
    trace_id: state.traceId,
    threshold: String(state.threshold),
    max_rows: String(MAX_WATERFALL_ROWS),
  });
  state.waterfall = await api(`/api/waterfall?${query}`);
  state.heatmap = buildHeatmap(state.waterfall);
}

/** Exact amplitudes at one position, memoised. The waterfall's planes
 *  are quantized for display; every number the panels print comes from
 *  here instead. */
async function ensureState(position) {
  if (position === null || position === undefined) return null;
  if (stateCache.has(position)) return stateCache.get(position);
  const query = new URLSearchParams({ trace_id: state.traceId, position: String(position) });
  const payload = await api(`/api/state?${query}`);
  const amplitudes = payload.amplitudes;
  const record = {
    position,
    probabilities: amplitudes.map(([re, im]) => re * re + im * im),
    hues: amplitudes.map(([re, im]) => ((Math.atan2(im, re) / (2 * Math.PI)) % 1 + 1) % 1 * 360),
  };
  stateCache.set(position, record);
  return record;
}

const stateAt = (position) => stateCache.get(position) || null;

let pendingScrub = null;

function requestState(position) {
  if (stateCache.has(position)) return;
  clearTimeout(pendingScrub);
  pendingScrub = setTimeout(() => {
    ensureState(position).then(() => {
      if (currentPosition() === position || position === positions()[state.pinA]
        || position === positions()[state.pinB]) render();
    }).catch(() => {});
  }, SCRUB_DEBOUNCE_MS);
}

/* ---------- expectations ---------- */

/** The reference distribution an assert_distribution recorded, expanded
 *  onto the full basis so it lines up with the observed bars. */
function expectedVector(assertion) {
  const expected = assertion?.expected;
  if (!expected) return null;
  const size = 1 << numQubits();
  const vector = new Array(size).fill(0);
  for (const [label, probability] of Object.entries(expected)) {
    const index = parseInt(label, 2);
    if (Number.isInteger(index) && index >= 0 && index < size) vector[index] = probability;
  }
  return vector;
}

/** The distribution assertion nearest the cursor, which is what the
 *  State tab ghosts behind the observed bars. */
function nearestExpectation() {
  const candidates = (state.detail?.assertions || []).filter((a) => a.expected);
  if (!candidates.length) return null;
  const here = currentPosition();
  return candidates.reduce((best, a) => {
    if (a.position === null || a.position === undefined) return best;
    if (!best) return a;
    return Math.abs(a.position - here) < Math.abs(best.position - here) ? a : best;
  }, null) || candidates[0];
}

function nearestAssertion() {
  const list = state.detail?.assertions || [];
  const positioned = list.filter((a) => a.position !== null && a.position !== undefined);
  if (!positioned.length) return list[0] || null;
  const here = currentPosition();
  return positioned.reduce((best, a) =>
    Math.abs(a.position - here) < Math.abs(best.position - here) ? a : best);
}

/* ---------- navigation ---------- */

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      tab: state.tab, threshold: state.threshold,
      overlay: state.overlay, helpSeen: state.helpSeen, prefs: state.prefs,
    }));
  } catch { /* private browsing; the view still works */ }
}

function scrubTo(index) {
  const limit = positionCount() - 1;
  state.index = Math.max(0, Math.min(limit, index));
  requestState(currentPosition());
  render();
}

function step(delta) {
  state.playing = false;
  scrubTo(state.index + delta);
}

function jumpAssertion(direction) {
  state.playing = false;
  const indexes = markers().map((m) => m.index).sort((a, b) => a - b);
  const next = direction > 0
    ? indexes.find((i) => i > state.index)
    : [...indexes].reverse().find((i) => i < state.index);
  if (next !== undefined) scrubTo(next);
}

let rafHandle = 0;
let carry = 0;
let lastFrame = 0;

function playLoop(now) {
  const elapsed = now - lastFrame;
  lastFrame = now;
  carry += (elapsed * state.speed * 30) / 1000;
  if (carry >= 1) {
    const advance = Math.floor(carry);
    carry -= advance;
    const next = state.index + advance;
    if (next >= positionCount() - 1) {
      state.index = positionCount() - 1;
      setPlaying(false);
      requestState(currentPosition());
      render();
      return;
    }
    state.index = next;
    requestState(currentPosition());
    render();
  }
  rafHandle = requestAnimationFrame(playLoop);
}

function setPlaying(playing) {
  state.playing = playing && positionCount() > 1;
  cancelAnimationFrame(rafHandle);
  if (state.playing) {
    lastFrame = performance.now();
    carry = 0;
    rafHandle = requestAnimationFrame(playLoop);
  }
}

async function setThreshold(threshold) {
  state.threshold = threshold;
  persist();
  await loadWaterfall();
  render();
}

function setTab(name) {
  state.tab = name;
  // Leaving the timeline dismisses its tour rather than parking it to
  // reappear the next time that tab comes back.
  if (name !== 'Timeline' && state.helpOpen) {
    state.helpOpen = false;
    state.helpSeen = true;
  }
  persist();
  render();
}

/** Position picked from a pointer along a full-width surface. */
function pickFromEvent(event, element) {
  const box = element.getBoundingClientRect();
  const fraction = (event.clientX - box.left) / Math.max(box.width, 1);
  return Math.round(fraction * (positionCount() - 1));
}

function scrubbable(element) {
  const handle = (event) => {
    if (event.type === 'pointermove' && event.buttons !== 1) return;
    setPlaying(false);
    scrubTo(pickFromEvent(event, element));
  };
  element.addEventListener('pointerdown', handle);
  element.addEventListener('pointermove', handle);
  element.classList.add('scrubbable');
  return element;
}

document.addEventListener('keydown', (event) => {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
  if (!state.detail) return;
  if (event.key === ' ') { event.preventDefault(); setPlaying(!state.playing); render(); }
  else if (event.key === 'ArrowRight') { event.preventDefault(); event.shiftKey ? jumpAssertion(1) : step(1); }
  else if (event.key === 'ArrowLeft') { event.preventDefault(); event.shiftKey ? jumpAssertion(-1) : step(-1); }
  else if (event.key === 'Home') { event.preventDefault(); step(-positionCount()); }
  else if (event.key === 'End') { event.preventDefault(); step(positionCount()); }
  else if (event.key === 'Escape' && state.helpOpen) { state.helpOpen = false; render(); }
  else if (/^[1-4]$/.test(event.key)) setTab(TABS[Number(event.key) - 1]);
});

/* ---------- layout ---------- */

/** Panel geometry from the viewport. Canvas surfaces need explicit pixel
 *  sizes, so the sizes CSS would normally own are computed here. */
function geometry() {
  const width = Math.max(root.clientWidth || window.innerWidth, 480);
  const height = Math.max(root.clientHeight || window.innerHeight, 480);
  const content = width - 40 - 2 - 40; // page padding, panel border, panel padding
  const bodyHeight = height - 48 - 36 - 40;
  const qubits = numQubits();
  const laneHeight = qubits > 7 ? 11 : 16;
  const stripHeight = qubits * laneHeight + 8;
  return {
    content,
    waterfallWidth: Math.max(240, content - 74 - 8),
    waterfallHeight: Math.max(160, bodyHeight - stripHeight - 320),
    laneHeight,
    stripHeight,
    stateHeight: Math.max(200, bodyHeight - 300),
    assertionWidth: Math.round(content * 0.42),
    compareWidth: Math.max(200, Math.round((content - 260 - 40) / 2)),
    deltaWidth: Math.max(240, content - 420 - 24),
    deltaHeight: Math.max(140, Math.min(320, bodyHeight - 360)),
  };
}

/* ---------- shell ---------- */

function topbar() {
  const run = state.runs.find((r) => r.trace_id === state.traceId);
  const failed = failedCount();
  const needleAngle = state.playing ? (state.index * 7) % 360 : 45;
  return h('header', { class: 'topbar' },
    h('div', { class: 'brand' }, phaseQ(22, needleAngle), h('span', { class: 'brand-name' }, 'qlens')),
    state.health && h('span', { class: 'micro', title: state.health.source },
      shortSource(state.health.source)),
    h('div', { class: 'rule' }),
    runPicker(),
    run?.backend && tag(run.backend),
    run?.num_qubits ? tag(`${run.num_qubits} qubits · ${run.gate_count} gates`) : null,
    h('div', { class: 'spacer' }),
    button('Guide', { onClick: () => openGuide('overview') }),
    iconButton('⚙', 'Settings', { onClick: () => { state.settingsOpen = true; render(); } }),
    unreliableCount() ? status('warn', `${unreliableCount()} unreliable`) : null,
    run?.in_flight && status('live', 'recording'),
    state.playing && status('live', `playing ${state.speed}×`),
    state.detail && (failed
      ? status('fail', `${failed} assertion${failed === 1 ? '' : 's'} failed`)
      : status('pass', 'all passing')),
  );
}

function runPicker() {
  if (!state.runs.length) return h('span', { class: 'micro' }, 'no runs yet');
  const select = h('select', {
    class: 'select', 'aria-label': 'Circuit run',
    onChange: (event) => { selectRun(event.target.value); },
  }, state.runs.map((run) => h('option', {
    value: run.trace_id, selected: run.trace_id === state.traceId,
  }, runLabel(run))));
  return select;
}

function runLabel(run) {
  const when = run.started_at ? run.started_at.slice(11, 19) : '';
  const failed = run.assertions_failed ? ` · ${run.assertions_failed} failed` : '';
  return `${run.trace_id} · ${when}${failed}`;
}

function tabbar() {
  const failed = failedCount();
  return h('nav', { class: 'tabbar', role: 'tablist' },
    TABS.map((name, i) => h('button', {
      class: 'tab', role: 'tab', type: 'button',
      'aria-selected': String(name === state.tab),
      onClick: () => setTab(name),
    },
      name,
      name === 'Assertions' && failed > 0 ? status('fail', String(failed)) : null,
      h('span', { class: 'key' }, String(i + 1)),
    )),
    h('span', { class: 'shortcuts' }, 'space play · ←→ step · shift+←→ assertion · 1–4 tabs'),
  );
}

/* ---------- timeline ---------- */

function waterfallPanel(geo) {
  const waterfall = state.waterfall;
  const canvas = h('canvas');
  drawWaterfall(canvas, {
    heatmap: state.heatmap, waterfall,
    width: geo.waterfallWidth, height: geo.waterfallHeight,
    index: state.index, marks: markers(),
  });
  scrubbable(canvas);

  const rowsPerPixel = waterfall.kept_rows / geo.waterfallHeight;
  const qubits = numQubits();

  return panel('Amplitude waterfall', [
    tag(`${waterfall.num_positions} positions · true resolution`),
    tag(`${waterfall.num_states} basis states`),
    rowsPerPixel > 2 ? status('warn', `${rowsPerPixel.toFixed(1)} rows per pixel`) : null,
    iconButton('◎', 'Point out the parts of this panel', {
      onClick: () => { state.helpOpen = true; state.guideTopic = null; render(); },
    }),
    iconButton('ⓘ', 'What the waterfall shows', { onClick: () => openGuide('waterfall') }),
  ],
    h('div', { class: 'waterfall-row' },
      h('div', {
        class: 'basis-axis',
        style: { height: `${geo.waterfallHeight}px` },
      },
        h('span', {}, ket(waterfall.first_row_state, qubits)),
        h('span', {}, ket(waterfall.last_row_state, qubits)),
      ),
      h('div', { style: { flex: '1', minWidth: '0' } },
        canvas,
        h('div', { style: { marginTop: 'var(--space-3)' } }, gateStrip(geo)),
      ),
    ),
    h('div', { class: 'controls' }, collapseBar(), transport()),
  );
}

function gateStrip(geo) {
  const width = geo.waterfallWidth;
  const height = geo.stripHeight;
  const qubits = numQubits();
  const list = positions();
  const columns = Math.max(list.length, 1);
  const xAt = (index) => ((index + 0.5) / columns) * width;

  const nodes = [];
  for (let q = 0; q < qubits; q++) {
    nodes.push(svg('line', {
      x1: 0, y1: 6 + q * geo.laneHeight, x2: width, y2: 6 + q * geo.laneHeight,
      stroke: 'var(--border-subtle)', 'stroke-width': 1,
    }));
  }
  // One tick per gate on the wire it acted on, with a spine joining the
  // wires of a multi-qubit gate. At 400 gates across 1200px the ticks
  // merge into texture, which is the intent: the shape of the circuit,
  // not a legible per-gate diagram.
  for (let i = 0; i < list.length; i++) {
    const gate = gateAt(list[i]);
    if (!gate) continue;
    const qubitsOn = gate.qubits || [];
    const x = xAt(i);
    const colour = qubitsOn.length > 1 ? 'var(--accent-11)' : 'var(--text-secondary)';
    if (qubitsOn.length > 1) {
      const ys = qubitsOn.map((q) => 6 + q * geo.laneHeight);
      nodes.push(svg('line', {
        x1: x, y1: Math.min(...ys), x2: x, y2: Math.max(...ys),
        stroke: colour, 'stroke-width': 1, opacity: 0.45,
      }));
      nodes.push(svg('rect', {
        x: x - 1, y: ys[ys.length - 1] - 2.5, width: 2, height: 5, fill: colour,
      }));
    } else if (qubitsOn.length === 1) {
      nodes.push(svg('rect', {
        x: x - 1, y: 6 + qubitsOn[0] * geo.laneHeight - 2.5, width: 2, height: 5, fill: colour,
      }));
    }
  }
  for (const mark of markers()) {
    nodes.push(svg('rect', {
      x: xAt(mark.index) - 1.5, y: 0, width: 3, height,
      fill: mark.pass ? 'var(--pass-9)' : 'var(--fail-9)',
      opacity: mark.pass ? 0.3 : 0.75,
    }));
  }
  nodes.push(svg('line', {
    x1: xAt(state.index), y1: 0, x2: xAt(state.index), y2: height,
    stroke: 'var(--accent-9)', 'stroke-width': 1.5,
  }));

  return scrubbable(svg('svg', { width, height, style: 'display:block' }, nodes));
}

function collapseBar() {
  const waterfall = state.waterfall;
  return h('div', { class: 'control-row' },
    h('div', { class: 'group' },
      micro('collapse near-zero rows'),
      segmented(
        THRESHOLDS.map((t) => ({ value: t.value, label: t.label })),
        state.threshold,
        (value) => { setThreshold(value); },
      ),
    ),
    h('div', { class: 'rule' }),
    h('span', { class: 'readout' }, state.threshold
      ? [
        'showing ', h('span', { class: 'hi' }, String(waterfall.kept_rows)),
        ` of ${waterfall.num_states} rows`,
        h('span', { class: 'lo' }, ` · ${waterfall.elided_rows} collapsed`),
      ]
      : [
        'showing all ', h('span', { class: 'hi' }, String(waterfall.num_states)), ' rows',
        h('span', { class: 'lo' }, ' · no collapse'),
      ]),
    waterfall.rows < waterfall.kept_rows
      ? h('span', { class: 'readout lo' }, `${waterfall.rows} display rows`) : null,
  );
}

function transport() {
  const last = positionCount() - 1;
  return h('div', { class: 'control-row' },
    h('div', { style: { display: 'flex', gap: '2px' } },
      iconButton('⏮', 'Start', { onClick: () => { setPlaying(false); scrubTo(0); } }),
      iconButton('◀', 'Step back', { onClick: () => step(-1) }),
      iconButton(state.playing ? '⏸' : '▶', state.playing ? 'Pause' : 'Play', {
        pressed: state.playing,
        onClick: () => { setPlaying(!state.playing); render(); },
      }),
      iconButton('▶', 'Step forward', { onClick: () => step(1) }),
      iconButton('⏭', 'End', { onClick: () => { setPlaying(false); scrubTo(last); } }),
    ),
    h('span', { class: 'readout', style: { minWidth: '230px' } },
      'position ', h('span', { class: 'hi' }, String(currentPosition() ?? 0)), ` of ${last}`,
      h('span', { class: 'lo' }, ` · ${gateLabel(currentPosition())}`),
    ),
    scrubBar(),
    segmented(SPEEDS.map((s) => ({ value: s, label: `${s}×` })), state.speed,
      (value) => { state.speed = value; if (state.playing) setPlaying(true); render(); }),
    iconButton('⇤', 'Previous assertion', { onClick: () => jumpAssertion(-1) }),
    iconButton('⇥', 'Next assertion', { onClick: () => jumpAssertion(1) }),
  );
}

function scrubBar() {
  const last = Math.max(positionCount() - 1, 1);
  const percent = (index) => `${(index / last) * 100}%`;
  const bar = h('div', { class: 'scrub' },
    h('div', { class: 'scrub-track' },
      h('div', { class: 'scrub-fill', style: { width: percent(state.index) } }),
      markers().map((mark) => h('div', {
        class: 'scrub-mark',
        title: `${mark.assertion.assertion} · ${mark.pass ? 'pass' : 'fail'}`,
        style: {
          left: percent(mark.index),
          background: mark.pass ? 'var(--pass-9)' : 'var(--fail-9)',
          boxShadow: mark.pass ? 'none' : 'var(--glow-fail)',
        },
      })),
      h('div', { class: 'scrub-head', style: { left: percent(state.index) } }),
    ),
  );
  return scrubbable(bar);
}

/** The assertion at or nearest the cursor, with its observed bars and,
 *  for distribution checks, the expectation ghosted behind them. */
function activeAssertionPanel(geo) {
  const assertion = nearestAssertion();
  if (!assertion) {
    return panel('Assertions', [tag('none recorded')],
      h('p', { class: 'readout lo' },
        'This run recorded no assertions. Call qlens.assert_* against the result to mark it up.'));
  }
  const here = currentPosition();
  const atCursor = assertion.position !== null && Math.abs(assertion.position - here) <= 2;
  const record = stateAt(here);
  const expected = expectedVector(assertion);
  const canvas = h('canvas');
  if (record) {
    drawBars(canvas, {
      observed: record.probabilities, expected, hues: record.hues,
      width: Math.round(geo.content * 0.52), height: 96, tokens,
    });
  }

  return panel(
    atCursor ? assertion.assertion : `nearest assertion — ${assertion.assertion}`,
    [
      status(assertion.status === 'failed' ? 'fail' : 'pass',
        assertion.status === 'failed' ? 'failed' : 'pass'),
      assertion.source ? tag(shortSource(assertion.source)) : null,
      assertion.position !== null && assertion.position !== undefined
        ? button(`Go to ${assertion.position}`, {
          onClick: () => scrubTo(positions().indexOf(assertion.position)),
        }) : null,
    ],
    h('div', { style: { display: 'flex', gap: 'var(--space-8)', alignItems: 'flex-start', flexWrap: 'wrap' } },
      h('div', {},
        canvas,
        h('div', {
          style: {
            display: 'flex', alignItems: 'center', gap: 'var(--space-7)',
            marginTop: 'var(--space-4)', fontFamily: 'var(--font-mono)',
            fontSize: '10.5px', color: 'var(--text-tertiary)',
          },
        },
          expected ? legendSwatch('expected', 'oklch(72% 0.01 258 / 0.16)', true) : null,
          expected ? legendSwatch('observed', 'oklch(78% 0.17 175)', false) : null,
          h('span', { style: { marginLeft: 'auto' } },
            `${1 << numQubits()} basis states · big-endian`),
        ),
      ),
      h('div', { style: { flex: '1', minWidth: '260px', display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' } },
        h('p', {
          style: { margin: 0, fontSize: '12.5px', lineHeight: 1.5, color: 'var(--text-secondary)' },
        }, assertionDetail(assertion)),
        metricGrid(assertion),
      ),
    ),
  );
}

function legendSwatch(label, colour, dashed) {
  return h('span', { style: { display: 'flex', alignItems: 'center', gap: 'var(--space-3)' } },
    h('span', {
      style: {
        width: dashed ? '16px' : '9px', height: '10px', background: colour,
        borderTop: dashed ? '1px dashed oklch(72% 0.01 258 / 0.7)' : 'none',
      },
    }),
    label);
}

function assertionDetail(assertion) {
  if (assertion.error?.message) return assertion.error.message;
  if (assertion.assertion === 'assert_distribution') return 'observed distribution within tolerance';
  if (assertion.assertion === 'assert_unitary') return 'U†U is the identity within tolerance';
  if (assertion.assertion === 'assert_equivalent') return 'both circuits compute the same unitary';
  return 'passed';
}

const METRIC_LABELS = {
  statistic: 'statistic', p_value: 'p-value', tolerance: 'tolerance',
  shots: 'shots', deviation: 'deviation', atol: 'atol',
};

function metricGrid(assertion) {
  const entries = Object.entries(assertion.details || {});
  if (!entries.length) return h('span', { class: 'readout lo' }, 'no metrics recorded');
  return h('div', { class: 'metrics' }, entries.map(([key, value]) =>
    val(METRIC_LABELS[key] || key, key === 'shots' ? String(value ?? '—') : sci(value))));
}

function timelineTab(geo) {
  return [waterfallPanel(geo), activeAssertionPanel(geo)];
}

/* ---------- state tab ---------- */

function stateTab(geo) {
  const record = stateAt(currentPosition());
  if (!record) return [panel('Statevector', [], h('p', { class: 'readout lo' }, 'loading…'))];
  const qubits = numQubits();
  const size = record.probabilities.length;
  const expectation = nearestExpectation();
  const expected = state.overlay ? expectedVector(expectation) : null;

  const canvas = h('canvas');
  drawBars(canvas, {
    observed: record.probabilities, expected, hues: record.hues,
    width: geo.content, height: geo.stateHeight, tokens,
  });

  const divergences = record.probabilities
    .map((probability, index) => ({
      index, hue: record.hues[index], probability,
      delta: expected ? probability - expected[index] : null,
    }))
    .sort((a, b) => (expected
      ? Math.abs(b.delta) - Math.abs(a.delta)
      : b.probability - a.probability))
    .slice(0, 16);

  return [
    panel(`Statevector — position ${currentPosition()}`, [
      iconButton('ⓘ', 'What these bars show', { onClick: () => openGuide('state') }),
      expectation ? toggle('Overlay expected', state.overlay, (checked) => {
        state.overlay = checked; persist(); render();
      }) : null,
      tag(`${size} states`),
      button('Back to timeline', { onClick: () => setTab('Timeline') }),
    ],
      canvas,
      basisAxis(size, qubits, geo.content),
    ),
    panel(expected ? 'Largest divergences' : 'Largest amplitudes', [
      tag(expected ? 'sorted by |Δ probability|' : 'sorted by probability'),
      expectation ? tag(`expected from ${expectation.assertion}`) : null,
    ],
      h('div', {
        class: 'divergence-grid',
        style: {
          gridTemplateColumns: `repeat(${geo.content >= 1240 ? 4 : geo.content >= 920 ? 3 : 2}, minmax(0, 1fr))`,
        },
      }, divergences.map((row) => h('div', { class: 'divergence-row' },
        h('span', { class: 'basis-label' },
          h('span', { class: 'swatch', style: { background: phaseColor(row.hue, tokens) } }),
          ket(row.index, qubits)),
        h('span', {}, fixed(row.probability)),
        row.delta === null
          ? h('span', {})
          : h('span', {
            class: `pos-delta ${meaningful(row.delta) ? (row.delta > 0 ? 'up' : 'down') : 'dim'}`,
          }, signed(row.delta)),
      ))),
    ),
  ];
}

function basisAxis(size, qubits, width) {
  if (size <= 32) {
    const per = width / size;
    const stride = Math.max(1, Math.ceil(34 / per));
    return h('div', {
      style: {
        display: 'grid', gridTemplateColumns: `repeat(${size}, minmax(0, 1fr))`,
        marginTop: 'var(--space-3)',
      },
    }, Array.from({ length: size }, (_, i) => h('div', {
      style: {
        minWidth: 0, overflow: 'hidden', fontFamily: 'var(--font-mono)',
        fontSize: '9.5px', color: 'var(--text-tertiary)', textAlign: 'center',
        whiteSpace: 'nowrap',
      },
    }, i % stride === 0 ? bits(i, qubits) : '')));
  }
  return h('div', {
    style: {
      display: 'flex', justifyContent: 'space-between', marginTop: 'var(--space-3)',
      fontFamily: 'var(--font-mono)', fontSize: '9.5px', color: 'var(--text-tertiary)',
    },
  },
    h('span', {}, ket(0, qubits)),
    h('span', {}, `${size} basis states`),
    h('span', {}, ket(size - 1, qubits)),
  );
}

/* ---------- diff tab ---------- */

function diffTab(geo) {
  const list = positions();
  const positionA = list[state.pinA];
  const positionB = list[state.pinB];
  const a = stateAt(positionA);
  const b = stateAt(positionB);
  if (!a) ensureState(positionA).then(render).catch(() => {});
  if (!b) ensureState(positionB).then(render).catch(() => {});
  if (!a || !b) return [panel('Compare positions', [], h('p', { class: 'readout lo' }, 'loading…'))];

  const fidelityValue = fidelity(a, b);
  const distance = l2(a.probabilities, b.probabilities);
  const moved = a.probabilities.reduce(
    (count, value, i) => count + (Math.abs(b.probabilities[i] - value) > 0.004 ? 1 : 0), 0);
  const tone = fidelityValue > 0.99 ? 'pass' : fidelityValue > 0.9 ? 'warn' : 'fail';
  const qubits = numQubits();

  const rows = a.probabilities
    .map((value, index) => ({
      index, hue: b.hues[index], a: value, b: b.probabilities[index],
      delta: b.probabilities[index] - value,
    }))
    .sort((x, y) => Math.abs(y.delta) - Math.abs(x.delta))
    .slice(0, 8);

  const deltaCanvas = h('canvas');
  drawDeltaBars(deltaCanvas, {
    a: a.probabilities, b: b.probabilities, hues: b.hues,
    width: geo.deltaWidth, height: geo.deltaHeight, tokens,
  });

  return [
    panel('Compare positions', [
      tag('same run'),
      button('Pin A here', { onClick: () => { state.pinA = state.index; render(); } }),
      button('Pin B here', { onClick: () => { state.pinB = state.index; render(); } }),
    ],
      h('div', { class: 'compare' },
        pinColumn('A', positionA, a, geo),
        pinColumn('B', positionB, b, geo),
        h('div', {},
          h('div', { class: 'fidelity' },
            h('div', { class: `fidelity-num ${tone === 'pass' ? 'up' : tone === 'fail' ? 'down' : ''}`,
              style: tone === 'warn' ? { color: 'var(--warn-9)' } : {} },
              fixed(fidelityValue)),
            h('div', { class: 'fidelity-sub' }, '|⟨ψ_A|ψ_B⟩|²'),
          ),
          h('div', { class: 'fidelity-stats' },
            val('L2 distance', fixed(distance)),
            val('states moved', String(moved)),
            val('Δ positions', String(Math.abs(state.pinB - state.pinA))),
            val('gates between', String(Math.abs(positionB - positionA))),
          ),
        ),
      ),
    ),
    panel('Δ probability — B minus A', [tag('bar colour = phase at B'), tag(`${a.probabilities.length} states`)],
      h('div', {
        style: {
          display: 'grid', gridTemplateColumns: `minmax(0, 1fr) 400px`,
          gap: 'var(--space-9)', alignItems: 'start',
        },
      },
        deltaCanvas,
        h('div', {},
          h('div', {
            class: 'grid-row',
            style: { gridTemplateColumns: '1fr 66px 66px 72px', paddingBottom: 'var(--space-3)' },
          }, micro('basis'), micro('A'), micro('B'), micro('Δ')),
          rows.map((row) => h('div', {
            class: 'grid-row',
            style: {
              gridTemplateColumns: '1fr 66px 66px 72px', padding: 'var(--space-2) 0',
              borderTop: '1px solid var(--border-subtle)', color: 'var(--text-secondary)',
            },
          },
            h('span', { class: 'basis-label' },
              h('span', { class: 'swatch', style: { background: phaseColor(row.hue, tokens) } }),
              ket(row.index, qubits)),
            h('span', {}, fixed(row.a)),
            h('span', {}, fixed(row.b)),
            h('span', {
              class: `pos-delta ${meaningful(row.delta) ? (row.delta > 0 ? 'up' : 'down') : 'dim'}`,
            }, signed(row.delta)),
          )),
        ),
      ),
    ),
  ];
}

function pinColumn(name, position, record, geo) {
  const canvas = h('canvas');
  drawBars(canvas, {
    observed: record.probabilities, expected: null, hues: record.hues,
    width: geo.compareWidth, height: 132, tokens,
  });
  return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 'var(--space-4)', minWidth: 0 } },
    h('div', { class: 'compare-head' },
      h('span', { class: 'pos' }, name),
      h('span', {}, `position ${position}`),
      h('span', { class: 'dim' }, gateLabel(position)),
      button('Go', { onClick: () => scrubTo(positions().indexOf(position)) }),
    ),
    canvas,
  );
}

/** |⟨ψ_A|ψ_B⟩|² from magnitudes and phases. */
function fidelity(a, b) {
  let real = 0;
  let imaginary = 0;
  for (let i = 0; i < a.probabilities.length; i++) {
    const magnitude = Math.sqrt(a.probabilities[i]) * Math.sqrt(b.probabilities[i]);
    const delta = ((b.hues[i] - a.hues[i]) * Math.PI) / 180;
    real += magnitude * Math.cos(delta);
    imaginary += magnitude * Math.sin(delta);
  }
  return real * real + imaginary * imaginary;
}

function l2(a, b) {
  let sum = 0;
  for (let i = 0; i < a.length; i++) sum += (b[i] - a[i]) ** 2;
  return Math.sqrt(sum);
}

/* ---------- assertions tab ---------- */

function assertionsTab(geo) {
  const assertions = state.detail?.assertions || [];
  const failed = failedCount();
  // The status column carries a pass/fail badge and, when a check's
  // statistics do not hold, a second one beside it.
  const columns = '28px 76px minmax(0, 1fr) minmax(0, 240px) 150px 190px';

  return [
    panel('Assertions', [
      failed ? status('fail', `${failed} failed`) : status('pass', 'all passing'),
      unreliableCount() ? status('warn', `${unreliableCount()} unreliable`) : null,
      tag(`${assertions.length} recorded`),
      iconButton('ⓘ', 'How checks are tested', { onClick: () => openGuide('checks') }),
    ],
      h('div', { class: 'grid-row', style: { gridTemplateColumns: columns, paddingBottom: 'var(--space-4)' } },
        micro(''), micro('position'), micro('assertion'), micro('detail'), micro('source'), micro('status')),
      assertions.length
        ? assertions.map((assertion, i) => assertionRow(assertion, i, columns, geo))
        : h('p', { class: 'readout lo' },
          'No assertions recorded for this run. Call qlens.assert_* against the result while its trace is open.'),
    ),
    coveragePanel(assertions),
  ];
}

function assertionRow(assertion, key, columns, geo) {
  const open = state.openAssertion === key;
  const hasPosition = assertion.position !== null && assertion.position !== undefined;
  const record = hasPosition ? stateAt(assertion.position) : null;
  if (hasPosition && !record) ensureState(assertion.position).then(() => { if (state.openAssertion === key) render(); }).catch(() => {});

  const head = h('div', {
    class: 'grid-row assert-row', style: { gridTemplateColumns: columns },
    onClick: () => { state.openAssertion = open ? null : key; render(); },
  },
    h('span', { class: 'dim' }, open ? '▾' : '▸'),
    h('span', { class: hasPosition ? 'pos' : 'dim' }, hasPosition ? String(assertion.position) : '—'),
    h('span', {}, assertion.assertion),
    h('span', { class: 'dim ellipsis', title: assertionDetail(assertion) }, assertionDetail(assertion)),
    h('span', { class: 'dim ellipsis', title: assertion.source || '' }, shortSource(assertion.source)),
    h('span', { style: { display: 'flex', gap: 'var(--space-4)', alignItems: 'center' } },
      status(assertion.status === 'failed' ? 'fail' : 'pass',
        assertion.status === 'failed' ? 'failed' : 'pass'),
      isUnreliable(assertion)
        ? h('span', {
          title: assertion.reliability.summary,
          style: { cursor: 'help' },
        }, status('warn', 'unreliable'))
        : null,
    ),
  );

  if (!open) return h('div', {}, head);

  const canvas = h('canvas');
  if (record) {
    drawBars(canvas, {
      observed: record.probabilities, expected: expectedVector(assertion),
      hues: record.hues, width: geo.assertionWidth, height: 110, tokens,
    });
  }

  return h('div', { class: 'assert-open' }, head,
    h('div', { class: 'assert-detail' },
      record ? canvas : h('span', { class: 'readout lo' }, hasPosition ? 'loading…' : 'no state captured for this check'),
      h('div', { style: { flex: '1', minWidth: '260px', display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' } },
        metricGrid(assertion),
        reliabilityBlock(assertion),
        h('div', { style: { display: 'flex', gap: 'var(--space-5)', flexWrap: 'wrap' } },
          hasPosition ? button('Open in timeline', {
            variant: 'secondary',
            onClick: () => { scrubTo(positions().indexOf(assertion.position)); setTab('Timeline'); },
          }) : null,
          hasPosition ? button('Pin as B in diff', {
            onClick: () => { state.pinB = positions().indexOf(assertion.position); setTab('Diff'); },
          }) : null,
        ),
      ),
    ),
  );
}

/** Marks at 0 and 100 percent would sit half outside the frame, so the
 *  track is inset by a mark's width at each end. */
const coveragePercent = (index, last) =>
  `calc(2px + ${(index / last) * 100}% - ${(index / last) * 4}px)`;

/** Why a check's statistics cannot be trusted, and the exact lines that
 *  would settle it. Shown in full on the open row rather than hidden in
 *  a tooltip, because it is the thing the reader needs most. */
function reliabilityBlock(assertion) {
  if (!isUnreliable(assertion)) return null;
  const { summary, remedies = [] } = assertion.reliability;
  return h('div', { class: 'reliability' },
    h('div', { class: 'reliability-head' },
      status('warn', 'unreliable statistic'),
      h('span', { class: 'readout lo' }, `method: ${assertion.method || 'unknown'}`),
    ),
    h('p', { class: 'reliability-body' }, summary),
    remedies.length
      ? h('div', { class: 'remedies' },
        micro('use instead'),
        remedies.map((remedy) => h('div', { class: 'remedy' },
          h('code', {}, remedy),
          copyButton('Copy', remedy),
        )),
      )
      : null,
    h('button', {
      class: 'btn btn-ghost', type: 'button',
      onClick: () => openGuide('checks'),
    }, 'What does this mean?'),
  );
}

function coveragePanel(assertions) {
  const list = positions();
  const last = Math.max(list.length - 1, 1);
  const marks = markers();
  const sorted = marks.map((m) => m.index).sort((a, b) => a - b);

  let gapStart = 0;
  let widest = { start: 0, end: last };
  for (const index of [...sorted, last]) {
    if (index - gapStart > widest.end - widest.start) widest = { start: gapStart, end: index };
    gapStart = index;
  }
  const firstFailure = marks.find((m) => !m.pass);

  return panel('Coverage', [tag('assertion density across the run')],
    h('div', { class: 'coverage' },
      marks.map((mark) => h('div', {
        class: 'coverage-mark',
        title: `${mark.assertion.assertion} at ${mark.assertion.position}`,
        style: {
          left: coveragePercent(mark.index, last),
          background: mark.pass ? 'var(--pass-9)' : 'var(--fail-9)',
          boxShadow: mark.pass ? 'none' : 'var(--glow-fail)',
        },
        onClick: () => { scrubTo(mark.index); setTab('Timeline'); },
      })),
      h('div', { class: 'coverage-head', style: { left: coveragePercent(state.index, last) } }),
      h('div', { class: 'coverage-end', style: { left: '8px' } }, '0'),
      h('div', { class: 'coverage-end', style: { right: '8px' } }, String(list[last] ?? 0)),
    ),
    h('div', {
      style: {
        marginTop: 'var(--space-5)', display: 'flex', gap: 'var(--space-9)',
        fontFamily: 'var(--font-mono)', fontSize: 'var(--text-micro)',
        color: 'var(--text-tertiary)', flexWrap: 'wrap',
      },
    },
      assertions.length ? h('span', {},
        'largest untested span: ',
        h('span', { style: { color: 'var(--text-secondary)' } },
          `positions ${list[widest.start] ?? 0}–${list[widest.end] ?? 0} `
          + `(${Math.max(widest.end - widest.start, 0)} gates)`)) : null,
      firstFailure ? h('span', {}, 'first failure: ',
        h('span', { class: 'down' }, `position ${firstFailure.assertion.position}`)) : null,
    ),
  );
}

/* ---------- help ---------- */

/** The reading guide, anchored to the elements it describes.
 *
 * A centred card would be easier, but the thing being explained is a
 * dense field of colour whose meaning is entirely positional: which axis
 * is time, which band is a basis state, which strip shares the x axis.
 * Notes sit beside the region they name and run a leader line to it, so
 * the explanation and the pixels it refers to are read together.
 */
function helpOverlay() {
  const dismiss = () => { state.helpOpen = false; state.helpSeen = true; persist(); render(); };
  const overlay = h('div', { class: 'help', onClick: dismiss });

  // Anchors come from the live layout rather than the geometry model, so
  // the guide cannot drift out of register with what is on screen.
  //
  // Measured synchronously: render() has already put the panels in the
  // document, so getBoundingClientRect forces the layout it needs. A
  // requestAnimationFrame here would never fire in a background tab, and
  // webbrowser.open frequently lands the viewer in one, leaving an empty
  // scrim over the app.
  (() => {
    const body = document.getElementById('body');
    const canvas = body?.querySelector('canvas');
    const strip = body?.querySelector('svg[width]');
    if (!body || !canvas) { overlay.append(helpFallback(dismiss)); return; }

    const frame = body.getBoundingClientRect();
    const wf = canvas.getBoundingClientRect();
    const gs = strip ? strip.getBoundingClientRect() : wf;
    const box = (rect) => ({
      left: rect.left - frame.left + body.scrollLeft,
      top: rect.top - frame.top + body.scrollTop,
      width: rect.width, height: rect.height,
    });
    const w = box(wf);
    const g = box(gs);

    const lines = svg('svg', {
      class: 'help-lines', width: frame.width, height: body.scrollHeight,
    });
    const leader = (x1, y1, x2, y2) => lines.append(
      svg('path', { d: `M ${x1} ${y1} L ${x2} ${y2}`, stroke: 'var(--accent-9)', 'stroke-width': 1 }),
      svg('circle', { cx: x2, cy: y2, r: 3, fill: 'var(--accent-9)' }),
    );

    // The whole waterfall, and the strip that shares its x axis.
    lines.append(svg('rect', {
      x: w.left, y: w.top, width: w.width, height: w.height,
      fill: 'none', stroke: 'var(--accent-9)', 'stroke-width': 1, opacity: 0.5,
    }));
    lines.append(svg('rect', {
      x: g.left, y: g.top, width: g.width, height: g.height,
      fill: 'none', stroke: 'var(--accent-9)', 'stroke-width': 1, opacity: 0.45,
    }));

    // Title and axis notes share one band inside the field. Above the
    // panel there is only ~130px of chrome, not enough to stack them
    // without collision, and the overlay dims the field anyway.
    const band = w.top + 20;
    const titleWidth = Math.min(340, w.width * 0.34);
    const colourX = Math.max(w.left + titleWidth + 60, w.left + w.width * 0.42);
    const positionX = Math.max(colourX + 280, w.left + w.width * 0.72);
    const dropTo = Math.min(band + 190, w.top + w.height - 16);
    leader(colourX + 20, band + 96, colourX + 20, dropTo);
    leader(positionX + 20, band + 96, positionX + 20, dropTo);
    overlay.append(
      helpTitle({ left: w.left + 16, top: band, width: titleWidth }, dismiss),
      helpNote('colour = phase',
        'Hue is the phase of that amplitude, −π to +π around the wheel. Brightness is magnitude.',
        { left: colourX, top: band, width: 240 }),
      helpNote('x = position',
        `Left to right is time: ${positionCount()} columns, one per gate applied.`,
        { left: positionX, top: band, width: 240 }),
    );

    // The playhead, and the assertion nearest it, named where they sit.
    const headX = w.left + ((state.index + 0.5) / Math.max(positionCount(), 1)) * w.width;
    leader(headX, g.top + g.height + 96, headX, w.top + w.height * 0.72);
    overlay.append(helpNote('the cursor',
      'Everything below the waterfall reads the state at this column. Drag anywhere on the field to move it.',
      { left: Math.min(headX - 130, frame.width - 300), top: g.top + g.height + 104, width: 260 }));

    const mark = markers()[0];
    if (mark) {
      const markX = w.left + ((mark.index + 0.5) / Math.max(positionCount(), 1)) * w.width;
      leader(markX, w.top + w.height + 40, markX, w.top + w.height - 24);
      overlay.append(helpNote('assertion rules',
        'Green passed, red failed. shift+←→ jumps between them; the panel below shows the one nearest the cursor.',
        { left: Math.min(markX + 16, frame.width - 300), top: w.top + w.height + 20, width: 280 }));
    }

    leader(g.left + 120, g.top + g.height + 96, g.left + 120, g.top + g.height / 2);
    overlay.append(helpNote('circuit shares this axis',
      'The wire strip maps x identically, so a break in the field lines up with the gate that caused it.',
      { left: g.left + 8, top: g.top + g.height + 104, width: 290 }));
    overlay.prepend(lines);
  })();

  return overlay;
}

/** Keep a note inside the viewport whichever element it is anchored to. */
const clampLeft = (left, width) =>
  Math.max(8, Math.min(left, (document.getElementById('body')?.clientWidth || 0) - width - 8));

function helpTitle(position, dismiss) {
  return h('div', {
    class: 'help-title',
    style: {
      left: `${position.left}px`, top: `${position.top}px`, width: `${position.width}px`,
    },
  },
    h('h2', {}, 'Reading the waterfall'),
    h('p', {},
      'Every column is one gate position. Every row is one basis state. '
      + 'The whole execution at once, with no scrubbing to find where it went wrong.'),
    h('div', { class: 'help-foot' },
      button('Got it', { variant: 'primary', onClick: dismiss }),
      h('span', { class: 'readout lo' }, 'shown once · re-open from the ⓘ in the panel header'),
    ),
  );
}

/** Used when there is no waterfall to point at — an empty run, or a tab
 *  where the guide was re-opened out of context. */
function helpFallback(dismiss) {
  return h('div', { class: 'help-title', style: { left: '50%', top: '25%', transform: 'translateX(-50%)' } },
    h('h2', {}, 'Reading the waterfall'),
    h('p', {}, 'Every column is one gate position. Every row is one basis state. '
      + 'Hue is phase, brightness is magnitude.'),
    h('div', { class: 'help-foot' }, button('Got it', { variant: 'primary', onClick: dismiss })),
  );
}

const helpNote = (label, body, position) => h('div', {
  class: 'help-note',
  style: {
    left: `${clampLeft(position.left, position.width)}px`,
    top: `${Math.max(position.top, 8)}px`,
    width: `${position.width}px`,
  },
},
  h('div', { class: 'help-note-label' }, label),
  h('div', { class: 'help-note-body' }, body));

/* ---------- render ---------- */

function render() {
  const scrollTop = document.getElementById('body')?.scrollTop || 0;
  clear(root);
  root.append(topbar(), tabbar());

  const body = h('div', { id: 'body' });
  root.append(body);

  if (state.error) {
    body.append(h('div', { class: 'banner' }, state.error));
  }
  if (state.loading) {
    body.append(h('div', { class: 'placeholder' }, h('p', {}, 'Loading runs…')));
    return;
  }
  if (!state.detail || !state.waterfall) {
    body.append(emptyState());
    return;
  }

  const geo = geometry();
  if (state.tab === 'Timeline') body.append(...timelineTab(geo));
  else if (state.tab === 'State') body.append(...stateTab(geo));
  else if (state.tab === 'Diff') body.append(...diffTab(geo));
  else body.append(...assertionsTab(geo));

  // The tour annotates the timeline's own panels, so it belongs to that
  // tab whether it was opened by hand or shown on first run. Anywhere
  // else it would anchor its leader lines to whatever canvas happened to
  // be on screen.
  if (state.tab === 'Timeline'
      && (state.helpOpen || (!state.helpSeen && state.prefs.showTour))) {
    state.helpOpen = true;
    body.append(helpOverlay());
  }
  if (state.guideTopic) {
    body.append(guideOverlay({
      topicId: state.guideTopic,
      onTopic: (id) => { state.guideTopic = id; render(); },
      onClose: () => { state.guideTopic = null; render(); },
    }));
  }
  if (state.settingsOpen) {
    body.append(settingsOverlay({
      prefs: state.prefs,
      runSettings: state.detail?.settings || {},
      onChange: (key, value) => {
        state.prefs[key] = value;
        if (key === 'overlayExpected') state.overlay = value;
        persist();
        render();
      },
      onResetNotices: resetNotices,
      onClose: () => { state.settingsOpen = false; render(); },
    }));
  }
  body.scrollTop = scrollTop;
}

/** Bring every dismissed piece of guidance back. Someone who clicked a
 *  notice away before reading it has no other way to recover it. */
function resetNotices() {
  state.helpSeen = false;
  state.prefs.showTour = true;
  state.settingsOpen = false;
  state.guideTopic = null;
  state.tab = 'Timeline';
  state.helpOpen = true;
  persist();
  render();
}

function emptyState() {
  return h('div', { class: 'placeholder' },
    phaseQ(56, 45),
    h('h2', {}, 'Waiting for a circuit run'),
    h('p', {},
      'Record one against this trace source and it appears here live, '
      + 'with the whole execution laid out gate by gate.'),
    h('code', {}, 'qlens.run(circuit, trace=True)'),
    h('p', { class: 'dim' }, 'Or open the viewer on sample runs to try it first:'),
    h('code', {}, 'qlens view --demo'),
  );
}

/* ---------- boot ---------- */

async function selectRun(traceId) {
  try {
    state.error = null;
    await openRun(traceId);
  } catch (error) {
    state.error = String(error.message || error);
  }
  render();
}

let resizeHandle = 0;
window.addEventListener('resize', () => {
  clearTimeout(resizeHandle);
  resizeHandle = setTimeout(render, 100);
});

/** New and updated runs arrive here. An update to the run already open
 *  refetches it; anything else only refreshes the picker, so a suite
 *  running in the background never yanks the view out from under you. */
function listen() {
  const source = new EventSource('/api/stream');
  source.addEventListener('message', async (event) => {
    let summary;
    try { summary = JSON.parse(event.data); } catch { return; }
    const existing = state.runs.findIndex((r) => r.trace_id === summary.trace_id);
    if (existing === -1) state.runs.unshift(summary);
    else state.runs[existing] = summary;

    if (!state.traceId) { await selectRun(summary.trace_id); return; }
    if (summary.trace_id === state.traceId) {
      try {
        state.detail = await api(`/api/circuit?trace_id=${encodeURIComponent(state.traceId)}`);
        gatesByPosition = new Map(gateList().map((gate) => [gate.position, gate]));
      } catch { /* the run may be mid-write; the next event catches up */ }
    }
    render();
  });
  source.addEventListener('error', () => { /* EventSource reconnects on its own */ });
}

async function boot() {
  render();
  try {
    state.health = await api('/api/health');
    const runs = await loadRuns();
    state.loading = false;
    if (runs.length) await openRun(runs[0].trace_id);
  } catch (error) {
    state.loading = false;
    state.error = String(error.message || error);
  }
  render();
  listen();
}

boot();

/* Element construction and the small components the panels are built from.
 *
 * No framework and no build step: h() is the whole abstraction. Panels
 * re-render by replacing their children, which is cheap at this scale —
 * the expensive surfaces (waterfall, bars) are canvases that draw
 * imperatively and are never thrown away by a re-render.
 */

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style') Object.assign(el.style, value);
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key in el && key !== 'list') el[key] = value;
    else el.setAttribute(key, value);
  }
  append(el, children);
  return el;
}

export function svg(tag, props, ...children) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith('on')) el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

/* ---------- components ---------- */

export function panel(title, actions, ...body) {
  return h('section', { class: 'panel' },
    h('div', { class: 'panel-head' },
      h('h2', { class: 'panel-title' }, title),
      h('div', { class: 'panel-actions' }, actions || []),
    ),
    ...body,
  );
}

export const tag = (text) => h('span', { class: 'tag' }, text);
export const micro = (text) => h('span', { class: 'micro' }, text);

export function val(label, value) {
  return h('div', { class: 'val' }, micro(label), h('span', { class: 'val-num' }, value));
}

export function button(text, { variant = 'ghost', onClick, title } = {}) {
  return h('button', {
    class: `btn btn-${variant}`, type: 'button', title: title || null, onClick,
  }, text);
}

export function iconButton(glyph, label, { onClick, pressed } = {}) {
  return h('button', {
    class: 'btn-icon', type: 'button', title: label, 'aria-label': label,
    'aria-pressed': pressed === undefined ? null : String(!!pressed),
    onClick,
  }, glyph);
}

const FAIL_GLYPH = () => svg('svg', {
  width: 11, height: 11, viewBox: '0 0 16 16', fill: 'none',
  stroke: 'currentColor', 'stroke-width': 2, 'stroke-linecap': 'round',
},
  svg('rect', { x: 1.8, y: 1.8, width: 12.4, height: 12.4, rx: 1.5 }),
  svg('path', { d: 'M5.6 5.6 L10.4 10.4 M10.4 5.6 L5.6 10.4' }),
);

const WARN_GLYPH = () => svg('svg', {
  width: 11, height: 11, viewBox: '0 0 16 16', fill: 'none',
  stroke: 'currentColor', 'stroke-width': 2,
  'stroke-linecap': 'round', 'stroke-linejoin': 'round',
},
  svg('path', { d: 'M8 1.9 L14.6 13.6 L1.4 13.6 Z' }),
  svg('path', { d: 'M8 6.2 L8 9.4 M8 11.4 L8 11.5' }),
);

/** Severity ramp: failures carry a filled plate and a glyph, warnings an
 *  outline and a glyph, passes only colour. The weight of the treatment
 *  tracks how much the reader needs to care. */
export function status(tone, text) {
  const kids = [];
  if (tone === 'fail') kids.push(FAIL_GLYPH());
  if (tone === 'warn') kids.push(WARN_GLYPH());
  if (tone === 'live') kids.push(h('span', { class: 'led' }));
  kids.push(text);
  return h('span', { class: `status status-${tone}` }, ...kids);
}

export function toggle(label, checked, onChange) {
  return h('label', { class: 'switch' },
    h('input', { type: 'checkbox', checked, onChange: (e) => onChange(e.target.checked) }),
    h('span', { class: 'track' }),
    label,
  );
}

/** A row of mutually exclusive small buttons. */
export function segmented(options, current, onPick) {
  return h('div', { class: 'buttons' }, options.map((option) =>
    button(option.label, {
      variant: option.value === current ? 'primary' : 'ghost',
      onClick: () => onPick(option.value),
    })));
}

/** The Phase Q mark. The needle tracks a live value while playing and
 *  locks to 45 degrees at rest, where the gap and needle read as a Q. */
export function phaseQ(size, angleDeg) {
  const rad = (d) => (d * Math.PI) / 180;
  const at = (d, r) => [24 + r * Math.cos(rad(d)), 24 + r * Math.sin(rad(d))];
  const [sx, sy] = at(angleDeg + 13, 15);
  const [ex, ey] = at(angleDeg - 13, 15);
  const [nx, ny] = at(angleDeg, 23.4);
  const f = (n) => n.toFixed(2);
  return svg('svg', {
    width: size, height: size, viewBox: '0 0 48 48', fill: 'none',
    stroke: 'var(--accent-9)', 'stroke-linecap': 'round', 'aria-hidden': 'true',
  },
    svg('path', { d: `M ${f(sx)} ${f(sy)} A 15 15 0 1 1 ${f(ex)} ${f(ey)}`, 'stroke-width': 2.4 }),
    svg('path', { d: `M 24 24 L ${f(nx)} ${f(ny)}`, 'stroke-width': 4 }),
    svg('circle', { cx: 24, cy: 24, r: 2.6, fill: 'var(--accent-9)', stroke: 'none' }),
  );
}

/* ---------- formatting ---------- */

export const bits = (index, numQubits) =>
  index.toString(2).padStart(Math.max(numQubits, 1), '0');

export const ket = (index, numQubits) => `|${bits(index, numQubits)}⟩`;

export function fixed(value, places = 4) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  return value.toFixed(places);
}

/** Small numbers in a test report are usually tolerances or deviations,
 *  where the exponent is the whole story. */
export function sci(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  if (value === 0) return '0';
  const magnitude = Math.abs(value);
  if (magnitude < 1e-3 || magnitude >= 1e5) return value.toExponential(2);
  return value.toFixed(4);
}

export function signed(value, places = 4) {
  if (!Number.isFinite(value)) return '—';
  return (value >= 0 ? '+' : '−') + Math.abs(value).toFixed(places);
}

/** Whether a difference survives rounding to the shown precision. A
 *  −1e-17 float printed as "−0.0000" in failure red reads as a problem
 *  the numbers do not actually describe. */
export function meaningful(value, places = 4) {
  return Number.isFinite(value) && Math.abs(value) >= 0.5 * 10 ** -places;
}

export function shortSource(source) {
  if (!source) return '—';
  const parts = source.split('/');
  return parts.length > 2 ? parts.slice(-2).join('/') : source;
}

/* Canvas surfaces: the waterfall heatmap, amplitude bars, and delta bars.
 *
 * Canvas rather than SVG throughout, including at small sizes. A 400-gate,
 * 10-qubit run is 400k cells; SVG would mean 400k nodes, and the point of
 * the waterfall is that it stays readable at full resolution. Using one
 * renderer at every size also means the small views and the large ones
 * cannot drift apart in how they map amplitude to colour.
 */

const HUE_BUCKETS = 72;
const LIGHT_BUCKETS = 48;

/* ---------- colour ---------- */

/** OKLCH to sRGB. The design tokens are authored in OKLCH and the
 *  waterfall needs per-pixel colour in a typed array, where CSS colour
 *  parsing is not available. */
export function oklchToRgb(lightness, chroma, hueDeg) {
  const hue = (hueDeg * Math.PI) / 180;
  const a = chroma * Math.cos(hue);
  const b = chroma * Math.sin(hue);
  const l_ = lightness + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = lightness - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = lightness - 0.0894841775 * a - 1.2914855480 * b;
  const l = l_ ** 3, m = m_ ** 3, s = s_ ** 3;
  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s;
  const encode = (v) => {
    const gamma = v <= 0.0031308 ? 12.92 * v : 1.055 * Math.max(v, 0) ** (1 / 2.4) - 0.055;
    return Math.max(0, Math.min(255, Math.round(gamma * 255)));
  };
  return [encode(r), encode(g), encode(bl)];
}

/** Phase wheel parameters, read from the stylesheet so the tokens stay
 *  the single source of truth for the palette. */
export function phaseTokens() {
  const style = getComputedStyle(document.documentElement);
  const lightness = style.getPropertyValue('--phase-l').trim() || '78%';
  const chroma = style.getPropertyValue('--phase-c').trim() || '0.13';
  return {
    css: { lightness, chroma },
    lightness: parseFloat(lightness) / 100,
    chroma: parseFloat(chroma),
  };
}

export const phaseColor = (hueDeg, tokens) =>
  `oklch(${tokens.css.lightness} ${tokens.css.chroma} ${hueDeg})`;

let cachedLut = null;

/** hue × lightness lookup table for the waterfall, built once. Per-pixel
 *  OKLCH conversion would be several hundred thousand cube roots per
 *  redraw; this is a few thousand, once. */
function lut() {
  if (cachedLut) return cachedLut;
  const tokens = phaseTokens();
  const table = new Uint8Array(HUE_BUCKETS * LIGHT_BUCKETS * 3);
  for (let hueIndex = 0; hueIndex < HUE_BUCKETS; hueIndex++) {
    for (let lightIndex = 0; lightIndex < LIGHT_BUCKETS; lightIndex++) {
      const k = lightIndex / (LIGHT_BUCKETS - 1);
      const [r, g, b] = oklchToRgb(
        tokens.lightness * k,
        tokens.chroma * Math.min(1, k * 1.5),
        hueIndex * (360 / HUE_BUCKETS),
      );
      const offset = (hueIndex * LIGHT_BUCKETS + lightIndex) * 3;
      table[offset] = r; table[offset + 1] = g; table[offset + 2] = b;
    }
  }
  cachedLut = table;
  return table;
}

export const decodePlane = (base64) =>
  Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));

/* ---------- waterfall ---------- */

/** Paint the magnitude/phase planes into an offscreen canvas at their
 *  native cell resolution. Scaling to the panel happens at draw time, so
 *  a resize never re-runs the colour mapping. */
export function buildHeatmap(waterfall) {
  const { rows, num_positions: columns } = waterfall;
  const magnitude = decodePlane(waterfall.magnitude);
  const phase = decodePlane(waterfall.phase);
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(columns, 1);
  canvas.height = Math.max(rows, 1);
  const ctx = canvas.getContext('2d');
  const image = ctx.createImageData(canvas.width, canvas.height);
  const data = image.data;
  const table = lut();
  // Target tone curve on normalized magnitude: wider state spaces spread
  // their amplitude thinner and need more lift before the low end reads
  // as anything but black. The bytes already carry (m/peak)^mag_exponent,
  // so the residual exponent is what remains to reach the target — not
  // the target itself, which would compound the two curves and wash the
  // whole field out.
  const states = Math.max(waterfall.num_states, 2);
  const target = 6 / (6 + Math.log2(states));
  const residual = target / (waterfall.mag_exponent || 1);
  const levels = new Uint8Array(256);
  for (let i = 0; i < 256; i++) {
    levels[i] = Math.min(
      LIGHT_BUCKETS - 1,
      Math.round((i / 255) ** residual * (LIGHT_BUCKETS - 1)),
    );
  }

  for (let i = 0; i < rows * columns; i++) {
    const hueIndex = Math.min(HUE_BUCKETS - 1, Math.floor((phase[i] / 256) * HUE_BUCKETS));
    const offset = (hueIndex * LIGHT_BUCKETS + levels[magnitude[i]]) * 3;
    const out = i * 4;
    data[out] = table[offset];
    data[out + 1] = table[offset + 1];
    data[out + 2] = table[offset + 2];
    data[out + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
  return canvas;
}

export function drawWaterfall(canvas, { heatmap, waterfall, width, height, index, marks }) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = 'oklch(10% 0.01 258)';
  ctx.fillRect(0, 0, width, height);
  if (heatmap) ctx.drawImage(heatmap, 0, 0, width, height);

  const columns = Math.max(waterfall.num_positions, 1);
  const xAt = (i) => Math.round(((i + 0.5) / columns) * width) + 0.5;

  // The server returns segments only when they read as bands, so there
  // is no second threshold to keep in step here.
  const segments = waterfall.segments || [];
  if (segments.length > 1) {
    ctx.strokeStyle = 'oklch(55% 0.02 258 / 0.85)';
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 3]);
    for (const [, end] of segments.slice(0, -1)) {
      const y = Math.round(((end + 1) / waterfall.kept_rows) * height) + 0.5;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
    }
    ctx.setLineDash([]);
  }

  for (const mark of marks || []) {
    if (mark.index === null) continue;
    ctx.strokeStyle = mark.pass ? 'oklch(76% 0.18 148 / 0.5)' : 'oklch(68% 0.2 25 / 0.85)';
    ctx.lineWidth = 1;
    const x = xAt(mark.index);
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke();
  }

  ctx.strokeStyle = 'oklch(78% 0.17 175)';
  ctx.lineWidth = 1.5;
  const head = xAt(index);
  ctx.beginPath(); ctx.moveTo(head, 0); ctx.lineTo(head, height); ctx.stroke();
}

/* ---------- bars ---------- */

/** Observed probabilities, optionally with an expected distribution
 *  ghosted behind them. Bar colour is the phase of that amplitude. */
export function drawBars(canvas, {
  observed, expected, hues, width, height, tokens, focus = null,
}) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const base = height - 1;
  const count = observed.length || 1;
  const slot = width / count;
  const peak = Math.max(...observed, ...(expected || [0]), 1e-12) * 1.08;

  ctx.strokeStyle = 'oklch(30% 0.014 258 / 0.55)';
  ctx.lineWidth = 1;
  for (let g = 1; g <= 4; g++) {
    const y = Math.round(base - (base * g) / 4) + 0.5;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
  }

  if (expected) {
    for (let k = 0; k < expected.length; k++) {
      const barHeight = (expected[k] / peak) * (base - 4);
      ctx.globalAlpha = focus === null || focus === k ? 1 : 0.25;
      ctx.fillStyle = 'oklch(72% 0.01 258 / 0.16)';
      ctx.fillRect(k * slot + slot * 0.08, base - barHeight, slot * 0.84, barHeight);
      ctx.strokeStyle = 'oklch(72% 0.01 258 / 0.55)';
      ctx.setLineDash([3, 2]);
      ctx.beginPath();
      ctx.moveTo(k * slot + slot * 0.08, base - barHeight + 0.5);
      ctx.lineTo(k * slot + slot * 0.92, base - barHeight + 0.5);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.globalAlpha = 1;
  }

  const barWidth = expected ? slot * 0.48 : slot * 0.7;
  const inset = expected ? slot * 0.26 : slot * 0.15;
  for (let k = 0; k < observed.length; k++) {
    const barHeight = (observed[k] / peak) * (base - 4);
    // Focusing one bar dims the rest rather than hiding them, so the
    // one under inspection keeps its context: how tall it is relative to
    // everything else is most of what makes it worth looking at.
    ctx.globalAlpha = focus === null || focus === k ? 1 : 0.18;
    ctx.fillStyle = phaseColor(hues ? hues[k] : 175, tokens);
    ctx.fillRect(
      k * slot + inset, base - barHeight,
      Math.max(barWidth, 1), Math.max(barHeight, observed[k] > 0 ? 1 : 0),
    );
  }
  ctx.globalAlpha = 1;
  if (focus !== null && focus >= 0 && focus < observed.length) {
    ctx.strokeStyle = 'oklch(96% 0.004 258 / 0.5)';
    ctx.lineWidth = 1;
    ctx.strokeRect(Math.round(focus * slot) + 0.5, 0.5, Math.max(slot, 2), base);
  }

  ctx.strokeStyle = 'oklch(38% 0.016 258)';
  ctx.beginPath(); ctx.moveTo(0, base + 0.5); ctx.lineTo(width, base + 0.5); ctx.stroke();
}

/** Which bar a pointer is over, or null when past the ends. */
export function barAtPointer(event, canvas, count) {
  const box = canvas.getBoundingClientRect();
  if (box.width <= 0 || count <= 0) return null;
  const index = Math.floor(((event.clientX - box.left) / box.width) * count);
  return index >= 0 && index < count ? index : null;
}

/** Signed differences around a centre line. */
export function drawDeltaBars(canvas, { a, b, hues, width, height, tokens }) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const middle = height / 2;
  const count = a.length || 1;
  const slot = width / count;
  let peak = 0;
  for (let i = 0; i < count; i++) peak = Math.max(peak, Math.abs(b[i] - a[i]));
  peak = peak || 1;

  ctx.strokeStyle = 'oklch(30% 0.014 258 / 0.55)';
  ctx.lineWidth = 1;
  for (const fraction of [0.25, 0.75]) {
    const y = Math.round(height * fraction) + 0.5;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke();
  }

  for (let k = 0; k < count; k++) {
    const delta = ((b[k] - a[k]) / peak) * (middle - 6);
    ctx.fillStyle = phaseColor(hues ? hues[k] : 175, tokens);
    ctx.fillRect(
      k * slot + slot * 0.15, delta >= 0 ? middle - delta : middle,
      Math.max(slot * 0.7, 1), Math.max(Math.abs(delta), 0.8),
    );
  }

  ctx.strokeStyle = 'oklch(38% 0.016 258)';
  ctx.beginPath(); ctx.moveTo(0, middle + 0.5); ctx.lineTo(width, middle + 0.5); ctx.stroke();
}

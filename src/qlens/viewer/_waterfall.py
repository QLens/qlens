"""Server-side reduction of a run's spooled statevectors into the
amplitude waterfall the viewer draws.

The waterfall is one column per captured position and one row per basis
state: for a 10-qubit, 400-gate run that is 400k complex amplitudes,
which is not something to ship to a browser as JSON. So the reduction
happens here, in numpy, and the payload is two base64 uint8 planes at
display resolution — magnitude and phase — which the frontend maps
through its colour table without further arithmetic per pixel.

Magnitude is quantized on a fourth-root scale rather than linearly.
Amplitudes in a real circuit span several decades, and 256 linear levels
put almost all of them in the bottom bucket; the fourth root spreads
them across the range, and the frontend applies only a residual gamma.
"""

from __future__ import annotations

import base64
import threading
from pathlib import Path
from typing import Any

import numpy as np

# Magnitude pre-warp applied before quantizing to 8 bits. Documented in
# the payload as `mag_exponent` so the frontend never has to assume it.
_MAG_EXPONENT = 0.25
# Loading and unpacking a compressed sidecar costs real work, and the
# frontend refetches whenever the collapse threshold moves. Two runs is
# enough to cover the common flow (one open run, one being compared).
_CACHE_LIMIT = 2
_MAX_SEGMENTS = 24
# Percentile of the magnitude field that maps to full brightness. High
# enough that only genuinely dominant amplitudes clip, low enough that a
# single concentrated column cannot set the scale for the whole run.
_NORMALIZE_PERCENTILE = 99.5


class _Grid:
    """One run's spooled statevectors, unpacked. Rows are basis states,
    columns are captured positions."""

    def __init__(self, amplitudes: np.ndarray, positions: list[int]):
        self.amplitudes = amplitudes  # complex128 [num_states, num_positions]
        self.positions = positions
        self.magnitude = np.abs(amplitudes).astype(np.float32)
        # Phase in turns rather than radians: the frontend wants a hue
        # fraction, and this keeps the wrap at the quantizer boundary exact.
        self.phase = ((np.angle(amplitudes) / (2 * np.pi)) % 1.0).astype(np.float32)
        self.maximum = float(self.magnitude.max()) if self.magnitude.size else 0.0
        # Normalizing on the absolute maximum makes most runs unreadable:
        # a circuit starts in a basis state, so position 0 has one
        # amplitude at 1.0, and every later column — where a spread-out
        # state peaks two orders of magnitude lower — collapses to black
        # against it. A high percentile tracks the body of the data
        # instead and lets the few dominant cells clip.
        self.peak = (
            float(np.percentile(self.magnitude, _NORMALIZE_PERCENTILE))
            if self.magnitude.size else 0.0
        ) or self.maximum
        self.row_max = (
            self.magnitude.max(axis=1) if self.magnitude.size else np.zeros(0)
        )

    def column(self, position: int) -> np.ndarray:
        return self.amplitudes[:, self.positions.index(position)]


_cache: dict[tuple[str, float], _Grid] = {}
_cache_lock = threading.Lock()


def load(path: Path) -> _Grid:
    """Unpack a run's sidecar, memoised on (path, mtime).

    Scrubbing the viewer asks for one position after another and the
    collapse control refetches the whole grid, so the decompression cost
    is worth paying once per run rather than once per request.
    """
    key = (str(path), path.stat().st_mtime)
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit

    with np.load(path) as archive:
        positions = sorted(int(name[4:]) for name in archive.files)
        columns = [np.asarray(archive[f"pos_{p}"], dtype=np.complex128) for p in positions]
    stacked = (
        np.stack(columns, axis=1) if columns else np.zeros((0, 0), dtype=np.complex128)
    )
    grid = _Grid(stacked, positions)

    with _cache_lock:
        if len(_cache) >= _CACHE_LIMIT:
            _cache.pop(next(iter(_cache)))
        _cache[key] = grid
    return grid


def _segments(kept: np.ndarray) -> list[list[int]]:
    """Contiguous runs within the kept row indices, in kept-row space, so
    the frontend can rule a line where basis states were skipped.

    Returns nothing past _MAX_SEGMENTS: dozens of rules mark no structure,
    they just fill the field with dashes. The frontend draws whatever
    comes back, so the judgement lives here rather than in both places.
    """
    if kept.size == 0:
        return []
    breaks = np.flatnonzero(np.diff(kept) != 1)
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [kept.size - 1]))
    if starts.size > _MAX_SEGMENTS:
        return []
    return [[int(a), int(b)] for a, b in zip(starts, ends, strict=True)]


def _band(values: np.ndarray, rows: int, take_from: np.ndarray | None = None) -> np.ndarray:
    """Reduce ``values`` down the row axis to ``rows`` bands.

    Each band contributes its largest-magnitude row. Padding to a whole
    number of bands lets one reshape do the whole reduction; the pad rows
    are zero magnitude, so they never win a band unless the band is
    entirely empty anyway.
    """
    source, positions = values.shape
    band = -(-source // rows)  # ceil
    pad = rows * band - source
    if pad:
        values = np.concatenate((values, np.zeros((pad, positions), values.dtype)))
        if take_from is not None:
            take_from = np.concatenate(
                (take_from, np.zeros((pad, positions), take_from.dtype))
            )
    shaped = values.reshape(rows, band, positions)
    winners = shaped.argmax(axis=1)[:, None, :]
    if take_from is None:
        return np.take_along_axis(shaped, winners, axis=1)[:, 0, :]
    return np.take_along_axis(take_from.reshape(rows, band, positions), winners, axis=1)[
        :, 0, :
    ]


def _encode(plane: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(plane).tobytes()).decode("ascii")


def build(
    path: Path,
    *,
    num_qubits: int,
    max_rows: int,
    threshold: float,
) -> dict[str, Any]:
    """Reduce a run's sidecar to a display-resolution waterfall payload."""
    grid = load(path)
    num_states, num_positions = grid.magnitude.shape

    kept = (
        np.flatnonzero(grid.row_max >= threshold)
        if threshold > 0
        else np.arange(num_states)
    )
    if kept.size == 0:
        # Every basis state is below the threshold; showing nothing is
        # worse than ignoring the filter, so fall back to the full set.
        kept = np.arange(num_states)
        threshold = 0.0

    magnitude = grid.magnitude[kept]
    phase = grid.phase[kept]
    rows = min(int(kept.size), max(1, int(max_rows)))
    if kept.size > rows:
        phase = _band(magnitude, rows, take_from=phase)
        magnitude = _band(magnitude, rows)

    peak = grid.peak or 1.0
    warped = np.power(magnitude / peak, _MAG_EXPONENT, dtype=np.float32)
    mag_bytes = np.clip(warped * 255.0, 0, 255).astype(np.uint8)
    # Phase wraps, so 256 maps back to 0 rather than clipping to 255.
    phase_bytes = (np.rint(phase * 256.0).astype(np.int32) % 256).astype(np.uint8)

    return {
        "num_qubits": num_qubits,
        "num_states": int(num_states),
        "positions": grid.positions,
        "num_positions": int(num_positions),
        "rows": int(mag_bytes.shape[0]) if mag_bytes.size else 0,
        "first_row_state": int(kept[0]) if kept.size else 0,
        "last_row_state": int(kept[-1]) if kept.size else 0,
        "kept_rows": int(kept.size),
        "elided_rows": int(num_states - kept.size),
        "segments": _segments(kept) if threshold > 0 else [],
        "threshold": float(threshold),
        "peak": peak,
        "maximum": grid.maximum,
        "mag_exponent": _MAG_EXPONENT,
        "row_max": [float(v) for v in grid.row_max],
        "magnitude": _encode(mag_bytes),
        "phase": _encode(phase_bytes),
    }

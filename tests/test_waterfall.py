"""Waterfall reduction: degenerate and hostile inputs first.

Every case here is one the reduction can actually meet in the field —
one-gate runs, states that are exactly a basis state, amplitudes spanning
ten decades, thresholds that keep nothing, row counts that do not divide
the basis size — because the reduction runs on whatever a user's circuit
produced, not on a shape chosen to suit it.
"""

from __future__ import annotations

import base64
import math
from pathlib import Path

import numpy as np
import pytest

from qlens.viewer import _waterfall as waterfall


def write(path: Path, columns: list[np.ndarray]) -> Path:
    """Spool a hand-built run to a sidecar, the shape write_sidecar makes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path, **{f"pos_{i}": np.asarray(c, dtype=np.complex128) for i, c in enumerate(columns)}
    )
    return path


def planes(payload: dict) -> tuple[np.ndarray, np.ndarray]:
    shape = (payload["rows"], payload["num_positions"])
    return (
        np.frombuffer(base64.b64decode(payload["magnitude"]), dtype=np.uint8).reshape(shape),
        np.frombuffer(base64.b64decode(payload["phase"]), dtype=np.uint8).reshape(shape),
    )


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    # The grid cache is keyed on (path, mtime); tmp_path reuse within one
    # second could otherwise serve a previous test's grid.
    waterfall._cache.clear()


# -- degenerate runs ---------------------------------------------------


def test_single_position_run(tmp_path: Path) -> None:
    path = write(tmp_path / "a.npz", [np.array([1, 0, 0, 0])])
    payload = waterfall.build(path, num_qubits=2, max_rows=512, threshold=0)
    assert payload["num_positions"] == 1
    assert payload["rows"] == 4
    magnitude, _ = planes(payload)
    assert magnitude[0, 0] == 255  # the occupied state saturates
    assert magnitude[1:, 0].max() == 0


def test_single_state_run(tmp_path: Path) -> None:
    """One qubit is the smallest real circuit; the reduction must not
    assume it can band or split anything."""
    path = write(tmp_path / "a.npz", [np.array([1, 0]), np.array([0, 1])])
    payload = waterfall.build(path, num_qubits=1, max_rows=512, threshold=0)
    assert (payload["rows"], payload["num_positions"]) == (2, 2)


def test_all_zero_state_does_not_divide_by_zero(tmp_path: Path) -> None:
    """A normalized statevector can never be all zeros, but a truncated
    or corrupt sidecar can be, and it must not raise."""
    path = write(tmp_path / "a.npz", [np.zeros(4), np.zeros(4)])
    payload = waterfall.build(path, num_qubits=2, max_rows=512, threshold=0)
    magnitude, _ = planes(payload)
    assert magnitude.max() == 0
    assert payload["peak"] > 0  # never zero, or the client divides by it


def test_positions_are_ordered_numerically_not_lexically(tmp_path: Path) -> None:
    """Sidecar keys are pos_0 … pos_11; sorting them as strings puts
    pos_10 before pos_2 and silently transposes the time axis."""
    columns = [np.eye(16, dtype=np.complex128)[i] for i in range(12)]
    path = write(tmp_path / "a.npz", columns)
    payload = waterfall.build(path, num_qubits=4, max_rows=512, threshold=0)
    assert payload["positions"] == list(range(12))
    magnitude, _ = planes(payload)
    # Column i must be the one with row i lit.
    assert [int(magnitude[:, i].argmax()) for i in range(12)] == list(range(12))


# -- dynamic range -----------------------------------------------------


def test_amplitudes_spanning_ten_decades_stay_distinguishable(tmp_path: Path) -> None:
    """Linear 8-bit quantization would floor everything below ~1/255 of
    the peak to zero, which is most of a real circuit's state."""
    state = np.array([10.0**-k for k in range(8)], dtype=np.complex128)
    path = write(tmp_path / "a.npz", [state, state])
    payload = waterfall.build(path, num_qubits=3, max_rows=512, threshold=0)
    magnitude, _ = planes(payload)
    levels = magnitude[:, 0]
    # Strictly decreasing: every decade lands in a different bucket.
    assert list(levels) == sorted(levels, reverse=True)
    assert len(set(levels.tolist())) == 8


def test_peak_ignores_a_lone_dominant_column(tmp_path: Path) -> None:
    """Position 0 of any circuit is a basis state at magnitude 1, two
    orders above the spread-out columns that follow."""
    initial = np.zeros(64, dtype=np.complex128)
    initial[0] = 1.0
    spread = np.full(64, 1 / 8, dtype=np.complex128)
    path = write(tmp_path / "a.npz", [initial, *([spread] * 40)])
    payload = waterfall.build(path, num_qubits=6, max_rows=512, threshold=0)
    assert payload["maximum"] == pytest.approx(1.0)
    assert payload["peak"] < 0.5
    magnitude, _ = planes(payload)
    # The body of the run must land in usable range, not near black.
    assert magnitude[:, 20].min() > 128


def test_phase_covers_the_wheel_uniformly(tmp_path: Path) -> None:
    """256 buckets over one turn, so a quarter turn is exactly 64."""
    angles = [0, math.pi / 2, math.pi, -math.pi / 2]
    state = np.array([np.exp(1j * a) for a in angles], dtype=np.complex128)
    path = write(tmp_path / "a.npz", [state])
    payload = waterfall.build(path, num_qubits=2, max_rows=512, threshold=0)
    _, phase = planes(payload)
    assert [int(v) for v in phase[:, 0]] == [0, 64, 128, 192]


def test_phase_just_below_zero_wraps_to_zero(tmp_path: Path) -> None:
    """The seam of the wheel. A phase infinitesimally below zero is the
    same hue as zero, so it must quantize to the same byte — scaling by
    255 and clamping instead sends it to the far end of the ramp."""
    state = np.array([np.exp(-1e-9j), 1.0], dtype=np.complex128)
    path = write(tmp_path / "a.npz", [state])
    payload = waterfall.build(path, num_qubits=1, max_rows=512, threshold=0)
    _, phase = planes(payload)
    assert phase[0, 0] == 0
    assert phase[1, 0] == 0


def test_band_reports_the_phase_of_its_largest_row(tmp_path: Path) -> None:
    """A band collapses several basis states into one pixel, and the one
    worth showing is the dominant amplitude. Reducing the phase plane on
    its own value instead would paint the band with the hue of whichever
    negligible state happened to sit furthest around the wheel."""
    state = np.array([
        0.9 * np.exp(0.05j * 2 * np.pi),   # dominant, near the start of the wheel
        0.01 * np.exp(0.90j * 2 * np.pi),  # negligible, near the end of it
    ], dtype=np.complex128)
    path = write(tmp_path / "a.npz", [state])
    payload = waterfall.build(path, num_qubits=1, max_rows=1, threshold=0)
    magnitude, phase = planes(payload)
    assert magnitude[0, 0] == 255
    assert phase[0, 0] == pytest.approx(0.05 * 256, abs=1)


# -- banding -----------------------------------------------------------


def test_banding_keeps_the_largest_row_in_each_band(tmp_path: Path) -> None:
    state = np.array([0.1, 0.9, 0.2, 0.8, 0.3, 0.7, 0.4, 0.6], dtype=np.complex128)
    path = write(tmp_path / "a.npz", [state])
    payload = waterfall.build(path, num_qubits=3, max_rows=4, threshold=0)
    magnitude, _ = planes(payload)
    peak = payload["peak"]
    expected = [
        round(255 * (max(state[i].real, state[i + 1].real) / peak) ** payload["mag_exponent"])
        for i in (0, 2, 4, 6)
    ]
    assert [int(v) for v in magnitude[:, 0]] == pytest.approx(expected, abs=1)


def test_banding_when_rows_do_not_divide_evenly(tmp_path: Path) -> None:
    """7 rows into 3 bands: the padding must not win a band or drop data."""
    state = np.array([1, 2, 3, 4, 5, 6, 7], dtype=np.complex128) / 20
    path = write(tmp_path / "a.npz", [state])
    payload = waterfall.build(path, num_qubits=3, max_rows=3, threshold=0)
    magnitude, _ = planes(payload)
    assert payload["rows"] == 3
    assert magnitude[:, 0].min() > 0  # no band came back empty
    assert list(magnitude[:, 0]) == sorted(magnitude[:, 0])


def test_max_rows_above_the_basis_size_does_not_upsample(tmp_path: Path) -> None:
    path = write(tmp_path / "a.npz", [np.full(4, 0.5, dtype=np.complex128)])
    payload = waterfall.build(path, num_qubits=2, max_rows=4096, threshold=0)
    assert payload["rows"] == 4


def test_max_rows_of_one_collapses_to_a_single_band(tmp_path: Path) -> None:
    path = write(tmp_path / "a.npz", [np.array([0.1, 0.9, 0.2, 0.3])])
    payload = waterfall.build(path, num_qubits=2, max_rows=1, threshold=0)
    magnitude, _ = planes(payload)
    assert payload["rows"] == 1
    assert magnitude[0, 0] == 255  # the run's largest amplitude survives


# -- thresholds --------------------------------------------------------


def test_threshold_keeps_rows_at_exactly_the_boundary(tmp_path: Path) -> None:
    state = np.array([0.5, 0.25, 0.1, 0.0], dtype=np.complex128)
    path = write(tmp_path / "a.npz", [state])
    payload = waterfall.build(path, num_qubits=2, max_rows=512, threshold=0.25)
    assert payload["kept_rows"] == 2  # 0.25 is kept, not excluded


def test_threshold_keeping_nothing_falls_back_to_everything(tmp_path: Path) -> None:
    path = write(tmp_path / "a.npz", [np.array([0.1, 0.1, 0.1, 0.1])])
    payload = waterfall.build(path, num_qubits=2, max_rows=512, threshold=10.0)
    assert payload["kept_rows"] == 4
    assert payload["threshold"] == 0.0
    assert payload["segments"] == []


def test_negative_threshold_keeps_everything(tmp_path: Path) -> None:
    path = write(tmp_path / "a.npz", [np.array([0.5, 0.0, 0.5, 0.0])])
    payload = waterfall.build(path, num_qubits=2, max_rows=512, threshold=-1.0)
    assert payload["kept_rows"] == 4


def test_row_survives_on_its_peak_not_its_final_value(tmp_path: Path) -> None:
    """A state that carries amplitude mid-run and ends empty is exactly
    what the waterfall exists to show; filtering on the last column would
    hide it."""
    path = write(
        tmp_path / "a.npz",
        [np.array([1.0, 0.0]), np.array([0.0, 1.0]), np.array([1.0, 0.0])],
    )
    payload = waterfall.build(path, num_qubits=1, max_rows=512, threshold=0.5)
    assert payload["kept_rows"] == 2


def test_segments_report_gaps_in_kept_row_space(tmp_path: Path) -> None:
    state = np.array([1.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0], dtype=np.complex128)
    path = write(tmp_path / "a.npz", [state])
    payload = waterfall.build(path, num_qubits=3, max_rows=512, threshold=0.5)
    # Kept basis states 0, 2, 3, 6 become kept-row indices 0 | 1,2 | 3.
    assert payload["segments"] == [[0, 0], [1, 2], [3, 3]]
    assert payload["first_row_state"] == 0
    assert payload["last_row_state"] == 6


def test_segments_suppressed_when_too_fragmented(tmp_path: Path) -> None:
    """Ruling a line between every pair of rows is noise, not signal."""
    state = np.array([1.0 if i % 2 == 0 else 0.0 for i in range(256)], dtype=np.complex128)
    path = write(tmp_path / "a.npz", [state])
    payload = waterfall.build(path, num_qubits=8, max_rows=512, threshold=0.5)
    assert payload["kept_rows"] == 128
    assert payload["segments"] == []


# -- caching -----------------------------------------------------------


def test_rewritten_sidecar_is_reloaded(tmp_path: Path) -> None:
    """A live run appends to its sidecar; serving a stale cached grid
    would freeze the viewer at the first read."""
    path = tmp_path / "a.npz"
    write(path, [np.array([1.0, 0.0])])
    assert waterfall.build(path, num_qubits=1, max_rows=8, threshold=0)["num_positions"] == 1

    import os

    write(path, [np.array([1.0, 0.0]), np.array([0.0, 1.0])])
    os.utime(path, (0, 0))  # force a distinct mtime regardless of clock resolution
    assert waterfall.build(path, num_qubits=1, max_rows=8, threshold=0)["num_positions"] == 2


def test_cache_stays_bounded(tmp_path: Path) -> None:
    for i in range(5):
        path = write(tmp_path / f"{i}.npz", [np.array([1.0, 0.0])])
        waterfall.build(path, num_qubits=1, max_rows=8, threshold=0)
    assert len(waterfall._cache) <= waterfall._CACHE_LIMIT


def test_segments_suppressed_when_every_kept_row_is_isolated(tmp_path: Path) -> None:
    """A wide register worked in a sparse subspace keeps a few dozen rows
    scattered across hundreds; a rule at every one of them is dashes, not
    structure."""
    state = np.zeros(512, dtype=np.complex128)
    state[::11] = 0.1  # 47 isolated occupied rows
    path = write(tmp_path / "a.npz", [state])
    payload = waterfall.build(path, num_qubits=9, max_rows=1024, threshold=0.05)
    assert payload["kept_rows"] == 47
    assert payload["segments"] == []

"""Inspector: boundary and failure paths first, then the debugging flow."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from conftest import bell_program

import qlens
from qlens._inspect import Inspector


def _bell_inspector(build: Any) -> Inspector:
    return qlens.inspect(qlens.run(build(bell_program(), 2)))


def test_inspect_rejects_non_result() -> None:
    with pytest.raises(qlens.QlensError, match="ExecutionResult"):
        qlens.inspect({"snapshots": []})  # type: ignore[arg-type]


def test_step_past_end_raises(build: Any) -> None:
    ins = _bell_inspector(build)
    ins.goto(-1)
    with pytest.raises(qlens.QlensError, match="final position"):
        ins.step()


def test_step_back_at_start_raises(build: Any) -> None:
    ins = _bell_inspector(build)
    with pytest.raises(qlens.QlensError, match="position 0"):
        ins.step_back()


def test_goto_out_of_range(build: Any) -> None:
    ins = _bell_inspector(build)
    with pytest.raises(qlens.QlensError, match="out of range"):
        ins.goto(99)


def test_cursor_flow(build: Any) -> None:
    ins = _bell_inspector(build)
    assert ins.position == 0
    assert ins.current.gate in {"h", "hadamard"}
    snap = ins.step()
    assert ins.position == 1
    assert snap.qubits == (0, 1)
    ins.step_back()
    assert ins.position == 0
    assert ins.goto(-1).position == 1


def test_probabilities_at_each_position(build: Any) -> None:
    ins = _bell_inspector(build)
    # After H: half on |00>, half on |10> (big-endian).
    assert ins.probabilities() == pytest.approx({"00": 0.5, "10": 0.5})
    ins.step()
    assert ins.probabilities() == pytest.approx({"00": 0.5, "11": 0.5})


def test_diff_identical_positions(build: Any) -> None:
    ins = _bell_inspector(build)
    diff = ins.diff(0, 0)
    assert diff.fidelity == pytest.approx(1.0)
    assert diff.amplitude_deltas == {}


def test_diff_across_the_cnot(build: Any) -> None:
    ins = _bell_inspector(build)
    diff = ins.diff(0, 1)
    # The CNOT moves the |10> amplitude to |11>. Overlap <a|b> keeps only
    # the shared |00> term (1/2), so fidelity is 1/4; the deltas name
    # both basis states involved.
    assert diff.fidelity == pytest.approx(0.25)
    assert set(diff.amplitude_deltas) == {"10", "11"}
    assert diff.amplitude_deltas["10"] == pytest.approx(-1 / np.sqrt(2))
    assert diff.amplitude_deltas["11"] == pytest.approx(1 / np.sqrt(2))


def test_len_matches_snapshots(build: Any) -> None:
    assert len(_bell_inspector(build)) == 2

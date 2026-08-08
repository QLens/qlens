"""Sidecar spooling: malformed refs and missing files first."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import qlens
from qlens._execution import Snapshot
from qlens.tracing._spool import (
    load_snapshots,
    parse_ref,
    read_ref,
    state_ref,
    write_sidecar,
)


def _snap(position: int, state: np.ndarray) -> Snapshot:
    return Snapshot(
        position=position,
        gate="h",
        qubits=(0,),
        params={},
        statevector=state.astype(np.complex128),
    )


def test_parse_ref_rejects_missing_fragment() -> None:
    with pytest.raises(qlens.QlensError, match="malformed"):
        parse_ref("trc_abc.npz")


def test_parse_ref_rejects_bad_position() -> None:
    with pytest.raises(qlens.QlensError, match="malformed"):
        parse_ref("trc_abc.npz#pos_xyz")


def test_parse_ref_round_trip() -> None:
    assert parse_ref(state_ref("trc_abc", 17)) == ("trc_abc.npz", 17)


def test_read_ref_missing_file(tmp_path: Path) -> None:
    with pytest.raises(qlens.QlensError, match="does not exist"):
        read_ref(tmp_path, "trc_gone.npz#pos_0")


def test_read_ref_missing_position(tmp_path: Path) -> None:
    write_sidecar(tmp_path, "trc_abc", [_snap(0, np.array([1.0, 0.0]))])
    with pytest.raises(qlens.QlensError, match="no entry"):
        read_ref(tmp_path, "trc_abc.npz#pos_5")


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    state = np.array([0.6, 0.8j])
    write_sidecar(tmp_path, "trc_abc", [_snap(3, state)])
    loaded = read_ref(tmp_path, state_ref("trc_abc", 3))
    assert loaded.dtype == np.complex128
    assert np.allclose(loaded, state)


def test_load_snapshots_rejects_alien_record(tmp_path: Path) -> None:
    with pytest.raises(qlens.QlensError, match="missing trace_id"):
        load_snapshots({"action": "something.else"}, tmp_path)


def test_load_snapshots_rejects_gateless_trace(tmp_path: Path) -> None:
    write_sidecar(tmp_path, "trc_abc", [_snap(0, np.array([1.0, 0.0]))])
    record = {"trace_id": "trc_abc", "meta": {"num_qubits": 1}, "events": []}
    with pytest.raises(qlens.QlensError, match="no gate events"):
        load_snapshots(record, tmp_path)


def test_load_snapshots_from_layer_events(tmp_path: Path) -> None:
    states = [np.array([0.0, 1.0]), np.array([1.0, 0.0])]
    write_sidecar(tmp_path, "trc_abc", [_snap(i, s) for i, s in enumerate(states)])
    record = {
        "trace_id": "trc_abc",
        "meta": {"num_qubits": 1},
        "events": [
            {
                "kind": "gate",
                "operation": "apply_layer",
                "gates": [
                    {"gate": "x", "qubits": [0], "params": {}, "position": 0},
                    {"gate": "x", "qubits": [0], "params": {}, "position": 1},
                ],
            },
            {"kind": "qstate", "operation": "snapshot", "position": 1},
        ],
    }
    snapshots, num_qubits = load_snapshots(record, tmp_path)
    assert num_qubits == 1
    assert [s.position for s in snapshots] == [0, 1]
    assert np.allclose(snapshots[0].statevector, states[0])
    assert np.allclose(snapshots[1].statevector, states[1])

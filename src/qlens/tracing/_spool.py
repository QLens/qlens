"""Statevector sidecar spooling.

TraceAct's payload budget (8KB default) deletes oversized values at
capture time, so amplitude arrays never enter trace records. The
adapter writes them to one compressed ``.npz`` per trace, keyed by gate
position, and events carry only a reference string:

    <trace_id>.npz#pos_<position>

References are relative to the spool directory, so a trace folder can
move machines as a unit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from qlens._errors import QlensError
from qlens._execution import Snapshot


def spool_path(state_dir: str | Path, trace_id: str) -> Path:
    return Path(state_dir) / f"{trace_id}.npz"


def state_ref(trace_id: str, position: int) -> str:
    return f"{trace_id}.npz#pos_{position}"


def write_sidecar(state_dir: str | Path, trace_id: str, snapshots: list[Snapshot]) -> Path:
    """Write every snapshot's statevector to the trace's sidecar file."""
    path = spool_path(state_dir, trace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, Any] = {f"pos_{s.position}": s.statevector for s in snapshots}
    np.savez_compressed(path, **arrays)
    return path


def parse_ref(ref: str) -> tuple[str, int]:
    """Split a statevector_ref into (filename, position)."""
    filename, sep, fragment = ref.partition("#")
    if not sep or not fragment.startswith("pos_"):
        raise QlensError(
            f"malformed statevector_ref {ref!r}; expected '<file>.npz#pos_<n>'"
        )
    try:
        position = int(fragment[4:])
    except ValueError as exc:
        raise QlensError(
            f"malformed statevector_ref {ref!r}; position is not an integer"
        ) from exc
    return filename, position


def read_ref(state_dir: str | Path, ref: str) -> np.ndarray:
    """Load one statevector by reference."""
    filename, position = parse_ref(ref)
    path = Path(state_dir) / filename
    if not path.is_file():
        raise QlensError(
            f"statevector sidecar {path} does not exist; was the trace "
            "recorded with a different state_dir?"
        )
    with np.load(path) as archive:
        key = f"pos_{position}"
        if key not in archive:
            raise QlensError(f"sidecar {path} has no entry {key!r}")
        return np.asarray(archive[key], dtype=np.complex128)


def load_snapshots(
    trace_record: dict[str, Any], state_dir: str | Path
) -> tuple[list[Snapshot], int]:
    """Rebuild the full snapshot list of a recorded run from its trace
    record plus sidecar. Returns (snapshots, num_qubits)."""
    trace_id = str(trace_record.get("trace_id", ""))
    meta = trace_record.get("meta") or {}
    num_qubits = int(meta.get("num_qubits", 0))
    if not trace_id or not num_qubits:
        raise QlensError(
            "trace record is missing trace_id or meta.num_qubits; "
            "was it recorded by qlens?"
        )
    path = spool_path(state_dir, trace_id)
    if not path.is_file():
        raise QlensError(
            f"statevector sidecar {path} does not exist; was the trace "
            "recorded with a different state_dir?"
        )

    gates: list[dict[str, Any]] = []
    for event in trace_record.get("events") or []:
        if event.get("kind") != "gate":
            continue
        if event.get("operation") == "apply_layer":
            gates.extend(event.get("gates") or [])
        else:
            gates.append(
                {
                    "gate": event.get("gate", "?"),
                    "qubits": event.get("qubits", []),
                    "params": event.get("params", {}),
                    "position": event.get("position", 0),
                }
            )
    gates.sort(key=lambda g: int(g.get("position", 0)))
    if not gates:
        raise QlensError(f"trace {trace_id} contains no gate events")

    snapshots: list[Snapshot] = []
    with np.load(path) as archive:
        for gate in gates:
            position = int(gate["position"])
            key = f"pos_{position}"
            if key not in archive:
                raise QlensError(f"sidecar {path} has no entry {key!r}")
            snapshots.append(
                Snapshot(
                    position=position,
                    gate=str(gate.get("gate", "?")),
                    qubits=tuple(int(q) for q in gate.get("qubits", [])),
                    params={k: float(v) for k, v in (gate.get("params") or {}).items()},
                    statevector=np.asarray(archive[key], dtype=np.complex128),
                )
            )
    return snapshots, num_qubits

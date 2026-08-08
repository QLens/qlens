"""The inspect API: step-through debugging over a captured execution.

An Inspector is a cursor over an ExecutionResult's snapshots. Nothing
re-executes: Phase 1's instrumented run already captured the statevector
at every gate boundary, so stepping is a list index, and inspecting a
recorded trace (Inspector.from_trace) reads the spooled sidecar instead
of a live result.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from qlens._errors import QlensError
from qlens._execution import ExecutionResult, Snapshot


class Inspector:
    """Cursor-based step-through over captured snapshots."""

    def __init__(self, snapshots: list[Snapshot], num_qubits: int, backend: str) -> None:
        if not snapshots:
            raise QlensError("nothing to inspect: the execution captured no snapshots")
        self._snapshots = snapshots
        self.num_qubits = num_qubits
        self.backend = backend
        self._cursor = 0

    # -- construction ------------------------------------------------------

    @classmethod
    def from_result(cls, result: ExecutionResult) -> Inspector:
        return cls(result.snapshots, result.num_qubits, result.backend)

    @classmethod
    def from_trace(cls, trace_record: dict[str, Any], state_dir: str) -> Inspector:
        """Rebuild an inspector from a stored TraceAct record plus its
        statevector sidecar. ``state_dir`` is the spool directory the
        trace was recorded with."""
        from qlens.tracing._spool import load_snapshots

        snapshots, num_qubits = load_snapshots(trace_record, state_dir)
        backend = str(trace_record.get("meta", {}).get("backend", "unknown"))
        return cls(snapshots, num_qubits, backend)

    # -- cursor ------------------------------------------------------------

    @property
    def position(self) -> int:
        """Current gate position (0-based)."""
        return self._cursor

    @property
    def current(self) -> Snapshot:
        """Snapshot at the cursor."""
        return self._snapshots[self._cursor]

    def __len__(self) -> int:
        return len(self._snapshots)

    def step(self) -> Snapshot:
        """Advance one gate and return the snapshot there.

        Raises QlensError past the last gate, so a stepping loop
        terminates loudly instead of silently pinning to the end.
        """
        if self._cursor + 1 >= len(self._snapshots):
            raise QlensError(
                f"already at the final position ({self._cursor}); "
                "step_back() or goto() to move elsewhere"
            )
        self._cursor += 1
        return self.current

    def step_back(self) -> Snapshot:
        """Move back one gate and return the snapshot there."""
        if self._cursor == 0:
            raise QlensError("already at position 0")
        self._cursor -= 1
        return self.current

    def goto(self, position: int) -> Snapshot:
        """Jump to a gate position and return the snapshot there.

        Negative indices follow Python semantics.
        """
        if not -len(self._snapshots) <= position < len(self._snapshots):
            raise QlensError(
                f"position {position} out of range for {len(self._snapshots)} snapshots"
            )
        self._cursor = position % len(self._snapshots)
        return self.current

    # -- state inspection --------------------------------------------------

    def statevector(self) -> npt.NDArray[np.complex128]:
        """Statevector at the cursor, big-endian basis order."""
        return self.current.statevector

    def probabilities(self, *, threshold: float = 1e-12) -> dict[str, float]:
        """Basis-state probabilities at the cursor, big-endian bitstring
        keys, outcomes below ``threshold`` omitted."""
        probs = np.abs(self.current.statevector) ** 2
        return {
            format(i, f"0{self.num_qubits}b"): float(p)
            for i, p in enumerate(probs)
            if p > threshold
        }

    def diff(self, position_a: int, position_b: int, *, threshold: float = 1e-12) -> StateDiff:
        """Compare the states at two positions."""
        a = self._snapshots[position_a].statevector
        b = self._snapshots[position_b].statevector
        overlap = complex(np.vdot(a, b))
        deltas = {
            format(i, f"0{self.num_qubits}b"): complex(d)
            for i, d in enumerate(b - a)
            if abs(d) > threshold
        }
        return StateDiff(
            position_a=position_a,
            position_b=position_b,
            fidelity=float(abs(overlap) ** 2),
            amplitude_deltas=deltas,
        )


class StateDiff:
    """Result of comparing two captured states.

    fidelity: |<a|b>|^2 — 1.0 means the states are identical up to
    global phase; amplitude_deltas: per-basis-state complex difference
    (b minus a), near-zero entries omitted.
    """

    def __init__(
        self,
        *,
        position_a: int,
        position_b: int,
        fidelity: float,
        amplitude_deltas: dict[str, complex],
    ) -> None:
        self.position_a = position_a
        self.position_b = position_b
        self.fidelity = fidelity
        self.amplitude_deltas = amplitude_deltas

    def __repr__(self) -> str:
        return (
            f"StateDiff(positions {self.position_a}->{self.position_b}, "
            f"fidelity={self.fidelity:.6f}, "
            f"{len(self.amplitude_deltas)} changed amplitudes)"
        )


def inspect(source: ExecutionResult) -> Inspector:
    """Open an inspector over an executed circuit's captured snapshots."""
    if not isinstance(source, ExecutionResult):
        raise QlensError(
            f"inspect() takes an ExecutionResult from qlens.run(), got "
            f"{type(source).__qualname__}; for a stored trace use "
            "Inspector.from_trace(record, state_dir)"
        )
    return Inspector.from_result(source)

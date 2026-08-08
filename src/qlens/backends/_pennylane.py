"""PennyLane backend.

Statevector capture rewrites the QNode's tape, interleaving a
``qml.Snapshot()`` after every operation, and executes once through the
``qml.snapshots`` transform on ``default.qubit``. Counts execute a fresh
tape ending in ``qml.counts()`` over all wires.

PennyLane's conventions already match Qlens's canonical form (big-endian
bitstrings and basis ordering, wire 0 leftmost), so no reordering happens
at this boundary — the conversion burden falls entirely on little-endian
frameworks. See CONVENTIONS.md.

The provider package is imported inside methods, never at module level,
so the registry can load this module and call handles() without
pennylane installed.

The user's declared measurement (``qml.expval`` etc.) is ignored
everywhere: Qlens derives snapshots and counts from circuit structure
alone, keeping run()'s contract identical across backends.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from qlens._errors import UnsupportedCircuitError
from qlens._execution import ExecutionResult, Snapshot
from qlens._stats import max_unitarity_deviation, phase_invariant_allclose
from qlens.backends.base import Backend

_NON_UNITARY = frozenset({"MidMeasureMP", "Conditional"})


class PennyLaneBackend(Backend):
    """Backend for pennylane.QNode objects."""

    name = "pennylane"

    @classmethod
    def handles(cls, circuit: object) -> bool:
        module = type(circuit).__module__
        return module.startswith("pennylane.") and type(circuit).__qualname__ == "QNode"

    # -- execution ---------------------------------------------------------

    def run(self, circuit: Any, *, args: tuple[Any, ...] = ()) -> ExecutionResult:
        import pennylane as qml

        tape = self._tape(circuit, args)
        wires = self._wire_list(tape, circuit)
        num_qubits = len(wires)

        ops = list(tape.operations)
        # Leading identities allocate every wire in canonical order before
        # any real gate runs. Without them default.qubit tracks only the
        # wires touched so far, so early snapshots would span a subsystem
        # in first-use order instead of the full space in canonical order.
        interleaved: list[Any] = [qml.Identity(w) for w in wires]
        for op in ops:
            interleaved.append(op)
            interleaved.append(qml.Snapshot())
        snap_tape = qml.tape.QuantumTape(
            ops=interleaved, measurements=[qml.state()], shots=None
        )
        device = qml.device("default.qubit", wires=wires)
        tapes, processing = qml.snapshots(snap_tape)
        results = processing(device.execute(tapes))

        snapshots: list[Snapshot] = []
        for position, op in enumerate(ops):
            state = np.asarray(results[position], dtype=np.complex128).reshape(-1)
            if state.shape != (2**num_qubits,):
                raise UnsupportedCircuitError(
                    f"snapshot at position {position} spans {state.shape[0]} "
                    f"amplitudes, expected {2**num_qubits}; the device did not "
                    "allocate all wires"
                )
            snapshots.append(
                Snapshot(
                    position=position,
                    gate=op.name.lower(),
                    qubits=tuple(wires.index(w) for w in op.wires),
                    params={f"p{i}": float(p) for i, p in enumerate(op.parameters)},
                    statevector=state,
                )
            )
        if not snapshots:
            initial = np.zeros(2**num_qubits, dtype=np.complex128)
            initial[0] = 1.0
            snapshots.append(
                Snapshot(position=0, gate="initial", qubits=(), params={}, statevector=initial)
            )
        return ExecutionResult(
            backend=self.name,
            num_qubits=num_qubits,
            snapshots=snapshots,
            _counts_fn=lambda shots: self.counts(circuit, shots=shots, args=args),
        )

    # -- structural checks -------------------------------------------------

    def operator_matrix(
        self, circuit: Any, *, args: tuple[Any, ...] = ()
    ) -> npt.NDArray[np.complex128]:
        import pennylane as qml

        tape = self._tape(circuit, args)
        wires = self._wire_list(tape, circuit)
        matrix = qml.matrix(tape, wire_order=wires)
        return np.asarray(matrix, dtype=np.complex128)

    def is_unitary(self, circuit: Any, *, atol: float, args: tuple[Any, ...] = ()) -> bool:
        return max_unitarity_deviation(self.operator_matrix(circuit, args=args)) <= atol

    def equivalent(
        self, circuit_a: Any, circuit_b: Any, *, atol: float, args: tuple[Any, ...] = ()
    ) -> bool:
        a = self.operator_matrix(circuit_a, args=args)
        b = self.operator_matrix(circuit_b, args=args)
        return phase_invariant_allclose(a, b, atol=atol)

    # -- sampling ----------------------------------------------------------

    def counts(self, circuit: Any, *, shots: int, args: tuple[Any, ...] = ()) -> dict[str, int]:
        import pennylane as qml

        tape = self._tape(circuit, args)
        wires = self._wire_list(tape, circuit)
        counts_tape = qml.tape.QuantumTape(
            ops=list(tape.operations),
            measurements=[qml.counts(wires=wires, all_outcomes=False)],
            shots=shots,
        )
        device = qml.device("default.qubit", wires=wires)
        (raw,) = device.execute([counts_tape])
        # PennyLane is already big-endian (wire order = reading order).
        return {str(bitstring): int(count) for bitstring, count in raw.items()}

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _tape(circuit: Any, args: tuple[Any, ...]) -> Any:
        from pennylane.workflow import construct_tape

        tape = construct_tape(circuit)(*args)
        bad = [op.name for op in tape.operations if type(op).__name__ in _NON_UNITARY]
        if bad:
            raise UnsupportedCircuitError(
                f"circuit contains non-unitary operations {bad}; qlens captures "
                "pure statevector evolution (Phase 1 is simulator-first, "
                "gate-based circuits only)"
            )
        return tape

    @staticmethod
    def _wire_list(tape: Any, circuit: Any) -> list[Any]:
        """Wires in sorted order, the deterministic canonical order for
        integer-labeled circuits. Non-integer labels sort by string.

        The union of tape wires and device wires: the tape alone misses
        wires the device declares but no gate touches (an idle qubit is
        still a qubit — its bit must appear in counts and its axis in
        statevectors), and a gateless tape carries no wires at all."""
        device_wires = getattr(circuit.device, "wires", None)
        wires = set(tape.wires) | set(device_wires or [])
        try:
            return sorted(wires)
        except TypeError:
            return sorted(wires, key=str)


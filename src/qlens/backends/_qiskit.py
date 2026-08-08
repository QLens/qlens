"""Qiskit backend.

Statevector capture walks the circuit gate-by-gate with
``qiskit.quantum_info.Statevector.evolve`` — pure qiskit, no Aer.
Counts run through ``qiskit.primitives.StatevectorSampler``.

Qiskit is little-endian (qubit 0 is the rightmost bit of a basis label,
and the least-significant axis of a statevector). Every output crossing
this boundary is converted to Qlens's canonical big-endian convention:
bitstrings are reversed, statevectors are permuted by reversing the
qubit axis order. See CONVENTIONS.md.

The provider package is imported inside methods, never at module level,
so the registry can load this module and call handles() without qiskit
installed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from qlens._errors import UnsupportedCircuitError
from qlens._execution import ExecutionResult, Snapshot
from qlens._stats import max_unitarity_deviation
from qlens.backends.base import Backend

# Instructions that carry no unitary and no state change worth snapshotting.
_SKIPPED = frozenset({"barrier", "delay"})
_NON_UNITARY = frozenset({"measure", "reset", "initialize"})


def _to_big_endian_state(state: npt.NDArray[np.complex128], num_qubits: int) -> npt.NDArray[np.complex128]:
    """Reverse the qubit axis order of a little-endian statevector."""
    if num_qubits < 2:
        return state
    tensor = state.reshape([2] * num_qubits)
    return np.ascontiguousarray(tensor.transpose(*reversed(range(num_qubits)))).reshape(-1)


def _to_big_endian_matrix(matrix: npt.NDArray[np.complex128], num_qubits: int) -> npt.NDArray[np.complex128]:
    """Reverse the qubit axis order on both sides of a little-endian unitary."""
    if num_qubits < 2:
        return matrix
    axes = [2] * (2 * num_qubits)
    tensor = matrix.reshape(axes)
    perm = list(reversed(range(num_qubits))) + [
        num_qubits + i for i in reversed(range(num_qubits))
    ]
    return np.ascontiguousarray(tensor.transpose(perm)).reshape(matrix.shape)


class QiskitBackend(Backend):
    """Backend for qiskit.circuit.QuantumCircuit objects."""

    name = "qiskit"

    @classmethod
    def handles(cls, circuit: object) -> bool:
        return type(circuit).__module__.startswith("qiskit.") and type(
            circuit
        ).__qualname__ == "QuantumCircuit"

    # -- execution ---------------------------------------------------------

    def run(self, circuit: Any, *, args: tuple[Any, ...] = ()) -> ExecutionResult:
        from qiskit.quantum_info import Statevector

        bound = self._bind(circuit, args)
        num_qubits = bound.num_qubits
        state = Statevector.from_label("0" * num_qubits)
        snapshots: list[Snapshot] = []
        position = 0
        for instruction in bound.data:
            op = instruction.operation
            if op.name in _SKIPPED:
                continue
            if op.name in _NON_UNITARY:
                raise UnsupportedCircuitError(
                    f"instruction {op.name!r} at position {position} is non-unitary; "
                    "qlens.run captures pure statevector evolution (Phase 1 is "
                    "simulator-first, gate-based circuits only)"
                )
            qargs = [bound.find_bit(q).index for q in instruction.qubits]
            state = state.evolve(op, qargs=qargs)
            snapshots.append(
                Snapshot(
                    position=position,
                    gate=op.name.lower(),
                    qubits=tuple(qargs),
                    params={
                        f"p{i}": float(p) for i, p in enumerate(op.params)
                    },
                    statevector=_to_big_endian_state(
                        np.asarray(state.data, dtype=np.complex128), num_qubits
                    ),
                )
            )
            position += 1
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
        from qiskit.quantum_info import Operator

        bound = self._bind(circuit, args)
        if any(instr.operation.name in _NON_UNITARY for instr in bound.data):
            raise UnsupportedCircuitError(
                "circuit contains non-unitary instructions (measure/reset); "
                "it has no operator matrix"
            )
        matrix = np.asarray(Operator(bound).data, dtype=np.complex128)
        return _to_big_endian_matrix(matrix, bound.num_qubits)

    def is_unitary(self, circuit: Any, *, atol: float, args: tuple[Any, ...] = ()) -> bool:
        return max_unitarity_deviation(self.operator_matrix(circuit, args=args)) <= atol

    def equivalent(
        self, circuit_a: Any, circuit_b: Any, *, atol: float, args: tuple[Any, ...] = ()
    ) -> bool:
        from qiskit.quantum_info import Operator

        a = self._bind(circuit_a, args)
        b = self._bind(circuit_b, args)
        # Operator.equiv is Qiskit's own up-to-global-phase comparison; no
        # endianness conversion needed since both sides share a convention.
        return bool(Operator(a).equiv(Operator(b), atol=atol))

    # -- sampling ----------------------------------------------------------

    def counts(self, circuit: Any, *, shots: int, args: tuple[Any, ...] = ()) -> dict[str, int]:
        from qiskit import ClassicalRegister
        from qiskit.primitives import StatevectorSampler

        bound = self._bind(circuit, args)
        # Measure every qubit into a fresh register, ignoring any
        # measurements the user's circuit already carries (uniform
        # cross-backend contract: qlens measures all qubits itself).
        measured = bound.remove_final_measurements(inplace=False)
        creg = ClassicalRegister(measured.num_qubits, "qlens")
        measured.add_register(creg)
        measured.measure(range(measured.num_qubits), creg)

        result = StatevectorSampler(default_shots=shots).run([measured]).result()
        raw = result[0].data.qlens.get_counts()
        # Qiskit bitstrings are little-endian; canonical form is big-endian.
        return {bitstring[::-1]: count for bitstring, count in raw.items()}

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _bind(circuit: Any, args: tuple[Any, ...]) -> Any:
        if args:
            return circuit.assign_parameters(list(args))
        if circuit.parameters:
            raise UnsupportedCircuitError(
                f"circuit has {len(circuit.parameters)} unbound parameters; "
                "pass values via args=(...)"
            )
        return circuit

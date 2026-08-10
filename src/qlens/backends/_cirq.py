"""Cirq backend.

Statevector capture applies each operation's unitary onto a running state
tensor through ``cirq.apply_unitary``, which is linear in the number of
gates. Simulating a growing prefix of the circuit once per gate would give
the same snapshots at quadratic cost, and a 200-gate run is a normal size
here.

Cirq's conventions already match Qlens's canonical form: the first qubit
in the order is the most significant bit of a basis index, so wire 0 is
leftmost in a bitstring, and no reordering happens at this boundary. See
CONVENTIONS.md.

Qubit count follows Cirq's own model rather than a declared register: a
circuit has exactly the qubits its operations touch. ``cirq.LineQubit(0)``
and ``cirq.LineQubit(5)`` make a two-qubit circuit in Cirq, and Qlens
reports two qubits for it. A qubit that should occupy an axis without
being acted on needs an explicit ``cirq.I``, which is Cirq's own idiom for
saying so.

Gate parameters record what the gate actually carries. Rotation gates
report their angle in radians, matching the other backends; any other
gate with an exponent away from 1 reports that exponent, since in Cirq
that is where a partial gate keeps its magnitude.

The provider package is imported inside methods, never at module level,
so the registry can load this module and call handles() without cirq
installed.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import numpy.typing as npt

from qlens._errors import UnsupportedCircuitError
from qlens._execution import ExecutionResult, Snapshot
from qlens._gates import FIXED_EXPONENT, normalize
from qlens._stats import max_unitarity_deviation, phase_invariant_allclose
from qlens.backends.base import Backend

_MEASUREMENT_KEY = "qlens"


class CirqBackend(Backend):
    """Backend for cirq.Circuit and cirq.FrozenCircuit objects."""

    name = "cirq"

    @classmethod
    def handles(cls, circuit: object) -> bool:
        return type(circuit).__module__.startswith("cirq.") and type(
            circuit
        ).__qualname__ in {"Circuit", "FrozenCircuit"}

    # -- execution ---------------------------------------------------------

    def run(self, circuit: Any, *, args: tuple[Any, ...] = ()) -> ExecutionResult:
        import cirq

        bound = self._bind(circuit, args)
        qubits = self._qubit_list(bound)
        num_qubits = len(qubits)
        axis_of = {qubit: axis for axis, qubit in enumerate(qubits)}

        state = np.zeros((2,) * num_qubits, dtype=np.complex128)
        state[(0,) * num_qubits] = 1.0
        buffer = np.empty_like(state)

        snapshots: list[Snapshot] = []
        for position, operation in enumerate(bound.all_operations()):
            if not cirq.has_unitary(operation):
                raise UnsupportedCircuitError(
                    f"operation {operation!r} at position {position} is non-unitary; "
                    "qlens.run captures pure statevector evolution (simulator-first, "
                    "gate-based circuits only)"
                )
            axes = tuple(axis_of[qubit] for qubit in operation.qubits)
            applied = cirq.apply_unitary(
                operation,
                cirq.ApplyUnitaryArgs(
                    target_tensor=state, available_buffer=buffer, axes=axes
                ),
            )
            # apply_unitary is free to write into either array it was
            # handed; whichever came back is the state, and the other is
            # scratch for the next gate.
            if applied is buffer:
                state, buffer = buffer, state
            elif applied is not state:
                state = np.asarray(applied, dtype=np.complex128)
                buffer = np.empty_like(state)
            native = _native_name(operation.gate)
            snapshots.append(
                Snapshot(
                    position=position,
                    gate=normalize(native),
                    native_gate=native,
                    qubits=tuple(axes),
                    params=_gate_params(operation.gate, normalize(native)),
                    statevector=state.reshape(-1).copy(),
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
            _counts_fn=lambda shots, seed: self.counts(circuit, shots=shots, seed=seed, args=args),
        )

    # -- structural checks -------------------------------------------------

    def operator_matrix(
        self, circuit: Any, *, args: tuple[Any, ...] = ()
    ) -> npt.NDArray[np.complex128]:
        import cirq

        bound = self._bind(circuit, args)
        qubits = self._qubit_list(bound)
        # Checked per operation rather than through cirq.has_unitary on the
        # circuit, which accepts a trailing measurement and quietly drops
        # it. A circuit that measures has no operator matrix here, the same
        # answer the other backends give.
        if any(not cirq.has_unitary(operation) for operation in bound.all_operations()):
            raise UnsupportedCircuitError(
                "circuit contains non-unitary operations (measurement, reset, or "
                "classical control); it has no operator matrix"
            )
        matrix = bound.unitary(
            qubit_order=qubits, ignore_terminal_measurements=False
        )
        return np.asarray(matrix, dtype=np.complex128)

    def is_unitary(self, circuit: Any, *, atol: float, args: tuple[Any, ...] = ()) -> bool:
        return max_unitarity_deviation(self.operator_matrix(circuit, args=args)) <= atol

    def equivalent(
        self, circuit_a: Any, circuit_b: Any, *, atol: float, args: tuple[Any, ...] = ()
    ) -> bool:
        a = self.operator_matrix(circuit_a, args=args)
        b = self.operator_matrix(circuit_b, args=args)
        # Circuits over different qubit counts act on different spaces, so
        # they are not the same operator whatever the entries say.
        if a.shape != b.shape:
            return False
        return phase_invariant_allclose(a, b, atol=atol)

    # -- sampling ----------------------------------------------------------

    def counts(
        self,
        circuit: Any,
        *,
        shots: int,
        seed: int | None = None,
        args: tuple[Any, ...] = (),
    ) -> dict[str, int]:
        import cirq

        bound = self._bind(circuit, args)
        qubits = self._qubit_list(bound)
        # Measure every qubit into one fresh key, ignoring any measurement
        # the user's circuit already carries (uniform cross-backend
        # contract: qlens measures all qubits itself).
        sampled = cirq.Circuit(
            operation
            for operation in bound.all_operations()
            if not cirq.is_measurement(operation)
        )
        sampled.append(cirq.measure(*qubits, key=_MEASUREMENT_KEY))

        result = cirq.Simulator(seed=seed).run(sampled, repetitions=shots)
        width = len(qubits)
        # Cirq's histogram keys are the measured qubits read as one integer,
        # first qubit most significant — already the canonical big-endian
        # bitstring once formatted.
        return {
            format(int(value), f"0{width}b"): int(count)
            for value, count in result.histogram(key=_MEASUREMENT_KEY).items()
        }

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _bind(circuit: Any, args: tuple[Any, ...]) -> Any:
        import cirq

        names = sorted(cirq.parameter_names(circuit))
        if args:
            if len(args) != len(names):
                raise UnsupportedCircuitError(
                    f"circuit has {len(names)} free parameters {names}, "
                    f"but {len(args)} values were passed via args=(...)"
                )
            # Sorted by symbol name: positional binding needs an order the
            # caller can predict, and a set has none.
            return cirq.resolve_parameters(circuit, dict(zip(names, args, strict=True)))
        if names:
            raise UnsupportedCircuitError(
                f"circuit has {len(names)} unbound parameters {names}; "
                "pass values via args=(...) in sorted symbol-name order"
            )
        return circuit

    @staticmethod
    def _qubit_list(circuit: Any) -> list[Any]:
        """The circuit's qubits in Cirq's own default order.

        Sorting is what ``cirq.unitary`` and ``cirq.final_state_vector``
        use when given no explicit order, so following it keeps the axis
        order Qlens reports identical to the one Cirq itself would.
        """
        return sorted(circuit.all_qubits())


def _native_name(gate: Any) -> str:
    """Cirq's own name for a gate, without its parameters.

    ``str(gate)`` is Cirq's display form, which for a rotation carries the
    angle ("Rx(0.095π)"). The angle already travels in params, and a name
    repeating it would make every rotation a different gate.
    """
    if gate is None:
        return "unknown"
    label = str(gate)
    head, _, _ = label.partition("(")
    return (head or label).strip().lower()


def _gate_params(gate: Any, canonical: str) -> dict[str, float]:
    """Numeric parameters, in the same form the other backends report.

    Rotations give their angle in radians. Any other partial gate gives
    its exponent, which is where Cirq keeps a gate's magnitude — except
    where the canonical name already fixes it, since an S gate reporting
    p0=0.5 would carry a parameter its siblings on Qiskit and PennyLane
    do not.
    """
    import cirq

    if isinstance(gate, cirq.Rx | cirq.Ry | cirq.Rz):
        return {"p0": float(gate.exponent) * math.pi}
    if canonical in FIXED_EXPONENT:
        return {}
    exponent = getattr(gate, "exponent", None)
    if exponent is None or not isinstance(exponent, int | float) or exponent == 1:
        return {}
    return {"p0": float(exponent)}

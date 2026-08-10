"""Cirq backend behaviour beyond conformance.

Conformance proves the numbers agree with the reference simulator. What it
does not cover is what happens off the happy path: a measurement in the
middle of a circuit, a free parameter with no value, a circuit whose
qubits are not contiguous, and the places where Cirq's model differs from
the register-based frameworks.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import qlens
from qlens._errors import UnsupportedCircuitError
from qlens.backends import get_backend
from qlens.backends._cirq import CirqBackend

cirq = pytest.importorskip("cirq")


@pytest.fixture()
def backend() -> CirqBackend:
    resolved = get_backend("cirq")
    assert isinstance(resolved, CirqBackend)
    return resolved


def bell() -> object:
    q = cirq.LineQubit.range(2)
    return cirq.Circuit([cirq.H(q[0]), cirq.CNOT(q[0], q[1])])


# -- refusals -------------------------------------------------------------


def test_a_measurement_mid_circuit_is_refused_by_name(backend: CirqBackend) -> None:
    q = cirq.LineQubit.range(2)
    circuit = cirq.Circuit(
        [cirq.H(q[0]), cirq.measure(q[0], key="m"), cirq.X(q[1])],
        strategy=cirq.InsertStrategy.NEW,
    )
    with pytest.raises(UnsupportedCircuitError) as excinfo:
        backend.run(circuit)
    assert "non-unitary" in str(excinfo.value)
    assert "position 1" in str(excinfo.value), "the error should say which gate stopped it"


def test_reported_position_follows_moments_not_the_order_written(
    backend: CirqBackend,
) -> None:
    """Cirq packs operations on disjoint qubits into one moment, and a
    moment's contents run together. Positions follow that, so the X below
    is position 1 despite being written third."""
    q = cirq.LineQubit.range(2)
    circuit = cirq.Circuit([cirq.H(q[0]), cirq.measure(q[0], key="m"), cirq.X(q[1])])
    with pytest.raises(UnsupportedCircuitError) as excinfo:
        backend.run(circuit)
    assert "position 2" in str(excinfo.value)


def test_a_measured_circuit_has_no_operator_matrix(backend: CirqBackend) -> None:
    q = cirq.LineQubit.range(1)
    circuit = cirq.Circuit([cirq.H(q[0]), cirq.measure(q[0], key="m")])
    with pytest.raises(UnsupportedCircuitError):
        backend.operator_matrix(circuit)


def test_an_unbound_parameter_names_itself(backend: CirqBackend) -> None:
    import sympy

    q = cirq.LineQubit.range(1)
    circuit = cirq.Circuit([cirq.rx(sympy.Symbol("theta")).on(q[0])])
    with pytest.raises(UnsupportedCircuitError) as excinfo:
        backend.run(circuit)
    assert "theta" in str(excinfo.value)


def test_the_wrong_number_of_parameter_values_is_refused(backend: CirqBackend) -> None:
    import sympy

    q = cirq.LineQubit.range(1)
    circuit = cirq.Circuit(
        [cirq.rx(sympy.Symbol("a")).on(q[0]), cirq.ry(sympy.Symbol("b")).on(q[0])]
    )
    with pytest.raises(UnsupportedCircuitError) as excinfo:
        backend.run(circuit, args=(0.5,))
    assert "2 free parameters" in str(excinfo.value)


def test_handles_says_no_without_raising(backend: CirqBackend) -> None:
    for other in (None, 42, "circuit", object(), [cirq.X]):
        assert CirqBackend.handles(other) is False


def test_handles_recognises_both_circuit_types() -> None:
    assert CirqBackend.handles(bell()) is True
    assert CirqBackend.handles(bell().freeze()) is True  # type: ignore[attr-defined]


# -- capture --------------------------------------------------------------


def test_one_snapshot_per_gate_in_execution_order(backend: CirqBackend) -> None:
    q = cirq.LineQubit.range(2)
    circuit = cirq.Circuit(
        [cirq.H(q[0]), cirq.X(q[1]), cirq.CNOT(q[0], q[1])],
        strategy=cirq.InsertStrategy.NEW,
    )
    result = backend.run(circuit)
    assert [s.position for s in result.snapshots] == [0, 1, 2]
    assert [s.gate for s in result.snapshots] == ["h", "x", "cx"]
    assert [s.native_gate for s in result.snapshots] == ["h", "x", "cnot"]


def test_each_snapshot_is_the_state_at_that_point(backend: CirqBackend) -> None:
    result = backend.run(bell())
    after_h = result.snapshots[0].statevector
    assert np.allclose(after_h, [1 / math.sqrt(2), 0, 1 / math.sqrt(2), 0])
    assert np.allclose(
        result.final_statevector, [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)]
    )


def test_snapshots_do_not_alias_one_running_buffer(backend: CirqBackend) -> None:
    """Applying gates in place is the whole point of the capture loop, so
    a snapshot that kept a view rather than a copy would report the final
    state at every position."""
    q = cirq.LineQubit.range(1)
    result = backend.run(cirq.Circuit([cirq.H(q[0]), cirq.Z(q[0]), cirq.H(q[0])]))
    states = [s.statevector for s in result.snapshots]
    assert not np.allclose(states[0], states[2])


def test_qubit_zero_is_leftmost_in_the_captured_state(backend: CirqBackend) -> None:
    q = cirq.LineQubit.range(2)
    result = backend.run(cirq.Circuit([cirq.X(q[0]), cirq.I(q[1])]))
    # |10> is basis index 2 when qubit 0 is the most significant bit.
    assert np.argmax(np.abs(result.final_statevector)) == 2


def test_a_gate_records_the_axes_it_acted_on(backend: CirqBackend) -> None:
    q = cirq.LineQubit.range(3)
    result = backend.run(cirq.Circuit([cirq.CNOT(q[2], q[0]), cirq.I(q[1])]))
    assert result.snapshots[0].qubits == (2, 0)


def test_a_circuit_with_no_gates_still_reports_a_state(backend: CirqBackend) -> None:
    result = backend.run(cirq.Circuit())
    assert result.num_qubits == 0
    assert len(result.snapshots) == 1
    assert result.snapshots[0].gate == "initial"


# -- Cirq's own qubit model ----------------------------------------------


def test_qubit_count_follows_the_operations_not_the_labels(backend: CirqBackend) -> None:
    """Cirq has no register: a circuit on LineQubit 0 and 5 is a two-qubit
    circuit, and reporting six would invent four axes the framework itself
    does not simulate."""
    circuit = cirq.Circuit([cirq.H(cirq.LineQubit(0)), cirq.X(cirq.LineQubit(5))])
    result = backend.run(circuit)
    assert result.num_qubits == 2
    assert result.final_statevector.shape == (4,)


def test_axes_follow_sorted_qubit_order(backend: CirqBackend) -> None:
    # Recorded in reverse; the lower-labelled qubit still takes axis 0.
    circuit = cirq.Circuit([cirq.X(cirq.LineQubit(5)), cirq.H(cirq.LineQubit(0))])
    result = backend.run(circuit)
    assert result.snapshots[0].qubits == (1,)
    assert result.snapshots[1].qubits == (0,)


def test_an_idle_qubit_takes_an_axis_when_declared_with_identity(
    backend: CirqBackend,
) -> None:
    q = cirq.LineQubit.range(2)
    result = backend.run(cirq.Circuit([cirq.I(q[1]), cirq.X(q[0])]))
    assert result.num_qubits == 2


# -- gate labels and parameters ------------------------------------------


def test_a_rotation_label_carries_no_angle(backend: CirqBackend) -> None:
    """Cirq's own display name for a rotation includes the angle, which
    would make every rotation a different gate in the viewer."""
    q = cirq.LineQubit.range(1)
    result = backend.run(cirq.Circuit([cirq.rx(0.3).on(q[0])]))
    assert result.snapshots[0].gate == "rx"


def test_a_rotation_records_its_angle_in_radians(backend: CirqBackend) -> None:
    q = cirq.LineQubit.range(1)
    result = backend.run(cirq.Circuit([cirq.ry(0.75).on(q[0])]))
    assert result.snapshots[0].params["p0"] == pytest.approx(0.75)


def test_a_plain_gate_records_no_parameters(backend: CirqBackend) -> None:
    q = cirq.LineQubit.range(2)
    result = backend.run(cirq.Circuit([cirq.H(q[0]), cirq.CNOT(q[0], q[1])]))
    assert result.snapshots[0].params == {}
    assert result.snapshots[1].params == {}


def test_a_named_root_gate_reports_no_exponent(backend: CirqBackend) -> None:
    """Cirq models √X as X**0.5 and carries the exponent on it, but the
    canonical name `sx` already fixes it, and Qiskit's own `sx` reports no
    parameters."""
    q = cirq.LineQubit.range(1)
    result = backend.run(cirq.Circuit([cirq.X(q[0]) ** 0.5]))
    assert result.snapshots[0].gate == "sx"
    assert result.snapshots[0].params == {}


def test_an_unnamed_partial_gate_records_its_exponent(backend: CirqBackend) -> None:
    """A power with no canonical name has nowhere else to keep its
    magnitude, so dropping the exponent would lose what the gate does."""
    q = cirq.LineQubit.range(1)
    result = backend.run(cirq.Circuit([cirq.X(q[0]) ** 0.3]))
    assert result.snapshots[0].params["p0"] == pytest.approx(0.3)


# -- parameters -----------------------------------------------------------


def test_parameters_bind_in_sorted_symbol_order(backend: CirqBackend) -> None:
    import sympy

    q = cirq.LineQubit.range(1)
    circuit = cirq.Circuit(
        [cirq.rx(sympy.Symbol("beta")).on(q[0]), cirq.ry(sympy.Symbol("alpha")).on(q[0])]
    )
    # alpha sorts first, so 0.25 binds to the ry and 0.5 to the rx.
    result = backend.run(circuit, args=(0.25, 0.5))
    by_gate = {s.gate: s.params["p0"] for s in result.snapshots}
    assert by_gate["ry"] == pytest.approx(0.25)
    assert by_gate["rx"] == pytest.approx(0.5)


# -- sampling -------------------------------------------------------------


def test_counts_are_big_endian_bitstrings(backend: CirqBackend) -> None:
    q = cirq.LineQubit.range(2)
    counts = backend.counts(cirq.Circuit([cirq.X(q[0]), cirq.I(q[1])]), shots=64, seed=0)
    assert counts == {"10": 64}


def test_counts_sum_to_shots(backend: CirqBackend) -> None:
    counts = backend.counts(bell(), shots=500, seed=3)
    assert sum(counts.values()) == 500
    assert set(counts) <= {"00", "11"}


def test_the_same_seed_gives_the_same_counts(backend: CirqBackend) -> None:
    first = backend.counts(bell(), shots=256, seed=11)
    second = backend.counts(bell(), shots=256, seed=11)
    assert first == second


def test_a_measurement_the_user_wrote_is_ignored(backend: CirqBackend) -> None:
    """Qlens measures every qubit itself, so a circuit that already
    measures one qubit still reports both."""
    q = cirq.LineQubit.range(2)
    circuit = cirq.Circuit(
        [cirq.X(q[0]), cirq.I(q[1]), cirq.measure(q[0], key="theirs")]
    )
    counts = backend.counts(circuit, shots=32, seed=0)
    assert counts == {"10": 32}


# -- equivalence ----------------------------------------------------------


def test_circuits_over_different_qubit_counts_are_not_equivalent(
    backend: CirqBackend,
) -> None:
    q = cirq.LineQubit.range(2)
    one = cirq.Circuit([cirq.X(q[0])])
    two = cirq.Circuit([cirq.X(q[0]), cirq.I(q[1])])
    assert backend.equivalent(one, two, atol=1e-8) is False


def test_global_phase_does_not_break_equivalence(backend: CirqBackend) -> None:
    q = cirq.LineQubit.range(1)
    plain = cirq.Circuit([cirq.X(q[0])])
    phased = cirq.Circuit([cirq.X(q[0]), cirq.global_phase_operation(1j)])
    assert backend.equivalent(plain, phased, atol=1e-8) is True


# -- through the public API ----------------------------------------------


def test_a_cirq_circuit_routes_to_this_backend() -> None:
    result = qlens.run(bell())
    assert result.backend == "cirq"


def test_the_documented_assertions_work_on_a_cirq_circuit() -> None:
    result = qlens.run(bell())
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=0)
    qlens.assert_unitary(bell())

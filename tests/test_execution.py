"""qlens.run: snapshot capture, canonical state ordering, lazy counts."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from conftest import bell_program

import qlens


def test_bell_snapshots_positions_and_gates(build: Any) -> None:
    result = qlens.run(build(bell_program(), 2))
    assert [s.position for s in result.snapshots] == [0, 1]
    assert result.snapshots[0].qubits == (0,)
    assert result.snapshots[1].qubits == (0, 1)


def test_bell_intermediate_state_is_big_endian(build: Any) -> None:
    # After H on qubit 0: |+0> = (|00> + |10>)/sqrt(2). Big-endian means
    # the amplitude sits on indices 0 and 2 — index 1 (|01>) would mean
    # little-endian leaked through.
    result = qlens.run(build(bell_program(), 2))
    after_h = result.statevector_at(0)
    expected = np.array([1, 0, 1, 0], dtype=np.complex128) / np.sqrt(2)
    assert np.allclose(after_h, expected)


def test_bell_final_state(build: Any) -> None:
    result = qlens.run(build(bell_program(), 2))
    expected = np.array([1, 0, 0, 1], dtype=np.complex128) / np.sqrt(2)
    assert np.allclose(result.final_statevector, expected)


def test_empty_circuit_yields_initial_state(build: Any) -> None:
    result = qlens.run(build((), 1))
    assert len(result.snapshots) == 1
    assert np.allclose(result.final_statevector, [1, 0])


def test_counts_sum_and_caching(build: Any) -> None:
    result = qlens.run(build(bell_program(), 2))
    counts = result.counts(256)
    assert sum(counts.values()) == 256
    # Same shots -> cached object, not a re-sample.
    assert result.counts(256) is counts


def test_counts_keys_are_big_endian(build: Any) -> None:
    # X on qubit 0 of two qubits: outcome must be "10" (qubit 0 leftmost),
    # never "01".
    result = qlens.run(build((("x", (0,), ()),), 2))
    assert result.counts(128) == {"10": 128}


def test_parameterized_circuit_requires_args_qiskit() -> None:
    qiskit = pytest.importorskip("qiskit")
    from qiskit.circuit import Parameter

    circuit = qiskit.QuantumCircuit(1)
    circuit.rx(Parameter("theta"), 0)
    with pytest.raises(qlens.UnsupportedCircuitError, match="unbound parameters"):
        qlens.run(circuit)
    result = qlens.run(circuit, args=(0.7,))
    assert len(result.snapshots) == 1


def test_parameterized_qnode_args_pennylane() -> None:
    qml = pytest.importorskip("pennylane")

    @qml.qnode(qml.device("default.qubit", wires=1))
    def circuit(theta: float) -> Any:
        qml.RX(theta, wires=0)
        return qml.state()

    result = qlens.run(circuit, args=(0.7,))
    assert result.snapshots[0].params == {"p0": 0.7}


def test_measure_rejected_qiskit() -> None:
    qiskit = pytest.importorskip("qiskit")

    circuit = qiskit.QuantumCircuit(1, 1)
    circuit.h(0)
    circuit.measure(0, 0)
    with pytest.raises(qlens.UnsupportedCircuitError, match="non-unitary"):
        qlens.run(circuit)


def test_run_with_explicit_backend_name(build: Any, backend_name: str) -> None:
    result = qlens.run(build(bell_program(), 2), backend=backend_name)
    assert result.backend == backend_name


def test_cross_backend_states_identical() -> None:
    pytest.importorskip("qiskit")
    pytest.importorskip("pennylane")
    from qlens.conformance._builders import BUILDERS

    program = bell_program()
    result_q = qlens.run(BUILDERS["qiskit"](program, 2))
    result_p = qlens.run(BUILDERS["pennylane"](program, 2))
    for snap_q, snap_p in zip(result_q.snapshots, result_p.snapshots):
        assert np.allclose(snap_q.statevector, snap_p.statevector)

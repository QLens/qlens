"""Structural measurement capture across the three backends.

A measurement is recorded where it appears and on which qubits, without
collapsing the state: the gate snapshots stay pure unitary evolution, so a
circuit that measures mid-way still ends on the same statevector as one that
doesn't. Circuits that measure have no operator matrix.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

import qlens
from qlens import QlensError


def _bell_state() -> np.ndarray:
    return np.array([1, 0, 0, 1], dtype=np.complex128) / np.sqrt(2)


# --- Qiskit ------------------------------------------------------------


def test_qiskit_mid_circuit_measurement_is_captured() -> None:
    qiskit = pytest.importorskip("qiskit")
    qc = qiskit.QuantumCircuit(2, 1)
    qc.h(0)
    qc.measure(0, 0)
    qc.cx(0, 1)

    result = qlens.run(qc)
    # Two gates snapshotted, contiguous; the measure is not a gate.
    assert [s.gate for s in result.snapshots] == ["h", "cx"]
    assert [s.position for s in result.snapshots] == [0, 1]
    # One measurement, after the first gate, on qubit 0.
    assert result.measurements == [qlens.Measurement(after=1, qubits=(0,))]
    # No collapse: the state runs on to the Bell state.
    np.testing.assert_allclose(result.final_statevector, _bell_state(), atol=1e-9)


def test_qiskit_no_measurement_is_an_empty_list() -> None:
    qiskit = pytest.importorskip("qiskit")
    qc = qiskit.QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    assert qlens.run(qc).measurements == []


def test_qiskit_measuring_circuit_has_no_operator_matrix() -> None:
    qiskit = pytest.importorskip("qiskit")
    qc = qiskit.QuantumCircuit(1, 1)
    qc.h(0)
    qc.measure(0, 0)
    with pytest.raises(QlensError):
        qlens.assert_unitary(qc)


def test_qiskit_reset_is_still_refused() -> None:
    qiskit = pytest.importorskip("qiskit")
    qc = qiskit.QuantumCircuit(1)
    qc.h(0)
    qc.reset(0)
    with pytest.raises(QlensError):
        qlens.run(qc)


# --- Cirq --------------------------------------------------------------


def test_cirq_measurement_is_captured() -> None:
    cirq = pytest.importorskip("cirq")
    q = cirq.LineQubit.range(2)
    circuit = cirq.Circuit([cirq.H(q[0]), cirq.measure(q[0]), cirq.CNOT(q[0], q[1])])

    result = qlens.run(circuit)
    assert [s.gate for s in result.snapshots] == ["h", "cx"]
    assert result.measurements == [qlens.Measurement(after=1, qubits=(0,))]
    np.testing.assert_allclose(result.final_statevector, _bell_state(), atol=1e-9)


def test_cirq_measuring_circuit_has_no_operator_matrix() -> None:
    cirq = pytest.importorskip("cirq")
    q = cirq.LineQubit.range(1)
    circuit = cirq.Circuit([cirq.H(q[0]), cirq.measure(q[0])])
    with pytest.raises(QlensError):
        qlens.assert_unitary(circuit)


# --- PennyLane ---------------------------------------------------------


def test_pennylane_mid_circuit_measurement_is_captured() -> None:
    qml = pytest.importorskip("pennylane")
    dev = qml.device("default.qubit", wires=2)

    @qml.qnode(dev)
    def circuit() -> Any:  # type: ignore[valid-type]
        qml.Hadamard(0)
        qml.measure(0)
        qml.CNOT([0, 1])
        return qml.state()

    result = qlens.run(circuit)
    assert [s.gate for s in result.snapshots] == ["h", "cx"]
    assert result.measurements == [qlens.Measurement(after=1, qubits=(0,))]
    np.testing.assert_allclose(result.final_statevector, _bell_state(), atol=1e-9)


def test_pennylane_no_measurement_is_an_empty_list() -> None:
    qml = pytest.importorskip("pennylane")
    dev = qml.device("default.qubit", wires=2)

    @qml.qnode(dev)
    def circuit() -> Any:  # type: ignore[valid-type]
        qml.Hadamard(0)
        qml.CNOT([0, 1])
        return qml.state()

    assert qlens.run(circuit).measurements == []


# --- ordering: an operation after a measurement -----------------------


def test_after_index_orders_gates_against_measurements() -> None:
    qiskit = pytest.importorskip("qiskit")
    qc = qiskit.QuantumCircuit(2, 1)
    qc.h(0)
    qc.measure(0, 0)  # after 1 gate
    qc.cx(0, 1)  # gate at position 1, on qubit 0

    result = qlens.run(qc)
    measurement = result.measurements[0]
    # A gate follows the measurement on a measured qubit: position >= after
    # and a shared qubit. This is the substrate a lint rule reads.
    followers = [
        s
        for s in result.snapshots
        if s.position >= measurement.after and set(s.qubits) & set(measurement.qubits)
    ]
    assert [s.gate for s in followers] == ["cx"]

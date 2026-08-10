"""First-party interpreters from the neutral gate vocabulary to real
framework circuits. A third-party backend author writes the equivalent of
one of these functions for their framework and passes it to
run_conformance.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qlens.conformance._circuits import Program


def build_qiskit(program: Program, num_qubits: int) -> Any:
    from qiskit import QuantumCircuit

    circuit = QuantumCircuit(num_qubits)
    dispatch = {
        "i": circuit.id,
        "x": circuit.x,
        "y": circuit.y,
        "z": circuit.z,
        "h": circuit.h,
        "s": circuit.s,
        "t": circuit.t,
        "cx": circuit.cx,
        "cz": circuit.cz,
        "swap": circuit.swap,
        "ccx": circuit.ccx,
        "rx": circuit.rx,
        "ry": circuit.ry,
        "rz": circuit.rz,
    }
    for gate, qubits, params in program:
        dispatch[gate](*params, *qubits)
    return circuit


def build_pennylane(program: Program, num_qubits: int) -> Any:
    import pennylane as qml

    gate_classes = {
        "i": qml.Identity,
        "x": qml.PauliX,
        "y": qml.PauliY,
        "z": qml.PauliZ,
        "h": qml.Hadamard,
        "s": qml.S,
        "t": qml.T,
        "cx": qml.CNOT,
        "cz": qml.CZ,
        "swap": qml.SWAP,
        "ccx": qml.Toffoli,
        "rx": qml.RX,
        "ry": qml.RY,
        "rz": qml.RZ,
    }
    device = qml.device("default.qubit", wires=num_qubits)

    def circuit() -> Any:
        for gate, qubits, params in program:
            cls = gate_classes[gate]
            if params:
                cls(*params, wires=list(qubits))
            elif len(qubits) == 1:
                cls(wires=qubits[0])
            else:
                cls(wires=list(qubits))
        return qml.state()

    # Applied as a call, not a decorator: pennylane is untyped, and an
    # untyped decorator would erase this function's type under strict mypy.
    return qml.QNode(circuit, device)


def build_cirq(program: Program, num_qubits: int) -> Any:
    import cirq

    qubits = cirq.LineQubit.range(num_qubits)
    # Cirq's fixed gates are singletons and its rotations are factories, so
    # both arrive here as callables taking the program's parameters.
    gate_factories: dict[str, Callable[..., Any]] = {
        "i": lambda: cirq.I,
        "x": lambda: cirq.X,
        "y": lambda: cirq.Y,
        "z": lambda: cirq.Z,
        "h": lambda: cirq.H,
        "s": lambda: cirq.S,
        "t": lambda: cirq.T,
        "cx": lambda: cirq.CNOT,
        "cz": lambda: cirq.CZ,
        "swap": lambda: cirq.SWAP,
        "ccx": lambda: cirq.TOFFOLI,
        "rx": cirq.rx,
        "ry": cirq.ry,
        "rz": cirq.rz,
    }
    operations = [
        gate_factories[gate](*params).on(*(qubits[q] for q in qubit_indices))
        for gate, qubit_indices, params in program
    ]
    # One gate per moment. Cirq would otherwise pack gates on disjoint
    # qubits into a shared moment, and snapshots follow moment order, so
    # packing would reorder the program's positions.
    return cirq.Circuit(operations, strategy=cirq.InsertStrategy.NEW)


BUILDERS = {
    "qiskit": build_qiskit,
    "pennylane": build_pennylane,
    "cirq": build_cirq,
}

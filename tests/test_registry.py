"""Backend discovery, dispatch, and detection failure modes."""

from __future__ import annotations

import pytest

import qlens
from qlens.backends import available_backends, detect_backend, get_backend


def test_first_party_backends_registered() -> None:
    names = available_backends()
    assert "qiskit" in names
    assert "pennylane" in names


def test_unknown_backend_name() -> None:
    with pytest.raises(qlens.BackendNotFoundError, match="no backend named"):
        get_backend("cirq")


def test_detect_rejects_foreign_object() -> None:
    with pytest.raises(qlens.BackendNotFoundError, match="no installed backend"):
        detect_backend(object())


def test_detect_rejects_none() -> None:
    with pytest.raises(qlens.BackendNotFoundError):
        detect_backend(None)


def test_handles_is_probe_safe_without_provider_import() -> None:
    # handles() must inspect module names, never isinstance against
    # provider types, so it can answer for arbitrary objects for free.
    from qlens.backends._pennylane import PennyLaneBackend
    from qlens.backends._qiskit import QiskitBackend

    class FakeQuantumCircuit:
        pass

    fake = FakeQuantumCircuit()
    assert QiskitBackend.handles(fake) is False
    assert PennyLaneBackend.handles(fake) is False
    assert QiskitBackend.handles("a string") is False


def test_detect_qiskit() -> None:
    qiskit = pytest.importorskip("qiskit")
    assert detect_backend(qiskit.QuantumCircuit(1)).name == "qiskit"


def test_detect_pennylane() -> None:
    qml = pytest.importorskip("pennylane")

    @qml.qnode(qml.device("default.qubit", wires=1))
    def circuit():  # type: ignore[no-untyped-def]
        return qml.state()

    assert detect_backend(circuit).name == "pennylane"


def test_backend_instances_are_cached() -> None:
    assert get_backend("qiskit") is get_backend("qiskit")

"""Shared fixtures: paired circuit builders across both backends.

Tests parametrize over backend names and build circuits through the
conformance builders, so every test body runs identically against
Qiskit and PennyLane.
"""

from __future__ import annotations

from typing import Any

import pytest

from qlens.conformance._builders import BUILDERS
from qlens.conformance._circuits import Program

pytest_plugins = ["pytester"]

BACKEND_NAMES = ["qiskit", "pennylane"]


@pytest.fixture(params=BACKEND_NAMES)
def backend_name(request: Any) -> str:
    return str(request.param)


@pytest.fixture
def build(backend_name: str) -> Any:
    """Interpreter from neutral gate programs to this backend's circuits."""
    return lambda program, num_qubits: BUILDERS[backend_name](program, num_qubits)


def bell_program() -> Program:
    return (("h", (0,), ()), ("cx", (0, 1), ()))

"""Qlens: a testing, debugging, and observability SDK for quantum
programs, simulator-first.

Public API:
    run                 -- instrumented execution with per-gate snapshots
    assert_unitary      -- circuit operation is unitary within tolerance
    assert_equivalent   -- two circuits share one unitary up to global phase
    assert_distribution -- sampled output matches an expected distribution
"""

from typing import Any

from qlens._assertions import assert_distribution, assert_equivalent, assert_unitary
from qlens._errors import (
    BackendNotFoundError,
    BackendNotInstalledError,
    QlensAssertionError,
    QlensError,
    UnsupportedCircuitError,
)
from qlens._execution import ExecutionResult, Snapshot
from qlens._inspect import Inspector, StateDiff, inspect
from qlens.backends import Backend, available_backends, detect_backend, get_backend

__version__ = "0.2.0"

__all__ = [
    "Backend",
    "BackendNotFoundError",
    "BackendNotInstalledError",
    "ExecutionResult",
    "Inspector",
    "QlensAssertionError",
    "QlensError",
    "Snapshot",
    "StateDiff",
    "UnsupportedCircuitError",
    "__version__",
    "assert_distribution",
    "assert_equivalent",
    "assert_unitary",
    "available_backends",
    "detect_backend",
    "get_backend",
    "inspect",
    "run",
]


def run(
    circuit: Any,
    *,
    backend: str | None = None,
    args: tuple[Any, ...] = (),
) -> ExecutionResult:
    """Execute a circuit with per-gate statevector capture.

    ``backend`` names a registered backend explicitly; when omitted, the
    backend is detected from the circuit object's type. ``args`` binds
    parameter values for parameterized circuits.
    """
    resolved = get_backend(backend) if backend is not None else detect_backend(circuit)
    return resolved.run(circuit, args=args)

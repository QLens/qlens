"""Qlens: a testing, debugging, and observability SDK for quantum
programs, simulator-first.

Public API:
    run                 -- instrumented execution with per-gate snapshots
    assert_unitary      -- circuit operation is unitary within tolerance
    assert_equivalent   -- two circuits share one unitary up to global phase
    assert_distribution -- sampled output matches an expected distribution
"""

from typing import Any

from qlens._assertions import (
    assert_distribution,
    assert_entangled,
    assert_equivalent,
    assert_separable,
    assert_state,
    assert_unitary,
)
from qlens._config import configure, settings
from qlens._errors import (
    BackendNotFoundError,
    BackendNotInstalledError,
    QlensAssertionError,
    QlensError,
    UnsupportedCircuitError,
)
from qlens._execution import ExecutionResult, Snapshot
from qlens._inspect import Inspector, StateDiff, inspect
from qlens._reliability import QlensStatisticsWarning
from qlens.backends import Backend, available_backends, detect_backend, get_backend

__version__ = "0.6.0"

__all__ = [
    "Backend",
    "BackendNotFoundError",
    "BackendNotInstalledError",
    "ExecutionResult",
    "Inspector",
    "QlensAssertionError",
    "QlensError",
    "QlensStatisticsWarning",
    "Snapshot",
    "StateDiff",
    "UnsupportedCircuitError",
    "__version__",
    "assert_distribution",
    "assert_entangled",
    "assert_equivalent",
    "assert_separable",
    "assert_state",
    "assert_unitary",
    "available_backends",
    "configure",
    "detect_backend",
    "get_backend",
    "inspect",
    "run",
    "settings",
]


def run(
    circuit: Any,
    *,
    backend: str | None = None,
    args: tuple[Any, ...] = (),
    trace: bool | str = False,
) -> ExecutionResult:
    """Execute a circuit with per-gate statevector capture.

    ``backend`` names a registered backend explicitly; when omitted, the
    backend is detected from the circuit object's type. ``args`` binds
    parameter values for parameterized circuits.

    ``trace=True`` records the run as a TraceAct trace (gate events per
    circuit layer, final-state snapshot spooled to a sidecar file);
    ``trace="gates"`` records per-gate events and snapshots instead.
    Where the trace goes is TraceAct's configuration; see qlens.tracing.
    """
    resolved = get_backend(backend) if backend is not None else detect_backend(circuit)
    result = resolved.run(circuit, args=args)
    if trace:
        if trace not in (True, "gates"):
            raise QlensError(f"trace must be True or 'gates', got {trace!r}")
        from qlens import tracing

        result.traced_run = tracing.start_run(
            result, mode="gates" if trace == "gates" else "layers", args=args
        )
    return result

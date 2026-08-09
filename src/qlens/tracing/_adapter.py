"""Trace emission: one TraceAct trace per instrumented circuit run.

Modelled on TraceAct's LangChain adapter: public TraceAct API only,
traces started without entering the ambient context (so recording never
touches the caller's ContextVar stack), finished by calling __exit__
directly. Recording failures never propagate into the user's run.

The trace stays open after run() returns so later assert_* calls on the
same result can append assertion events; it closes on the next traced
run's flush, at interpreter exit, or explicitly via finish().
"""

from __future__ import annotations

import math
import sys
import sysconfig
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from qlens._layers import group_layers

if TYPE_CHECKING:
    from qlens._execution import ExecutionResult
    from qlens.tracing import TracingSettings

# Slack on top of the computed event need: assertion events recorded
# after the run, plus room for TraceAct's own bookkeeping.
_BUDGET_SLACK = 64

# An expected distribution rides along in the event so the viewer can
# ghost it behind the observed bars. TraceAct drops any single value over
# max_payload_bytes (8KB), so cap the entry count well under that; a
# larger reference is a viewer nicety, not something worth truncating a
# payload over.
_MAX_EXPECTED_ENTRIES = 256


def _caller_location() -> str | None:
    """``file:line`` of the first frame that is neither qlens nor the
    standard library — the test that made the assertion.

    Returns None when there is no such frame. Skipping the standard
    library matters: an assertion made from inside qlens itself would
    otherwise be attributed to whatever ran it, and ``<frozen runpy>:88``
    is worse than no source at all.
    """
    skip = (str(Path(__file__).resolve().parent.parent), sysconfig.get_paths()["stdlib"])
    frame: Any = sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename
        if not filename.startswith("<"):
            resolved = str(Path(filename).resolve())
            if not any(resolved.startswith(root) for root in skip):
                return f"{filename}:{frame.f_lineno}"
        frame = frame.f_back
    return None


def _finite(value: float) -> float | None:
    """JSON has no infinity or NaN; those become null."""
    return float(value) if math.isfinite(value) else None


def assertion_fields(
    result: Any,
    name: str,
    target: str,
    error: BaseException | None,
    details: dict[str, float] | None,
    expected: Any,
) -> dict[str, Any]:
    """Build the ``trace.event()`` kwargs for one assertion.

    Carries what the viewer's assertion table and expected-vs-observed
    overlay need: where in the run it applies, where in the source it was
    written, the measured numbers, and the reference distribution.
    """
    fields: dict[str, Any] = {
        "kind": "assertion",
        "operation": "check",
        "target": target,
        "assertion": name,
        "status": "failed" if error is not None else "completed",
    }
    if error is not None:
        fields["error"] = {"type": type(error).__name__, "message": str(error)}

    snapshots = getattr(result, "snapshots", None)
    if snapshots:
        # Assertions run against the result as a whole, so they apply at
        # the last captured position. Positions are per-gate indices, so
        # this is where the viewer places the marker.
        fields["position"] = int(snapshots[-1].position)

    source = _caller_location()
    if source is not None:
        fields["source"] = source
    if details:
        fields["details"] = {k: _finite(v) for k, v in details.items()}
    if expected is not None and len(expected) <= _MAX_EXPECTED_ENTRIES:
        total = sum(float(v) for v in expected.values())
        if total > 0:
            fields["expected"] = {
                str(k): float(v) / total for k, v in expected.items()
            }
    return fields


class TracedRun:
    """An open trace for one executed circuit."""

    def __init__(self, trace: Any, trace_id: str) -> None:
        self._trace = trace
        self.trace_id = trace_id
        self._open = True
        self._failed: BaseException | None = None

    def record_assertion(
        self, error: BaseException | None, fields: dict[str, Any]
    ) -> None:
        if not self._open:
            return
        if error is not None:
            self._failed = error
        self._trace.event(**fields)

    def finish(self) -> None:
        """Close the trace. Failed assertions fail the whole trace."""
        if not self._open:
            return
        self._open = False
        error = self._failed
        if error is not None:
            self._trace.__exit__(type(error), error, error.__traceback__)
        else:
            self._trace.__exit__(None, None, None)


def record_run(
    result: ExecutionResult,
    *,
    mode: str,
    settings: TracingSettings,
    args: tuple[Any, ...] = (),
) -> TracedRun:
    """Emit gate/qstate events for an executed circuit and return the
    still-open TracedRun."""
    from traceact import ActionTrace, TraceBudget

    from qlens.tracing._spool import state_ref, write_sidecar

    gate_snapshots = [s for s in result.snapshots if s.gate != "initial"]
    layers = group_layers(gate_snapshots)

    if mode == "gates":
        needed = len(gate_snapshots) + len(gate_snapshots)  # gate + qstate each
    else:
        needed = len(layers) + 1  # layer events + final qstate
    max_events = max(settings.max_events, needed + _BUDGET_SLACK)

    trace = ActionTrace.start(
        action="circuit.run",
        kind="app",
        actor="qlens",
        project=settings.project,
        correlation_id=settings.correlation_id,
        budget=TraceBudget(max_events=max_events),
    )
    trace.set_meta("backend", result.backend)
    trace.set_meta("num_qubits", result.num_qubits)
    trace.set_meta("gate_count", len(gate_snapshots))
    trace.set_meta("capture_mode", mode)
    if args:
        trace.set_meta("circuit_args", [float(a) for a in args])

    trace_id = str(getattr(trace, "trace_id", "")) or "trc_unknown"
    write_sidecar(settings.state_dir, trace_id, result.snapshots)

    if mode == "gates":
        for snapshot in gate_snapshots:
            trace.event(
                kind="gate",
                operation="apply",
                target=f"q{snapshot.qubits[0]}" if snapshot.qubits else "q?",
                gate=snapshot.gate,
                position=snapshot.position,
                qubits=list(snapshot.qubits),
                params=snapshot.params,
            )
            trace.event(
                kind="qstate",
                operation="snapshot",
                target=f"pos{snapshot.position}",
                position=snapshot.position,
                statevector_ref=state_ref(trace_id, snapshot.position),
                num_qubits=result.num_qubits,
                norm_check=float(np.linalg.norm(snapshot.statevector)),
            )
    else:
        for layer in layers:
            trace.event(
                kind="gate",
                operation="apply_layer",
                target=f"layer{layer.index}",
                position=layer.index,
                qubits=list(layer.qubits),
                gates=[
                    {
                        "gate": s.gate,
                        "qubits": list(s.qubits),
                        "params": s.params,
                        "position": s.position,
                    }
                    for s in layer.snapshots
                ],
            )
        final = result.snapshots[-1]
        trace.event(
            kind="qstate",
            operation="snapshot",
            target="final",
            position=final.position,
            statevector_ref=state_ref(trace_id, final.position),
            num_qubits=result.num_qubits,
            norm_check=float(np.linalg.norm(final.statevector)),
        )

    return TracedRun(trace, trace_id)

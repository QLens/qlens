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

import json
import math
import sys
import sysconfig
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from qlens import _config as config
from qlens._layers import group_layers

if TYPE_CHECKING:
    from qlens._execution import ExecutionResult
    from qlens.tracing import TracingSettings

# Slack on top of the computed event need: assertion events recorded
# after the run, plus room for TraceAct's own bookkeeping.
_BUDGET_SLACK = 64

# An expected distribution rides along in the event so the viewer can
# ghost it behind the observed bars.
#
# The binding limit is bytes, not entries. TraceAct deletes any single
# value over max_payload_bytes (8192 by default), and an entry's size
# depends on how wide its bitstring key is: 256 outcomes of a 6-qubit run
# serialize to about 2KB, the same 256 outcomes of a 12-qubit run to over
# 10KB. Counting entries would keep the narrow case well inside the
# budget and push the wide one past it, which is exactly the case a wide
# expectation arrives in.
#
# Budgeted below 8192 so the estimate here never has to be exact to the
# byte against whatever encoder TraceAct uses.
_MAX_EXPECTED_BYTES = 6144
# A secondary ceiling for the viewer's sake rather than the payload's:
# past a few hundred ghosted bars nobody is reading individual outcomes.
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
    *,
    at: int | None = None,
    method: str | None = None,
    verdict: Any = None,
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
        # Where the viewer puts the marker: the position the assertion
        # named, or the end of the run when it named none. Negative
        # indices resolve here so the recorded position is absolute.
        index = -1 if at is None else at
        try:
            fields["position"] = int(snapshots[index].position)
        except IndexError:
            fields["position"] = int(snapshots[-1].position)
    if method:
        fields["method"] = method
    if verdict is not None:
        fields["reliability"] = verdict.as_event_field()

    source = _caller_location()
    if source is not None:
        fields["source"] = source
    if details:
        fields["details"] = {k: _finite(v) for k, v in details.items()}
    if expected is not None:
        fields.update(_expected_fields(expected))
    return fields


def _expected_fields(expected: Mapping[str, float]) -> dict[str, Any]:
    """The reference distribution, trimmed to what a payload can carry.

    A wide expectation is common and mostly empty: a check written against
    a 9-qubit run names all 512 outcomes so the sampler cannot draw one
    the expectation calls impossible, and 496 of them are zero. Dropping
    the whole thing over its length would lose an overlay that fits
    easily once the zeros go.

    So zeros go first, then the smallest outcomes, and what survives is
    reported. Silently keeping a fraction would leave the viewer ghosting
    part of a distribution while presenting it as the whole one.
    """
    total = sum(float(v) for v in expected.values())
    if total <= 0:
        return {}
    ranked = sorted(
        ((str(k), float(v) / total) for k, v in expected.items() if float(v) > 0),
        key=lambda item: -item[1],
    )
    kept = _fit_to_budget(ranked)
    # Probabilities are against the original total, not the kept total, so
    # a surviving bar keeps the height the check actually expected of it
    # rather than being inflated to cover what was dropped.
    fields: dict[str, Any] = {"expected": dict(kept)}
    if len(kept) < len(expected):
        fields["expected_trimmed"] = {
            "kept": len(kept),
            "of": len(expected),
            "coverage": sum(v for _, v in kept),
        }
    return fields


def _fit_to_budget(ranked: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """As many of the largest outcomes as the payload budget allows.

    The cheap estimate gets close, then an exact serialize confirms it.
    The estimate is not a reliable upper bound — ``repr`` and ``json``
    disagree on some floats (``json.dumps(0.1)`` is longer than
    ``repr(0.1)``), so a slice the estimate calls safe can serialize a few
    hundred bytes over. Measured, not assumed: a 2000-case check found the
    real payload up to ~300 bytes above the estimate. So the estimate
    picks a candidate quickly, and the loop drops entries until the actual
    encoded size fits.
    """
    kept: list[tuple[str, float]] = []
    size = 2  # the enclosing braces
    for key, value in ranked[:_MAX_EXPECTED_ENTRIES]:
        size += len(key) + len(repr(value)) + 4  # "key":value,
        if size > _MAX_EXPECTED_BYTES:
            break
        kept.append((key, value))
    while kept and len(json.dumps(dict(kept)).encode()) > _MAX_EXPECTED_BYTES:
        kept.pop()
    return kept


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
    # So the viewer can report which settings a run used rather
    # than assuming the defaults were in force.
    trace.set_meta("settings", config.effective())
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

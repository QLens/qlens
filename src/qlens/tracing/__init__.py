"""TraceAct integration: recording circuit runs as traces.

Enable per run with ``qlens.run(circuit, trace=True)`` (layer-grained)
or ``trace="gates"`` (per-gate events and snapshots). Module-level
settings live here:

    import qlens.tracing
    qlens.tracing.configure(state_dir="data/qstates",
                            project="my-experiment",
                            correlation_id="corr_sweep_1")

Where the trace goes is TraceAct's own configuration (``traceact.configure``
with sinks); qlens only emits.

A run's trace stays open after ``run()`` returns so ``assert_*`` calls
against the result append assertion events to the same timeline. Open
traces close on the next flush point: an explicit ``finish_traces()``,
the end of each test when the pytest plugin is active, or interpreter
exit.
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qlens._execution import ExecutionResult
    from qlens.tracing._adapter import TracedRun

__all__ = ["configure", "finish_traces", "settings"]

# Floor for the per-trace event budget. TraceAct's package default (100)
# is sized for classical app traces; circuit runs routinely produce
# hundreds of layers, and the TraceAct viewer's own query limit sits at
# this order of magnitude. The adapter raises the budget further per run
# whenever the circuit itself needs more.
DEFAULT_MAX_EVENTS = 1000


@dataclass
class TracingSettings:
    state_dir: str = "data/qstates"
    project: str | None = None
    correlation_id: str | None = None
    max_events: int = DEFAULT_MAX_EVENTS
    _open_runs: list[TracedRun] = field(default_factory=list, repr=False)


settings = TracingSettings()


def configure(
    *,
    state_dir: str | None = None,
    project: str | None = None,
    correlation_id: str | None = None,
    max_events: int | None = None,
) -> None:
    """Set module-level tracing options. Only passed fields change."""
    if state_dir is not None:
        settings.state_dir = state_dir
    if project is not None:
        settings.project = project
    if correlation_id is not None:
        settings.correlation_id = correlation_id
    if max_events is not None:
        settings.max_events = max_events


def start_run(
    result: ExecutionResult, mode: str, args: tuple[Any, ...] = ()
) -> TracedRun | None:
    """Record a run and register its open trace. Returns None (and
    records nothing) if recording fails — tracing never breaks a run."""
    from qlens.tracing._adapter import record_run

    try:
        run = record_run(result, mode=mode, settings=settings, args=args)
    except Exception:
        return None
    settings._open_runs.append(run)
    return run


def record_assertion(
    result: Any,
    name: str,
    target: str,
    error: BaseException | None,
    *,
    details: dict[str, float] | None = None,
    expected: Any = None,
) -> None:
    """Append an assertion event to the run that produced ``result``,
    or to the ambient TraceAct trace when there is one. No-op otherwise;
    never raises."""
    try:
        from qlens.tracing._adapter import assertion_fields

        fields = assertion_fields(result, name, target, error, details, expected)
        run = getattr(result, "traced_run", None)
        if run is None and len(settings._open_runs) == 1:
            # assert_unitary and assert_equivalent take a circuit, not a
            # result, so they carry no link to the run under test. With
            # exactly one run open the attribution is unambiguous; with
            # several it would be a guess, so those go unattributed.
            run = settings._open_runs[0]
        if run is not None:
            run.record_assertion(error, fields)
            return
        from traceact.context import get_active_trace

        trace = get_active_trace()
        if trace is None:
            return
        trace.event(**fields)
    except Exception:
        return


def finish_traces() -> int:
    """Close every open run trace. Returns how many were closed."""
    closed = 0
    while settings._open_runs:
        run = settings._open_runs.pop()
        try:
            run.finish()
            closed += 1
        except Exception:
            continue
    return closed


atexit.register(finish_traces)

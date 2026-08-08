"""Tracing round-trips against real TraceAct sinks.

Pattern copied from TraceAct's own LangChain adapter tests: configure a
real JsonlSink, run, read the JSONL back, assert on stored records.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import bell_program
from traceact import JsonlSink, TraceConfig, configure, reset_config

import qlens
from qlens import tracing
from qlens._inspect import Inspector

pytest.importorskip("qiskit")


@pytest.fixture()
def sink_path(tmp_path: Path) -> Any:
    path = tmp_path / "traces.jsonl"
    state_dir = tmp_path / "qstates"
    configure(
        project="qlens-test",
        config=TraceConfig(sink_mode="blocking"),
        sinks=[JsonlSink(str(path))],
    )
    tracing.configure(state_dir=str(state_dir))
    yield path
    tracing.finish_traces()
    reset_config()
    tracing.configure(state_dir="data/qstates", project=None, correlation_id=None)


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def _bell(build: Any) -> Any:
    return build(bell_program(), 2)


def test_untraced_run_writes_nothing(build: Any, sink_path: Path) -> None:
    qlens.run(_bell(build))
    tracing.finish_traces()
    assert _records(sink_path) == []


def test_invalid_trace_argument(build: Any, sink_path: Path) -> None:
    with pytest.raises(qlens.QlensError, match="trace must be"):
        qlens.run(_bell(build), trace="layers-please")


def test_layer_mode_round_trip(build: Any, sink_path: Path) -> None:
    result = qlens.run(_bell(build), trace=True)
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=0)
    tracing.finish_traces()

    records = _records(sink_path)
    assert len(records) == 1
    record = records[0]
    assert record["action"] == "circuit.run"
    assert record["status"] == "completed"
    assert record["meta"]["backend"] in {"qiskit", "pennylane"}
    assert record["meta"]["num_qubits"] == 2
    assert record["budget_hit"] is False

    kinds = [e["kind"] for e in record["events"]]
    # Bell circuit: h and cx share qubit 0, so two layers; one final
    # qstate; one assertion.
    assert kinds.count("gate") == 2
    assert kinds.count("qstate") == 1
    assert kinds.count("assertion") == 1
    assertion = next(e for e in record["events"] if e["kind"] == "assertion")
    assert assertion["status"] == "completed"


def test_failed_assertion_fails_the_trace(build: Any, sink_path: Path) -> None:
    result = qlens.run(_bell(build), trace=True)
    with pytest.raises(qlens.QlensAssertionError):
        qlens.assert_distribution(result, {"01": 0.5, "10": 0.5}, seed=0)
    tracing.finish_traces()

    record = _records(sink_path)[0]
    assert record["status"] == "failed"
    assertion = next(e for e in record["events"] if e["kind"] == "assertion")
    assert assertion["status"] == "failed"
    assert assertion["error"]["type"] == "QlensAssertionError"


def test_gates_mode_per_gate_events_and_refs(build: Any, sink_path: Path) -> None:
    qlens.run(_bell(build), trace="gates")
    tracing.finish_traces()

    record = _records(sink_path)[0]
    gate_events = [e for e in record["events"] if e["kind"] == "gate"]
    qstate_events = [e for e in record["events"] if e["kind"] == "qstate"]
    assert len(gate_events) == 2
    assert len(qstate_events) == 2
    assert gate_events[1]["qubits"] == [0, 1]
    for event in qstate_events:
        assert event["statevector_ref"].endswith(f"#pos_{event['position']}")
        assert event["norm_check"] == pytest.approx(1.0)


def test_qubit_touches_derived(build: Any, sink_path: Path) -> None:
    qlens.run(_bell(build), trace=True)
    tracing.finish_traces()
    record = _records(sink_path)[0]
    assert any(t["kind"] == "qubit" for t in record["touches"])


def test_sidecar_round_trip_through_inspector(build: Any, sink_path: Path, tmp_path: Path) -> None:
    qlens.run(_bell(build), trace="gates")
    tracing.finish_traces()

    record = _records(sink_path)[0]
    ins = Inspector.from_trace(record, str(tmp_path / "qstates"))
    assert len(ins) == 2
    expected = np.array([1, 0, 0, 1]) / np.sqrt(2)
    assert np.allclose(ins.goto(-1).statevector, expected)


def test_thousand_gate_circuit_stays_under_budget(sink_path: Path) -> None:
    from qiskit import QuantumCircuit

    circuit = QuantumCircuit(4)
    for i in range(1000):
        circuit.rx(0.01 * (i + 1), i % 4)
    result = qlens.run(circuit, trace=True)
    assert len(result.snapshots) == 1000
    tracing.finish_traces()

    record = _records(sink_path)[0]
    assert record["budget_hit"] is False
    layer_events = [e for e in record["events"] if e["kind"] == "gate"]
    assert len(layer_events) == 250  # 4 disjoint gates per layer


def test_tracing_never_breaks_the_run(build: Any, sink_path: Path, tmp_path: Path) -> None:
    # An unwritable state_dir must not stop the circuit from executing.
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the directory should be")
    tracing.configure(state_dir=str(blocker / "nested"))
    result = qlens.run(_bell(build), trace=True)
    assert result.traced_run is None
    assert len(result.snapshots) == 2


def test_finish_traces_is_idempotent(build: Any, sink_path: Path) -> None:
    qlens.run(_bell(build), trace=True)
    assert tracing.finish_traces() == 1
    assert tracing.finish_traces() == 0
    assert len(_records(sink_path)) == 1

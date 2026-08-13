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


# -- trimming a wide expectation ---------------------------------------


def _expected(**kwargs: Any) -> dict[str, Any]:
    from qlens.tracing._adapter import _expected_fields

    return _expected_fields(kwargs)


def test_an_all_zero_expectation_records_nothing() -> None:
    """Dividing by the total would be a divide by zero, and there is no
    distribution to ghost anyway."""
    assert _expected(**{"00": 0.0, "01": 0.0}) == {}


def test_a_small_expectation_is_recorded_whole_and_unflagged() -> None:
    fields = _expected(**{"00": 0.5, "11": 0.5})
    assert fields["expected"] == {"00": 0.5, "11": 0.5}
    assert "expected_trimmed" not in fields


def test_relative_weights_are_normalized() -> None:
    fields = _expected(**{"00": 3.0, "11": 1.0})
    assert fields["expected"] == {"00": 0.75, "11": 0.25}


def test_zero_entries_are_dropped_rather_than_costing_the_whole_expectation() -> None:
    """The case that lost the overlay on the 9-qubit demo run: a check
    naming every outcome of a 512-state register so the sampler cannot
    draw one it calls impossible, of which 496 are zero."""
    from qlens.tracing._adapter import _MAX_EXPECTED_ENTRIES

    wide = {format(i, "09b"): 0.0 for i in range(512)}
    for i in range(16):
        wide[format(i * 7, "09b")] = 1 / 16

    fields = _expected(**wide)
    assert len(fields["expected"]) == 16, "the nonzero outcomes fit easily"
    assert len(fields["expected"]) <= _MAX_EXPECTED_ENTRIES
    # Every outcome that carried probability survived, so the overlay is
    # the whole distribution despite the entry count.
    assert fields["expected_trimmed"]["coverage"] == pytest.approx(1.0)
    assert fields["expected_trimmed"]["of"] == 512
    assert fields["expected_trimmed"]["kept"] == 16


def test_an_expectation_too_wide_to_carry_keeps_its_largest_outcomes() -> None:
    """Which outcomes survive matters more than how many: a ghost of the
    dominant terms is a useful overlay, a ghost of the negligible ones is
    an empty chart."""
    wide = {format(i, "012b"): float(i + 1) for i in range(1000)}
    fields = _expected(**wide)
    assert 0 < len(fields["expected"]) < 1000
    assert format(999, "012b") in fields["expected"], "the largest is kept"
    assert format(0, "012b") not in fields["expected"], "the smallest is not"


def test_a_trimmed_expectation_reports_what_it_dropped() -> None:
    wide = {format(i, "012b"): float(i + 1) for i in range(1000)}
    trimmed = _expected(**wide)["expected_trimmed"]
    assert trimmed["kept"] < trimmed["of"] == 1000
    assert 0.0 < trimmed["coverage"] < 1.0, "some mass was genuinely lost"


def test_a_kept_outcome_keeps_the_probability_the_check_expected() -> None:
    """Normalizing against the kept total instead of the original would
    inflate every surviving bar to cover the dropped mass."""
    wide = {format(i, "012b"): 1.0 for i in range(1000)}
    fields = _expected(**wide)
    for probability in fields["expected"].values():
        assert probability == pytest.approx(1 / 1000)


def test_a_trimmed_expectation_survives_traceacts_payload_limit_at_every_width() -> None:
    """The budget is bytes, not entries, because an entry's size follows
    its bitstring width: 256 outcomes of a 6-qubit run serialize to about
    2KB and the same 256 of a 12-qubit run to over 10KB. Counting entries
    kept the narrow case safe and pushed the wide one past the limit,
    which is where a wide expectation actually arrives.

    Checked against TraceAct's limit rather than qlens's own budget, so
    raising the budget past what TraceAct accepts fails here."""
    import json

    from qlens.tracing._adapter import _expected_fields

    limit = _traceact_payload_limit()
    for num_qubits in (4, 6, 9, 12, 16, 20):
        width = min(2**num_qubits, 4096)
        wide = {format(i, f"0{num_qubits}b"): float(i + 1) for i in range(width)}
        recorded = _expected_fields(wide)["expected"]
        size = len(json.dumps(recorded).encode())
        assert size <= limit, f"{num_qubits} qubits serialized to {size} > {limit}"
        assert recorded, f"{num_qubits} qubits kept nothing"

def _traceact_payload_limit() -> int:
    """TraceAct's own per-value budget, read from TraceAct rather than
    restated here. The requirement these tests hold is that a recorded
    expectation survives capture, which is a fact about TraceAct's limit,
    not about whatever internal budget qlens picked to stay under it."""
    from traceact.budget import BUDGET_DEFAULTS

    return int(BUDGET_DEFAULTS["max_payload_bytes"])



def test_no_trimmed_slice_ever_exceeds_the_payload_limit() -> None:
    """The estimate isn't a reliable upper bound — repr and json disagree
    on some floats, so a slice the estimate accepts can serialize a few
    hundred bytes over. This fuzzes widths and random probabilities to
    hold the exact re-measure honest; without it, some slice overshoots."""
    import json
    import random

    from qlens.tracing._adapter import _expected_fields

    limit = _traceact_payload_limit()
    rng = random.Random(1)
    for _ in range(400):
        num_qubits = rng.randint(1, 16)
        count = rng.randint(1, 500)
        wide = {
            format(rng.randrange(2**num_qubits), f"0{num_qubits}b"): rng.random()
            for _ in range(count)
        }
        recorded = _expected_fields(wide).get("expected", {})
        size = len(json.dumps(recorded).encode())
        assert size <= limit, f"{num_qubits} qubits, {count} entries -> {size} > {limit}"

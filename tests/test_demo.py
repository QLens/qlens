"""The bundled sample runs.

These have to work on a bare install, so nothing here imports a provider
framework — that is the point of generating them on the reference
simulator, and this module is the check that it stays true.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from traceact import JsonlSink, TraceConfig, configure, reset_config

from qlens import tracing
from qlens.viewer._demo import generate


@pytest.fixture()
def demo(tmp_path: Path) -> Any:
    configure(config=TraceConfig(sink_mode="blocking"), sinks=[JsonlSink(str(tmp_path / "x.jsonl"))])
    source, state_dir = generate(tmp_path / "demo")
    records = [json.loads(line) for line in Path(source).read_text().splitlines()]
    yield records, Path(state_dir)
    reset_config()
    tracing.configure(state_dir="data/qstates", project=None, correlation_id=None)


def test_generates_three_runs_with_sidecars(demo: Any) -> None:
    records, state_dir = demo
    finished = [r for r in records if not r.get("in_flight")]
    assert len(finished) == 3
    for record in finished:
        assert record["action"] == "circuit.run"
        assert (state_dir / f"{record['trace_id']}.npz").is_file()


def test_exactly_one_run_fails(demo: Any) -> None:
    """A viewer with nothing failing has no red marker to click, and one
    with everything failing has no contrast."""
    records, _ = demo
    statuses = sorted(r["status"] for r in records if not r.get("in_flight"))
    assert statuses == ["completed", "completed", "failed"]


def test_failing_run_carries_a_clickable_assertion(demo: Any) -> None:
    records, _ = demo
    failing = next(r for r in records if r.get("status") == "failed")
    assertions = [e for e in failing["events"] if e["kind"] == "assertion"]
    failed = [a for a in assertions if a["status"] == "failed"]
    assert len(failed) == 1
    # Everything the assertions tab and the timeline marker need.
    assert failed[0]["position"] is not None
    assert failed[0]["details"]["tolerance"] == pytest.approx(0.05)
    assert failed[0]["expected"]


def test_sidecar_holds_every_position(demo: Any) -> None:
    records, state_dir = demo
    for record in (r for r in records if not r.get("in_flight")):
        with np.load(state_dir / f"{record['trace_id']}.npz") as archive:
            captured = sorted(int(name[4:]) for name in archive.files)
        assert captured == list(range(record["meta"]["gate_count"]))


def test_states_are_normalized(demo: Any) -> None:
    records, state_dir = demo
    record = next(r for r in records if not r.get("in_flight"))
    with np.load(state_dir / f"{record['trace_id']}.npz") as archive:
        for name in archive.files:
            assert float(np.linalg.norm(archive[name])) == pytest.approx(1.0)


def test_generating_imports_no_provider_framework(tmp_path: Path) -> None:
    """The demo is what a user with neither Qiskit nor PennyLane installed
    sees first, so it must generate in a process that has neither."""
    script = (
        "import sys, json\n"
        "import traceact\n"
        "from traceact import JsonlSink, TraceConfig\n"
        f"traceact.configure(config=TraceConfig(sink_mode='blocking'),"
        f" sinks=[JsonlSink({str(tmp_path / 'sink.jsonl')!r})])\n"
        "from qlens.viewer._demo import generate\n"
        f"generate({str(tmp_path / 'out')!r})\n"
        "print(json.dumps([m for m in ('qiskit', 'pennylane', 'cirq')"
        " if m in sys.modules]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []


def test_runs_are_reproducible(tmp_path: Path) -> None:
    configure(config=TraceConfig(sink_mode="blocking"), sinks=[JsonlSink(str(tmp_path / "x.jsonl"))])
    try:
        _, first_dir = generate(tmp_path / "a")
        _, second_dir = generate(tmp_path / "b")
        # Trace ids are random, so filenames cannot pair the two batches;
        # the qubit count identifies which sample run is which.
        first = _by_width(first_dir)
        second = _by_width(second_dir)
        assert sorted(first) == sorted(second) == [16, 64, 512]
        for width, states in first.items():
            np.testing.assert_allclose(states, second[width])
    finally:
        reset_config()
        tracing.configure(state_dir="data/qstates", project=None, correlation_id=None)


def _by_width(directory: str | Path) -> dict[int, np.ndarray]:
    """Each sample run's final statevector, keyed by basis size."""
    out: dict[int, np.ndarray] = {}
    for path in Path(directory).glob("*.npz"):
        with np.load(path) as archive:
            last = max(archive.files, key=lambda name: int(name[4:]))
            state = np.asarray(archive[last])
        out[len(state)] = state
    return out


def test_demo_assertions_have_no_misleading_source() -> None:
    """Through the CLI there is no user frame under the qlens ones, only
    runpy. Attributing an assertion to `<frozen runpy>:88` is worse than
    reporting no source at all.

    This runs the real command rather than calling generate() directly:
    under pytest the test function itself is a legitimate non-stdlib
    caller, so the frame walk would find it and the check would pass
    whether or not stdlib frames are skipped.
    """
    process = subprocess.Popen(
        [sys.executable, "-u", "-m", "qlens.viewer.cli", "view", "--demo",
         "--no-browser", "--port", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        directory = None
        assert process.stdout is not None
        for line in process.stdout:
            if "generated sample runs in" in line:
                directory = Path(line.strip().rsplit(" ", 1)[-1])
            if directory and "viewer on" in line:
                break
        assert directory is not None, "the CLI never reported a demo directory"
    finally:
        process.terminate()
        process.wait(timeout=15)

    records = [
        json.loads(line)
        for line in (directory / "traces.jsonl").read_text().splitlines()
    ]
    sources = [
        event.get("source")
        for record in records
        for event in record.get("events", [])
        if event["kind"] == "assertion"
    ]
    assert sources, "the demo recorded no assertions"
    assert all(source is None for source in sources), sources

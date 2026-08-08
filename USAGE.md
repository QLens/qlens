# Qlens Usage

Full manual for Qlens. For project context and install, see [README.md](https://github.com/qlens/qlens/blob/main/README.md). For the semantic conventions every result follows, see [CONVENTIONS.md](https://github.com/qlens/qlens/blob/main/CONVENTIONS.md).

## Install

```bash
pip install qlens[qiskit]
```

Extras select the framework(s) you use: `qlens[qiskit]`, `qlens[pennylane]`, or both. The core package installs no quantum framework itself. Python 3.11+.

## 5-minute quickstart

Write a pytest test asserting a Bell circuit produces the Bell distribution:

```python
import qlens
from qiskit import QuantumCircuit


def test_bell_distribution():
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)

    result = qlens.run(circuit)
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=0)


def test_bell_state_evolution():
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)

    result = qlens.run(circuit)
    # Statevector after each gate, big-endian (qubit 0 leftmost).
    after_h = result.statevector_at(0)
    assert abs(after_h[0]) > 0.7  # |00> amplitude
    assert abs(after_h[2]) > 0.7  # |10> amplitude
```

Run it:

```bash
pytest test_bell.py
```

Both tests pass. No backend configuration, no manual `save_statevector` calls, no statistics code.

The same circuit in PennyLane works identically, and produces the same canonical results:

```python
import pennylane as qml
import qlens


def test_bell_distribution_pennylane():
    @qml.qnode(qml.device("default.qubit", wires=2))
    def circuit():
        qml.Hadamard(wires=0)
        qml.CNOT(wires=[0, 1])
        return qml.state()

    result = qlens.run(circuit)
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=0)
```

## qlens.run

```python
result = qlens.run(circuit, backend=None, args=())
```

Executes a circuit with per-gate statevector capture and returns an `ExecutionResult`.

| Parameter | Meaning |
|---|---|
| `circuit` | A `qiskit.QuantumCircuit` or a PennyLane `QNode`. The framework is detected from the object type; `backend="qiskit"` or `backend="pennylane"` forces it. |
| `args` | Parameter values for parameterized circuits, bound positionally. |

`ExecutionResult`:

| Member | Meaning |
|---|---|
| `snapshots` | One `Snapshot` per gate, in execution order: `position`, `gate` (lowercase name), `qubits` (indices, controls first), `params`, `statevector`. |
| `statevector_at(position)` | Statevector immediately after the gate at that position. |
| `final_statevector` | Statevector after the last gate. |
| `counts(shots=1024, seed=None)` | Sampled measurement counts over all qubits, big-endian bitstring keys. Lazy and cached per (shots, seed). |

Any measurement the circuit itself declares is ignored: Qlens measures all qubits in the computational basis, identically on every backend. Circuits containing mid-circuit measurement or reset raise `UnsupportedCircuitError` (Phase 1 captures pure statevector evolution).

## Assertions

All assertion failures raise `QlensAssertionError`, a subclass of `AssertionError`, so pytest reports them as test failures.

### assert_distribution

```python
qlens.assert_distribution(result, expected, tolerance=0.05, test="chi_square", shots=1024)
```

Validates sampled output against an expected distribution.

| Parameter | Meaning |
|---|---|
| `result` | An `ExecutionResult`, a raw `{bitstring: count}` mapping, or (KS only) an array of continuous samples. |
| `expected` | `{bitstring: probability}` for chi-square (relative weights accepted). For KS: an array of reference samples, or a scipy distribution name with `reference_args`. |
| `tolerance` | Significance level. The assertion passes when the p-value is at or above it. |
| `test` | `"chi_square"` (default) or `"ks"`. |
| `seed` | Seeds the sampling when `result` is an `ExecutionResult`. Without it, a correct circuit fails at rate `tolerance` by chance; seed CI tests. |

**Choosing the test.** Use `chi_square` for discrete measurement outcomes, which is the normal case: comparing bitstring counts against expected probabilities. Use `ks` for continuous-valued samples, such as a sequence of expectation-value estimates. Passing counts to `ks` or samples to `chi_square` raises `QlensError` rather than silently computing the wrong statistic.

**Reading the tolerance.** `tolerance` is a significance level, not a distance. `tolerance=0.05` means: reject when the observed counts would occur less than 5% of the time under the expected distribution. Raising it makes the test stricter. A correct circuit fails at rate `tolerance` by chance; a suite of unseeded 0.05-level assertions flakes at 5% per assertion. Pass `seed` to make sampling reproducible; the seed reproduces within one backend and version, not across them.

### assert_unitary

```python
qlens.assert_unitary(circuit, atol=1e-8, args=())
```

Asserts the circuit's whole operation is unitary within `atol`. The failure message reports the largest deviation of U†U from the identity.

### assert_equivalent

```python
qlens.assert_equivalent(circuit_a, circuit_b, atol=1e-8, args=())
```

Asserts two circuits compute the same unitary, ignoring global phase. Different gate decompositions of the same operation pass; circuits differing by a relative phase fail. Both circuits must come from the same framework.

## Pytest plugin

Installing qlens registers a pytest plugin automatically. It provides:

- Fixtures: `qlens_run`, `assert_distribution`, `assert_unitary`, `assert_equivalent`. Tests can take them as arguments instead of importing qlens.
- A `qlens` marker for tagging quantum tests, selectable with `pytest -m qlens`.

```python
import pytest
from qiskit import QuantumCircuit


@pytest.mark.qlens
def test_bell(qlens_run, assert_distribution):
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    assert_distribution(qlens_run(circuit), {"00": 0.5, "11": 0.5}, seed=0)
```

## Parameterized circuits

Pass values through `args`, positionally:

```python
from qiskit.circuit import Parameter

theta = Parameter("theta")
circuit = QuantumCircuit(1)
circuit.rx(theta, 0)

result = qlens.run(circuit, args=(0.7,))
```

For PennyLane, `args` are the QNode's own call arguments:

```python
@qml.qnode(qml.device("default.qubit", wires=1))
def circuit(theta):
    qml.RX(theta, wires=0)
    return qml.state()

result = qlens.run(circuit, args=(0.7,))
```

Running a parameterized circuit without `args` raises `UnsupportedCircuitError`.

## Error types

| Error | Raised when |
|---|---|
| `QlensAssertionError` | An `assert_*` check failed. Also an `AssertionError`. |
| `UnsupportedCircuitError` | The circuit contains an instruction the operation cannot handle (mid-circuit measurement, reset, unbound parameters). |
| `BackendNotFoundError` | No registered backend matches the requested name or circuit object. |
| `BackendNotInstalledError` | The backend exists but its framework package is not installed; the message carries the pip command. |
| `QlensError` | Base class of all of the above, plus argument-validation errors. |

## Writing a third-party backend

Qlens discovers backends through the `qlens.backends` entry-point group; its own two backends register through that same mechanism. To add a framework:

1. Implement the `qlens.backends.Backend` ABC: `run`, `operator_matrix`, `is_unitary`, `equivalent`, `counts`, and the `handles()` classmethod. `handles()` must recognize your framework's circuit type by module-name inspection without importing the framework.
2. Follow [CONVENTIONS.md](https://github.com/qlens/qlens/blob/main/CONVENTIONS.md) for every output: big-endian bitstrings and basis ordering, canonical qubit indices, counts shape.
3. Register it in your package's `pyproject.toml`:

```toml
[project.entry-points."qlens.backends"]
myframework = "qlens_myframework:MyBackend"
```

4. Certify against the conformance suite:

```python
from qlens.conformance import run_conformance

failures = run_conformance(MyBackend(), build=my_program_interpreter)
assert not failures
```

`build` interprets the suite's neutral gate programs (vocabulary: `i x y z h s t cx cz swap ccx rx ry rz`) into your framework's circuits; the two bundled interpreters in `qlens.conformance._builders` are the reference examples. Expected results come from an independent reference simulator, so certifying against the suite is certifying against the spec, not against another framework.

## Step-through inspection

`qlens.inspect(result)` opens a cursor over a run's captured snapshots. Nothing re-executes: the run already captured the statevector at every gate boundary.

```python
result = qlens.run(circuit)
ins = qlens.inspect(result)

ins.current            # Snapshot at the cursor (starts at position 0)
ins.step()             # advance one gate
ins.step_back()        # go back one gate
ins.goto(-1)           # jump anywhere (negative indices work)
ins.probabilities()    # {"00": 0.5, "11": 0.5} at the cursor
```

`ins.diff(a, b)` compares the states at two positions:

```python
diff = ins.diff(0, 1)
diff.fidelity            # |<a|b>|^2 — 1.0 means identical up to global phase
diff.amplitude_deltas    # {"10": (-0.707+0j), "11": (0.707+0j)}
```

Stepping past either end raises `QlensError` rather than pinning silently. `Inspector.from_trace(record, state_dir)` rebuilds an inspector from a stored trace record and its statevector sidecar, so a recorded run inspects the same way a live one does.

## Recording runs as traces

Qlens records circuit executions as [TraceAct](https://github.com/traceact/traceact) traces. Where traces go is TraceAct's own configuration; Qlens emits.

```python
from traceact import configure, JsonlSink
import qlens
import qlens.tracing

configure(project="my-experiment", sinks=[JsonlSink("data/traces/traces.jsonl")])
qlens.tracing.configure(state_dir="data/qstates")

result = qlens.run(circuit, trace=True)
qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=0)
```

| `trace=` | What gets recorded |
|---|---|
| `True` | One `gate` event per circuit layer (qubit-disjoint groups, gates listed on the event), one final `qstate` snapshot event. The default for long circuits. |
| `"gates"` | One `gate` event and one `qstate` event per gate. Full granularity for debugging sessions. |

Statevector arrays never enter trace records (TraceAct's payload budget truncates oversized values). The adapter spools every snapshot to a compressed sidecar file, `<state_dir>/<trace_id>.npz`, and events carry a `statevector_ref` instead. Both capture modes spool every position, so the viewer scrubs through all of them either way.

`assert_*` calls made against a traced result append `assertion` events to the same trace, pass or fail; a failed assertion fails the whole trace record. The trace stays open until the end of the current test (the pytest plugin closes it automatically), an explicit `qlens.tracing.finish_traces()`, or interpreter exit.

Event budgets are computed per run from the circuit itself, with a floor of 1000 events (`qlens.tracing.configure(max_events=...)` raises or lowers the floor). A `budget_hit` flag on a Qlens trace is an anomaly, never an expected artifact.

`qlens.tracing.configure(correlation_id="corr_sweep_1")` stamps every subsequent run's trace, grouping an experiment or parameter sweep; `project=` overrides TraceAct's package-level project name for Qlens traces.

Recording never breaks a run: any failure inside the tracing layer (unwritable spool directory, sink trouble) leaves the circuit's result intact, with `result.traced_run` set to `None`.

## The viewer

```bash
qlens view data/traces/traces.jsonl
```

Opens a local web viewer over a trace source (a TraceAct `.jsonl` file, a folder of them, or a `SqliteSink` database). Runs recorded with `trace=True` or `trace="gates"` appear in the run browser; the page updates live while a test session writes new traces, including in-flight runs when TraceAct's `stream_progress` is enabled.

| Flag | Meaning |
|---|---|
| `--state-dir` | Directory holding the statevector sidecars (default `data/qstates`) |
| `--port` | First port to try (default 8766, auto-increments) |
| `--host` | Bind address (default 127.0.0.1) |
| `--no-browser` | Don't open a browser tab |

The JSON API behind the page, for anything that wants the data directly:

| Endpoint | Returns |
|---|---|
| `GET /api/health` | Version and source |
| `GET /api/circuits` | Run summaries, newest first, with assertion pass/fail counts |
| `GET /api/circuit?trace_id=` | One run: layers, gates, qstate refs, assertion markers |
| `GET /api/state?trace_id=&position=` | Amplitudes at a captured position (`-1` = final) |
| `GET /api/stream` | Server-Sent Events: run summaries as they land or change |

The same trace files open in TraceAct's own generic viewer (`traceact view`), where gate events render as generic timeline nodes.

## A debugging walkthrough

1. A test fails:

   ```python
   def test_ghz():
       result = qlens.run(build_ghz(), trace=True)
       qlens.assert_distribution(result, {"000": 0.5, "111": 0.5}, seed=0)  # fails
   ```

2. Open the viewer on the trace source: `qlens view data/traces/traces.jsonl`. The run shows a red assertion marker.

3. Step through the recorded states without re-running anything:

   ```python
   ins = qlens.inspect(result)          # or Inspector.from_trace(record, "data/qstates")
   ins.goto(-1); ins.probabilities()    # what the circuit produced
   ins.diff(0, 1)                        # where the state diverged
   ```

4. The position whose diff departs from expectation names the gate to fix.

# Qlens Usage

Full manual for Qlens. For project context and install, see [README.md](https://github.com/qlens/qlens/blob/main/README.md). For the semantic conventions every result follows, see [CONVENTIONS.md](https://github.com/qlens/qlens/blob/main/CONVENTIONS.md).

## Install

```bash
pip install qlens[qiskit]
```

Extras select the framework(s) you use: `qlens[qiskit]`, `qlens[pennylane]`, `qlens[cirq]`, or any combination. The core package installs no quantum framework itself. Python 3.11+.

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

And in Cirq:

```python
import cirq
import qlens


def test_bell_distribution_cirq():
    q = cirq.LineQubit.range(2)
    circuit = cirq.Circuit([cirq.H(q[0]), cirq.CNOT(q[0], q[1])])

    result = qlens.run(circuit)
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=0)
```

Cirq has no qubit register: a circuit has exactly the qubits its operations touch. A qubit that should occupy an axis without being acted on needs an explicit `cirq.I`, which is Cirq's own way of saying so.

## qlens.run

```python
result = qlens.run(circuit, backend=None, args=())
```

Executes a circuit with per-gate statevector capture and returns an `ExecutionResult`.

| Parameter | Meaning |
|---|---|
| `circuit` | A `qiskit.QuantumCircuit`, a PennyLane `QNode`, or a `cirq.Circuit`. The framework is detected from the object type; `backend="qiskit"`, `"pennylane"`, or `"cirq"` forces it. |
| `args` | Parameter values for parameterized circuits, bound positionally. |

`ExecutionResult`:

| Member | Meaning |
|---|---|
| `snapshots` | One `Snapshot` per gate, in execution order: `position`, `gate` (one canonical lowercase name across every backend), `native_gate` (what the framework itself called it), `qubits` (indices, controls first), `params`, `statevector`. |
| `statevector_at(position)` | Statevector immediately after the gate at that position. |
| `final_statevector` | Statevector after the last gate. |
| `counts(shots=1024, seed=None)` | Sampled measurement counts over all qubits, big-endian bitstring keys. Lazy and cached per (shots, seed). |

Any measurement the circuit itself declares is ignored: Qlens measures all qubits in the computational basis, identically on every backend. Circuits containing mid-circuit measurement or reset raise `UnsupportedCircuitError` (Phase 1 captures pure statevector evolution).

## Assertions

All assertion failures raise `QlensAssertionError`, a subclass of `AssertionError`, so pytest reports them as test failures.

### assert_distribution

```python
qlens.assert_distribution(result, expected, test="chi_square", tolerance=0.05, at=None)
```

Validates sampled output against an expected distribution.

| Parameter | Meaning |
|---|---|
| `result` | An `ExecutionResult`, a raw `{bitstring: count}` mapping, or (KS only) an array of continuous samples. |
| `expected` | `{bitstring: probability}` for the discrete tests (relative weights accepted). For KS: an array of reference samples, or a scipy distribution name with `reference_args`. |
| `test` | Which comparison to make. Defaults to the project setting, itself `chi_square`. |
| `tolerance` | Whatever the chosen test uses: a significance level for the p-value tests, a distance for `tvd`. Defaults to 0.05 either way. |
| `at` | Measure the state captured after this gate position instead of the circuit's final state. Negative indices count from the end. |
| `shots` | How many measurements to sample. Default 1024. |
| `seed` | Seeds the sampling. Without it, a correct circuit fails at rate `tolerance` by chance; seed CI tests. |

**Choosing a test.**

| `test=` | What it answers | Use when |
|---|---|---|
| `chi_square` | "How surprising would this result be if the circuit were correct?" Reports a p-value. | Every outcome is expected several times over |
| `chi_square_exact` | The same question, with the p-value simulated from `resamples` correct runs instead of read off a formula | Some outcomes are rare, which is most quantum output |
| `tvd` | "How far apart are these two distributions?" Reports a distance in [0, 1]. | You want a threshold you can picture, or the output is heavy-tailed |
| `ks` | Kolmogorov-Smirnov, for continuous-valued samples | Comparing expectation-value estimates rather than bitstring counts |

Passing counts to `ks` or samples to a discrete test raises `QlensError` rather than silently computing the wrong statistic.

**When a test doesn't suit the data.** Chi-square's p-value assumes every outcome is expected roughly five or more times. Quantum output routinely concentrates on a few states, leaving the rest expected far below once, and the p-value then swings by orders of magnitude on the sampling seed alone: such a check both flakes and misses errors it should catch.

Qlens never changes `test` on your behalf. It detects the condition, reports it, and names what would settle the question:

```
QlensStatisticsWarning: assert_distribution: chi-square assumes about 5 or more
expected counts per outcome. 10 of 16 outcomes here expect fewer (smallest:
0.00349), so this p-value can be wrong in either direction.
Instead, use test="chi_square_exact" for a simulated p-value that holds at any
count; or test="tvd" to compare by distance instead of significance; or shots at
least 1433 to populate every outcome.
```

`on_unreliable_statistics` decides what that does: `warn` (the default) raises `qlens.QlensStatisticsWarning`, `error` refuses the result, `ignore` says nothing. The verdict records onto the trace under every policy, so the viewer flags the check either way.

`tvd` gets the same treatment from the other direction: sampling never reproduces a distribution exactly, so a tolerance finer than the sampling noise at your shot count rejects correct circuits, and that's reported too.

**Reading the tolerance.** For the p-value tests, `tolerance` is a significance level, not a distance. `tolerance=0.05` means: reject when the observed counts would occur less than 5% of the time under the expected distribution. Raising it makes the test stricter. For `tvd`, `tolerance` is the distance itself: 0.02 allows the two distributions to disagree about 2% of their mass.

### assert_state

```python
qlens.assert_state(result, expected, fidelity=0.99, at=None)
```

Asserts the captured statevector matches an expected one, compared by fidelity |⟨expected|actual⟩|² and failing below `fidelity`.

Global phase is ignored: two states differing only by an overall phase factor are the same physical state and score 1.0. Relative phase isn't ignored, because it's physical and decides how amplitudes interfere later.

```python
result = qlens.run(circuit, trace=True)
qlens.assert_state(result, [SQ2, 0, 0, SQ2], at=41)   # entangled by here
```

`at` picks the gate position and is where the viewer marks the assertion on the timeline.

### assert_separable

```python
qlens.assert_separable(result, qubits, atol=1e-9, at=None)
```

Asserts the named qubits carry no correlation with the rest of the register: measuring them tells you nothing about the others.

This one asserts a *property*, not a value, so it needs no expected statevector. That's the point of it. `assert_state` requires you to already know the answer, which for anything you're debugging is exactly what you don't have.

It exists for the ancilla you forgot to uncompute. Mirroring a computation back is what releases a scratch qubit; skip the mirror and the ancilla stays entangled with your data, silently, until some later interference step turns a certain answer into a coin flip.

```python
result = qlens.run(circuit, trace=True)
qlens.assert_separable(result, [2], at=88)   # the ancilla is free again by here
```

Measured as the purity of the subsystem after tracing out the rest: exactly 1 is a product state, below 1 is entanglement. `atol` is how far below 1 still counts as separable, absorbing rounding accumulated across a long circuit.

Naming every qubit in the register is refused rather than answered. The whole register is always separable from nothing, so it would be a check that passes on every circuit ever written.

### assert_entangled

```python
qlens.assert_entangled(result, qubits, atol=1e-9, at=None)
```

The complement: asserts the named qubits *are* correlated with the rest. This is the check for a control that never took effect — a multiply-controlled operation whose controls are routed wrongly can leave the target uncorrelated with the qubits meant to drive it, and no amount of staring at the final distribution makes that obvious.

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

## Which bugs these catch

The assertions above are aimed at documented bug patterns rather than at whatever seemed worth checking. Four patterns, each with the check that finds it:

| Pattern | What it looks like | Caught by |
|---|---|---|
| Wrong qubit order | a control and target reversed, or a register read in the other endianness | `assert_state` at a position |
| Wrong gate | a same-arity substitution: `h` where `x` was meant | `assert_distribution`, or `assert_state` to localise |
| Phase error | a relative phase that leaves every measurement probability untouched | `assert_state` only |
| Ancilla not uncomputed | a scratch qubit still entangled with the data | `assert_separable` |

Two of these are worth understanding rather than just looking up.

**A phase error is invisible to measurement.** Not hard to see, *invisible*. Inject a relative phase into a GHZ circuit and the sampled counts come back byte-identical, so every distribution check passes:

```
counts, correct : {'111': 2012, '000': 2084}
counts, buggy   : {'111': 2012, '000': 2084}
state fidelity  : 0.7500
```

That isn't a shortcoming of `assert_distribution` — measurement can't distinguish those two states. It's the reason Qlens captures statevectors at all, and the reason a distribution check alone isn't a test of a quantum program.

**A leaked ancilla is silent until it isn't.** Before anything interferes, the data qubit's own statistics are unchanged, so a check watching the data passes. The damage appears later, when the interference the algorithm depends on fails to happen and a deterministic answer spreads across every outcome. `assert_separable` sees it at the point it happens, because it asks about the correlation rather than about either qubit's own numbers.

### What these don't catch

Worth stating plainly. In the largest study of quantum program bug fixes, **API misuse was the single biggest category — 30 of 96 bugs.** Qlens can't see any of them. Nor outdated API clients, nor misconfiguration, nor a wrong implementation approach. Those are static-analysis and code-review problems; [QChecker](https://arxiv.org/abs/2304.04387) is the tool shaped for them.

Qlens's slice is the semantic one: roughly a quarter of the bugs found in the wild, where the code runs cleanly and produces the wrong state. A lint pass and a state checker catch disjoint sets, and you want both.

The framing here follows the taxonomy in Huang and Martonosi's [Statistical Assertions for Validating Patterns and Finding Bugs in Quantum Programs](https://ar5iv.labs.arxiv.org/html/1905.09721) (ISCA 2019), with frequency data from [A Comprehensive Study of Bug Fixes in Quantum Programs](https://arxiv.org/abs/2201.08662). The cross-framework endianness disagreement that drives the first pattern is catalogued as "quantum plumbing" in [An experience-based classification of quantum bugs](https://arxiv.org/abs/2509.03280), and is why [CONVENTIONS.md](https://github.com/QLens/qlens/blob/main/CONVENTIONS.md) exists.

## Settings

Project defaults live in `pyproject.toml`, so a choice is made once rather than repeated on every call:

```toml
[tool.qlens]
distribution_test = "tvd"
on_unreliable_statistics = "warn"
```

| Setting | Values | Default | Meaning |
|---|---|---|---|
| `distribution_test` | `chi_square`, `chi_square_exact`, `tvd`, `ks` | `chi_square` | Which test `assert_distribution` runs when a call doesn't name one |
| `on_unreliable_statistics` | `warn`, `error`, `ignore` | `warn` | What happens when a test's assumptions don't hold for the data |
| `min_expected_count` | number | `5.0` | Expected count below which a chi-square cell counts as too sparse |
| `resamples` | integer ≥ 100 | `10000` | Samples drawn for a simulated p-value and for the TVD noise floor |

The pytest plugin loads them at collection, so a test run picks them up with no conftest wiring. `qlens.configure(**)` sets the same fields at runtime, and any `assert_*` argument overrides both. An unknown key or an invalid value raises `QlensError` naming the file, rather than being ignored.

The settings in force are recorded onto every traced run, so the viewer reports which ones a run used instead of assuming the defaults.

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
| `UnsupportedCircuitError` | The circuit contains an instruction the operation can't handle (mid-circuit measurement, reset, unbound parameters). |
| `BackendNotFoundError` | No registered backend matches the requested name or circuit object. |
| `BackendNotInstalledError` | The backend exists but its framework package isn't installed; the message carries the pip command. |
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

Each assertion event carries what the viewer needs to make it clickable:

| Field | Contents |
|---|---|
| `position` | The captured position the check applies to, which is where the timeline marker goes. Absent for checks made against a circuit rather than a result. |
| `source` | `file:line` of the call, skipping qlens's own frames and the standard library. Absent when no such frame exists. |
| `details` | The measured numbers: `statistic`, `p_value`, `tolerance`, `shots` for `assert_distribution`; `deviation` and `atol` for `assert_unitary`. Values that aren't finite (an infinite chi-square, when an outcome the expectation calls impossible was observed) record as `null`. |
| `expected` | The reference distribution, normalized to probabilities, for the viewer to ghost behind the observed bars. Omitted above 256 entries, which would exceed TraceAct's payload budget. |
| `method` | Which test ran: `chi_square`, `chi_square_exact`, `tvd`, `ks`, or `fidelity` for `assert_state`. |
| `reliability` | Whether the method's assumptions held, and if not, a plain-language summary, the numbers behind it, and the alternatives. Recorded whatever `on_unreliable_statistics` is set to. |

`assert_unitary` and `assert_equivalent` take a circuit, not a result, so they carry no link to the run under test. With exactly one traced run open they attach to it; with several they go unattributed rather than guess.

Event budgets are computed per run from the circuit itself, with a floor of 1000 events (`qlens.tracing.configure(max_events=...)` raises or lowers the floor). A `budget_hit` flag on a Qlens trace is an anomaly, never an expected artifact.

`qlens.tracing.configure(correlation_id="corr_sweep_1")` stamps every subsequent run's trace, grouping an experiment or parameter sweep; `project=` overrides TraceAct's package-level project name for Qlens traces.

Recording never breaks a run: any failure inside the tracing layer (unwritable spool directory, sink trouble) leaves the circuit's result intact, with `result.traced_run` set to `None`.

## The viewer

```bash
qlens view --demo                       # sample runs, nothing to set up
qlens view data/traces/traces.jsonl     # your own runs
```

Opens a local web viewer over a trace source (a TraceAct `.jsonl` file, a folder of them, or a `SqliteSink` database). Runs recorded with `trace=True` or `trace="gates"` appear in the run picker, and the page updates live while a test session writes new traces, including in-flight runs when TraceAct's `stream_progress` is enabled.

`--demo` generates three sample runs and opens on those instead of a source: a dense variational ansatz carrying one passing and one failing check, a sparse-subspace circuit where the collapse control has most of its rows to drop, and a GHZ state with phase winding. They execute on the bundled reference simulator, so the demo works with no quantum framework installed at all, and they're recorded through the ordinary path: the same trace events, sidecars, and assertion records an ordinary test produces.

| Flag | Meaning |
|---|---|
| `--demo` | Generate sample runs into a temporary directory and open on those |
| `--state-dir` | Directory holding the statevector sidecars (default `data/qstates`) |
| `--port` | First port to try (default 8766, auto-increments) |
| `--host` | Bind address (default 127.0.0.1) |
| `--no-browser` | Don't open a browser tab |

`./launch.sh` (or `launch.command`, `launch.bat`) does the same thing from a fresh clone, creating an environment first and falling back to `--demo` when given no source.

### The four views

| Tab | Shows |
|---|---|
| Timeline | The amplitude waterfall: one column per gate position, one row per basis state, hue for phase and brightness for magnitude. Below it the circuit's wire strip on the same x axis, then the transport. |
| State | The statevector at the cursor as probability bars, with a recorded `assert_distribution`'s expectation ghosted behind it, and the largest divergences listed. Where several checks apply, the failing one is overlaid first and a picker names the alternatives. |
| Diff | Two pinned positions side by side with fidelity \|⟨ψ_A\|ψ_B⟩\|², L2 distance, and the per-basis-state probability delta. |
| Assertions | Every recorded check with its position, source location, measured numbers, and pass/fail, plus a coverage strip showing where in the run the checks fall. A check whose statistics don't support its own verdict carries an `UNRELIABLE` badge; opening the row explains why and offers the alternatives as copyable lines. |

| Key | Action |
|---|---|
| `space` | Play / pause |
| `←` `→` | Step one position |
| `shift`+`←` `→` | Jump to the previous / next assertion |
| `home` `end` | First / last position |
| `1`–`4` | Switch tab |

**Guide** in the top bar opens the reading guide: what the waterfall shows, what phase is and why it's drawn as colour, what a position is, and how each test method decides whether a check held. It stays reachable at all times, and the ⓘ on a panel opens it at the relevant topic.

Every explanation comes in two registers, switchable from the guide header or Settings. **Simple** assumes no quantum background and explains from first principles; **Advanced** assumes the field and states the fact. The choice persists and applies to the guide, the guided tour, and the reliability notices alike.

**Settings** (the gear) holds that toggle, viewer preferences, the test settings the current run used, and **Reset dismissed notices**, which brings back the guided tour and anything else clicked away.

A run opens at its first gate with playback at 0.5×, so the transport starts where the circuit does and moves at a pace a gate can be read at. Speeds run 0.25× to 2×.

Dragging anywhere on the waterfall, the wire strip, or the scrubber moves the cursor. Hovering the waterfall or the strip names what happens at that column: the gate and its parameters, the layer it runs in, the other gates in that layer, and any check recorded there. The layer is the part worth reading, since gates in one layer share no qubit and therefore run together, which makes them the answer to what is active at a point rather than merely what is nearby. Double-clicking a column opens the State tab on it, so a spot that looks wrong in the field becomes the statevector that produced it in one gesture. On the State tab, hovering a bar reports its basis state, observed value, expected value, and divergence; clicking isolates it and dims the rest. The assertions table sorts on any column header and its widths drag, both remembered between sessions. **Collapse near-zero rows** drops basis states whose amplitude never exceeds a threshold anywhere in the run, which is what makes a 10-qubit run legible; a dashed rule marks where states were skipped.

### If something misbehaves

Every interaction handler in the viewer records what it decided, into a bounded ring you can read from the browser console:

```js
qlens.debug()            // the last 200 events
qlens.debug('scrub')     // only events whose kind contains 'scrub'
qlens.debug.table()      // the same, as a console table
qlens.debug.last('zoom') // the most recent zoom event
```

Events carry the values a branch tested rather than only the fact that it ran, so a double-click that did nothing reads as `{index: 83, quick: true, near: false, since: 37}` and names its own reason. It's always on: a capped array costs nothing, and instrumentation you have to switch on is instrumentation you don't have when you need it.

### Zooming in

The field lists what it responds to under the transport, so none of this has to be discovered. Scroll over the waterfall to zoom the time axis, hold shift and scroll to zoom the basis-state axis, and shift-drag to frame a region and jump straight to it. `+` and `-` do the same from the keyboard, `0` or `Escape` returns to the whole run, and a **Reset zoom** button appears whenever the field is showing less than everything. When it is, the panel says which slice you're looking at (`positions 74–159 of 209`) and a band on the transport shows where that slice sits in the run.

Zooming matters because of what the field does when a run is bigger than the screen. Say a run has 4096 basis states and the panel is about a thousand pixels tall. They don't fit, so the server groups every four states into one row and draws the loudest of the four.

Picture a security desk with 4096 cameras and 1000 monitors. Wire four cameras to each monitor, show whichever one has movement, and you'll see everything that happens. What you can't tell is which of the four rooms it happened in.

Zooming in rewires the cameras. Ask for two hundred of those states and they get their own rows again, one state per row, exact amplitudes rather than a summary. There's no mode to switch and nothing to configure: the field bands rows only while the range you asked for is taller than the panel, so zooming far enough stops it on its own. The panel says `1 row = 4 states` whenever a row is still standing in for several, and stops saying it once each row is a state.

The one number you can change is the ceiling. `qlens view --max-cells N` bounds how large a single request may get; the default holds a payload of roughly five megabytes. Hitting it costs rows rather than positions, since a narrower slice of time is a different question while coarser rows still answer the one you asked, and the panel shows `capped` when it happens rather than quietly handing back something coarser than you asked for.

### The JSON API

For anything that wants the data directly:

| Endpoint | Returns |
|---|---|
| `GET /api/health` | Version and source |
| `GET /api/circuits` | Run summaries, newest first, with assertion pass/fail counts |
| `GET /api/circuit?trace_id=` | One run: layers, gates, qstate refs, assertion records with their method and reliability verdict |
| `GET /api/state?trace_id=&position=` | Amplitudes at a captured position (`-1` = final) |
| `GET /api/waterfall?trace_id=` | Every position at once, reduced to display resolution |
| `GET /api/stream` | Server-Sent Events: run summaries as they land or change |

`/api/waterfall` accepts `max_rows` (display rows, default 512), `threshold` (drop basis states whose amplitude never reaches it), and a viewport: `pos_from`/`pos_to` over captured positions and `row_from`/`row_to` over the rows that survived the threshold, both half-open and both defaulting to the whole run. It returns two base64 `uint8` planes, `magnitude` and `phase`, laid out row-major at `rows × (view.pos_to - view.pos_from)`.

The response reports the viewport it actually served in `view`, which isn't always the one asked for: a range arriving inverted, or hanging off the end of a run that reloaded shorter, is clamped to something that exists rather than refused. Draw against `view` rather than against what you requested and the axes stay in step with the pixels. `row_band` says how many basis states one row stands for, `view_rows` how many the viewport covers, and `capped` whether the payload ceiling forced coarser rows than `max_rows` allowed.

Brightness is scaled against the whole run, never the viewport, so zooming in doesn't make a dim region look bright and two zoom levels of the same run stay comparable. Magnitude is normalized against `peak` and pre-warped by `mag_exponent` before quantizing: an amplitude field spans several decades, and 256 linear levels would put nearly all of it in the bottom bucket. `peak` is a high percentile rather than the maximum, because position 0 of any circuit is a basis state at magnitude 1 and would otherwise set the scale for the whole run.

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

# Qlens Architecture

```
┌──────────────────────────────────────────────────┐
│    User circuits (Qiskit / PennyLane / Cirq)       │
└──────────────────────┬─────────────────────────────┘
                        │
        ┌───────────────▼───────────────┐
        │        qlens public API         │
        │  run() · assert_distribution()  │
        │  assert_unitary() ·             │
        │  assert_equivalent() ·          │
        │  inspect() · mutate()           │
        └───────┬───────────────┬────────┘
                │               │
     ┌──────────▼─────┐   ┌─────▼──────────────┐
     │  registry        │   │  _assertions        │
     │  (entry-point     │   │  + _stats           │
     │   discovery,      │   │  (chi-square, KS,    │
     │   handles() poll) │   │   phase-invariant    │
     └──────────┬─────┘   │   compare)           │
                │           └────────────────────┘
     ┌──────────▼──────────────────────┐
     │  Backend contract (backends/base) │
     │  run / operator_matrix /          │
     │  is_unitary / equivalent / counts │
     └───────┬──────────────┬──────────┘
             │              │
   ┌────────▼───┐ ┌────▼───────────┐ ┌───▼────────┐  ┌────────────────┐
   │ QiskitBackend│ │ PennyLaneBackend│ │ CirqBackend │←─│ third-party      │
   │ (Statevector │ │ (tape rewrite + │ │ (apply_     │  │ backends via the │
   │  .evolve walk│ │  qml.snapshots, │ │  unitary    │  │ same entry-point │
   │  endian flip)│ │  no conversion) │ │  walk)      │  │ group            │
   └───────┬────┘ └────────┬───────┘ └───┬────────┘  └────────────────┘
           │               │             │
     ┌─────▼───────────────▼─────────────▼─────┐
     │   ExecutionResult / Snapshot              │  (canonical forms
     │   (big-endian, one gate vocabulary,       │   one gate name
     │    CONVENTIONS.md)                        │   per gate)
     └───────────────────────────────────────────┘

   ┌───────────────────────────────────────────────┐
   │  qlens.conformance                              │
   │  neutral gate programs + reference simulator    │
   │  (pure numpy, the executable spec) →            │
   │  run_conformance(backend) certifies any backend │
   └───────────────────────────────────────────────┘
```

## Component contracts

**Public API (`qlens/__init__.py`).** `run()` resolves a backend (by name, or by detection) and returns an `ExecutionResult`. The `assert_*` functions detect the backend from the circuit object and raise `QlensAssertionError` (an `AssertionError` subclass) on failure.

**Execution result (`_execution.py`).** The `ExecutionResult`, `Snapshot`, and `Measurement` dataclasses every backend fills in. Public, semver-governed forms in canonical conventions; counts stay lazy behind a closure so a structural inspection never pays the sampling cost.

**Errors (`_errors.py`).** The exception hierarchy under one `QlensError` base: `QlensAssertionError` (an `AssertionError` subclass, so pytest treats a failed assertion natively), `UnsupportedCircuitError`, and the backend-resolution errors `BackendNotFoundError` and `BackendNotInstalledError`.

**Pytest plugin (`pytest_plugin.py`).** Registers under pytest's `pytest11` group on install: the `qlens` marker, `assert_*` fixtures, per-test trace finalization, and the `--qlens-cov` gate-coverage flag, so a project's test run picks these up with no conftest wiring.

**Registry (`backends/_registry.py`).** Discovers backends exclusively through the `qlens.backends` entry-point group; the first-party backends register in qlens's own pyproject.toml through that group. Detection polls each backend's `handles()` classmethod, which identifies circuit types by module-name inspection without importing the framework. Backends load lazily and are cached per process.

**Backend contract (`backends/base.py`).** The public, semver-governed ABC: `run`, `operator_matrix`, `is_unitary`, `equivalent`, `counts`, plus `name` and `handles()`. Semantic requirements live in CONVENTIONS.md; every output crossing a backend boundary is in canonical form.

**Measurement capture.** Each backend records the measurements a circuit carries onto `ExecutionResult.measurements` as `Measurement(after, qubits)`, `after` being the gate count before it. Capture stays pure unitary evolution: the measurement is a structural marker, not a state change, so the snapshot stream never collapses and stays deterministic. The gate-position counter increments only on gates, so a measurement between gates leaves the gate positions contiguous. `operator_matrix` still refuses a measuring circuit, since it has no unitary. Qiskit reads `measure` instructions, Cirq reads measurement gates, PennyLane reads mid-circuit `MidMeasureMP` (its terminal return measurement stays ignored, as before); `reset` and classical feed-forward remain unsupported.

**QiskitBackend.** Walks `circuit.data` evolving a `qiskit.quantum_info.Statevector` gate by gate (no Aer dependency), takes matrices from `quantum_info.Operator`, samples through `qiskit.primitives.StatevectorSampler`. Converts everything from Qiskit's little-endian conventions at the boundary: bitstrings reverse, statevectors and matrices permute by reversing qubit axis order.

**PennyLaneBackend.** Builds the QNode's tape via `pennylane.workflow.construct_tape`, interleaves `qml.Snapshot()` markers after every operation (with leading identities so the device allocates all wires in canonical order), and executes once through the `qml.snapshots` transform on `default.qubit`. Matrices come from `qml.matrix` with an explicit wire order; counts execute a fresh tape measuring all wires. PennyLane's native conventions match the canonical form, so no reordering happens.

**CirqBackend.** Applies each operation's unitary onto a running state tensor through `cirq.apply_unitary`, which keeps capture linear in gate count where simulating a growing prefix per gate would be quadratic. Matrices come from `Circuit.unitary` with an explicit qubit order and terminal measurements no longer ignored, so a measured circuit raises here as it does on the other backends. Cirq's conventions already match the canonical form, so no reordering happens. Qubit count follows Cirq's own model: a circuit has the qubits its operations touch, and an idle qubit needs an explicit `cirq.I` to take an axis.

**Gate vocabulary (`_gates.py`).** The frameworks spell the same gate three ways (`cx` / `CNOT` / `CNOT`, `h` / `Hadamard` / `H`), and absorbing that's a backend's job rather than a caller's. Each backend normalizes at its own boundary through one alias map held as data, so supporting a new framework's spellings is an entry there rather than a branch in the backend. The framework's own name survives on `Snapshot.native_gate`, and a gate outside the vocabulary passes through lowercased rather than being forced into a canonical name it doesn't have.

**Statistics (`_stats.py`).** Framework-neutral: chi-square and KS wrappers over scipy, unitarity deviation, the phase-invariant matrix comparison shared by backends that lack a native up-to-phase equivalence check, and the bipartite split behind the separability assertions. That split reshapes a statevector into one axis per qubit, permutes the named qubits to the front, and takes the singular values of the resulting matrix; their squares are the reduced state's eigenvalues, so purity falls out without building a density matrix. Subsystems need not be contiguous, since an ancilla is rarely at the end of a register.

**Conformance (`conformance/`).** Canonical circuits expressed as neutral gate programs, with expected results computed by a bundled pure-numpy reference simulator written directly in the canonical conventions. `run_conformance(backend)` checks snapshots, final states, operator matrices, unitarity, sampled distributions, and equivalence verdicts. First-party backends certify through this same public path in the test suite; a third-party backend supplies one interpreter function from the neutral vocabulary to its own circuit type.

## Execution flow, one test

1. Test calls `qlens.run(circuit)`.
2. Registry polls `handles()` across registered backends; the match loads.
3. Backend captures a per-gate statevector walk into `Snapshot` objects, converting to canonical form at its boundary.
4. `ExecutionResult` returns; counts are a lazy callback into the backend, cached per shot count.
5. `assert_distribution(result, expected)` draws counts, runs the chi-square test, and raises `QlensAssertionError` if the p-value falls below the significance level.

## Phase 2 components

```
   qlens.run(circuit, trace=True)
            │
   ┌────────▼─────────┐        ┌───────────────────┐
   │  tracing adapter   │──────▶│ TraceAct sinks      │  (JSONL / SQLite,
   │  (layer grouping,  │        │ (user-configured)   │   TraceAct's config)
   │   computed budget) │        └─────────┬─────────┘
   └────────┬─────────┘                    │
            │ spools arrays        ┌───────▼─────────┐     ┌─────────────────┐
   ┌────────▼─────────┐          │  qlens view        │────▶│ browser page     │
   │ .npz sidecars      │◀────────│  (stdlib server:   │     │ (canvas surfaces,│
   │ (<state_dir>/       │  reads  │   JSON API + SSE,  │     │  ES modules,     │
   │  <trace_id>.npz)     │          │   grid reduction)  │     │  no build step)  │
   └────────┬─────────┘          └───────────────────┘     └─────────────────┘
            │
   ┌────────▼─────────┐
   │ Inspector           │   qlens.inspect(result)  · live results
   │ (cursor, diff)      │   Inspector.from_trace() · stored traces
   └───────────────────┘
```

**Tracing adapter (`tracing/`).** Emits one TraceAct trace per run through the public API only (`ActionTrace.start`, `trace.event`), modelled on TraceAct's LangChain adapter: traces start without entering the ambient context, close via direct `__exit__`, and any recording failure leaves the run's result intact. Gate events group by qubit-disjoint layers (`_layers.py`) by default; per-gate granularity is `trace="gates"`. Event budgets compute from the circuit with a 1000-event floor. Assertion events append to the still-open trace until the pytest plugin, `finish_traces()`, or interpreter exit closes it.

**Sidecar spool (`tracing/_spool.py`).** Amplitude arrays never enter trace records (TraceAct's payload budget would truncate them); every snapshot spools to a compressed `.npz` keyed by gate position, and events carry `statevector_ref` strings. `load_snapshots()` rebuilds a full snapshot list from a stored record plus sidecar.

**Viewer server (`viewer/server.py`).** Stdlib `ThreadingHTTPServer` over a TraceAct source, read through `TraceLog` (which handles JSONL, folders, SQLite, and in-flight stub dedup). JSON endpoints for run lists, circuit structure, per-position amplitudes, the waterfall grid, and an SSE stream that emits run summaries as they arrive or change.

**Waterfall reduction (`viewer/_waterfall.py`).** The division of labour between server and browser. A 10-qubit, 400-gate run is 400k complex amplitudes; sending that as JSON isn't an option, so the reduction runs here in numpy and the payload is two base64 `uint8` planes at display resolution. Magnitude is normalized against a high percentile rather than the maximum (position 0 is a basis state at magnitude 1 and would otherwise set the scale for the whole run) and pre-warped before quantizing, since a linear 8-bit ramp puts an amplitude field almost entirely in the bottom bucket. Row banding keeps each band's largest-magnitude row, carrying that row's phase with it. Unpacked grids memoise on `(path, mtime)`, which is what makes scrubbing, threshold changes, and zooming cheap; `/api/state` reads exact amplitudes from the same cache.

A viewport (`pos_from`/`pos_to`, `row_from`/`row_to`) slices that cached grid rather than re-reading the sidecar. Row banding isn't a mode: it applies only while the requested row span still exceeds the display height, so zooming far enough stops it by itself and each row becomes one basis state. Brightness stays scaled against the whole run, so two zoom levels of one run are comparable. A cell ceiling (`--max-cells`) bounds the payload, costs rows rather than positions when it bites, and is reported rather than applied silently.

**Viewer frontend (`viewer/static/`).** Seven ES modules served as-is: no bundler, no framework, no external requests. `draw.js` owns the canvas surfaces (waterfall, probability bars, delta bars) and the OKLCH-to-sRGB colour table the design tokens are authored in; `ui.js` is element construction and the small components; `logic.js` holds the decisions about recorded data that carry no DOM, so they can be tested without a browser (ordering the assertion table, ranking which recorded expectation a statevector is measured against, expanding a sparse expectation onto the basis, labelling a gate and resolving what else runs in its layer); `copy.js` holds every explanatory string in both a plain-language and an expert register; `guide.js` is the reading guide, the reliability notice, and the settings panel; `debug.js` is a bounded ring every interaction handler records into, reachable from the console as `qlens.debug()`; `app.js` is state, layout, and fetching. Canvas rather than SVG at every size, because the waterfall's whole point is staying readable at full resolution and a 400k-cell field isn't 400k DOM nodes.

One rule holds the interaction layer together: a pointer gesture never rebuilds the surface it's bound to. Scrubbing updates the existing elements in place and renders once when the gesture settles, because a render inside a handler detaches the canvas, and every listener that runs after it in the same dispatch then measures an element with no size. Three defects traced back to that, which is also why every handler records into `debug.js` rather than being reasoned about.

The two typefaces ship in `viewer/static/fonts/` (both SIL OFL 1.1) and are served from the package, so the viewer renders identically on a machine that has never installed them.

**Sample runs (`viewer/_demo.py`).** `qlens view --demo` generates sample runs on the bundled reference simulator and records them through the ordinary path, so the demo needs no provider framework installed and shows what an ordinary test produces.

**Settings and reliability (`_config.py`, `_reliability.py`).** A test method is chosen by the caller, never by Qlens. `_config` resolves the defaults from `[tool.qlens]` in the nearest pyproject.toml, validated at the point they're set rather than at assertion time, and records the effective values onto every traced run. `_reliability` decides whether the chosen method's assumptions hold for the data it was handed and builds one verdict string used by the warning, the trace event, and the viewer alike, so all three say the same thing.

**Inspector (`_inspect.py`).** A cursor over captured snapshots: stepping is list indexing, never re-execution. Works identically over a live `ExecutionResult` and a stored trace record resolved through the sidecar.

## Mutation engine

```
   qlens.mutate(circuit, check)
            │
   ┌────────▼─────────────────────────┐
   │  run(circuit) → canonical op list│
   └────────┬─────────────────────────┘
            │
   ┌────────▼─────────────────────────┐
   │  _mutations: four operators over │
   │  the captured op list            │
   └────────┬─────────────────────────┘
            │  each mutant
   ┌────────▼─────────────────────────┐
   │  _simulate: replay each mutant   │
   │  → statevector and unitary       │
   └────────┬─────────────────────────┘
            │
   ┌────────▼─────────────────────────┐
   │  equivalent? unitary == original │
   │  up to global phase              │
   │  yes → set aside, not scored     │
   │  no  → check(result) kills or    │
   │  lets the mutant survive         │
   └────────┬─────────────────────────┘
            │
   ┌────────▼─────────────────────────┐
   │  MutationReport:                 │
   │  score, survivors, equivalents   │
   └──────────────────────────────────┘
```

**Mutation engine (`_mutate.py`, `_mutations.py`, `_simulate.py`).** `qlens.mutate` mutation-tests a circuit against its own checks. The four operators in `_mutations.py` map one-to-one onto the bug-pattern catalog (reversed control/target, same-shape gate substitution, injected phase, deleted gate) and each returns a family of mutant op lists. A mutant is replayed on `_simulate.py`, a pure-numpy statevector simulator over the canonical gate vocabulary, rather than on the framework that built the circuit; that is why one path mutates all three backends, including the PennyLane circuits that are Python functions with no editable gate list. `_simulate` is deliberately separate from the conformance reference simulator, which stays an independent oracle so a shared bug can't hide from certification; a test replays every backend gate through `_simulate` and checks the state matches gate for gate. Equivalent mutants are found by comparing the mutant's unitary against the original's up to global phase and excluded from the score, a distinction the simulator can draw and hardware cannot.

**Gate coverage (`coverage.py`).** A session accumulates two sets of gate positions per circuit: the positions any `run` executed, and the positions any `assert_*` validated. Both hook the same seams the tracer uses: `run` calls `coverage.record_run`, and the assertion `_record` seam calls `coverage.record_assertion` with the position's `at=`. Recording is active only inside a `coverage.session()` and never raises, so it costs nothing and breaks nothing when off. The denominator is the observed gate set unless `declare` pins a reference circuit, which is what lets run coverage fall below 100% for a branch a suite never reaches. The pytest plugin opens one session under `--qlens-cov` and prints the report at the terminal summary.

## Tests

The Python suite runs under `pytest`, with order randomization on:

```bash
python -m pytest tests/
```

The viewer's own logic runs under Node's built-in test runner, which needs
no packages, no `package.json`, and no build step:

```bash
node --test tests/js/*.test.js
```

Both run in CI. The split follows what each can reach: `logic.js`,
`draw.js`, and `ui.js` hold arithmetic and formatting that Node covers
directly, while anything depending on measured layout is verified against
a running viewer.

## STRuFO

A five-part orientation to the system: **S**hape, **T**echnical stack,
**Ru**n details, **F**ailure modes, **O**bservability.

### Shape

Qlens is a simulator-first testing, debugging, and observability SDK for
quantum programs: one pytest-native assertion API and one local viewer over
Qiskit, PennyLane, and Cirq, built on instrumented execution that captures
the full statevector after every gate. You write ordinary tests that check
what the quantum state does, not only what the final measurement looks like.

### Technical stack

- **Language:** Python 3.11+, fully typed under `mypy --strict` with `ruff`.
  The viewer's frontend is vanilla JavaScript with no framework, tested on
  Node's built-in runner.
- **Core dependencies:** `numpy` (statevectors, linear algebra), `scipy`
  (chi-square, KS), `traceact >=0.14` (trace recording, itself
  zero-runtime-dependency).
- **Backends as optional extras:** `qiskit`, `pennylane`, `cirq`. Each
  registers through a public entry-point contract certified against a
  shipped conformance suite; none is a hard dependency, and a fourth
  framework plugs in as a separate package.
- **Storage:** compressed `.npz` sidecars for statevector arrays, JSONL
  trace records via TraceAct. No database.
- **Surfaces:** a bundled pytest plugin, a `qlens view` CLI (stdlib
  `http.server`, no build step), and `[tool.qlens]` settings read from
  `pyproject.toml`.

### Run details, simple English

You hand Qlens a quantum circuit and it runs it on a simulator, taking a
photograph of the entire quantum state after every single gate. Then you
write normal pytest tests that ask questions of those photographs: does the
output match the distribution I expected, is this the exact state I meant to
build, did I accidentally leave a scratch qubit tangled up with my data. The
subtle part is that measurement hides bugs. Two quantum states can measure
identically and still be different, so a test that only checks the final
counts is not a full test of a quantum program. Qlens looks underneath. If a
test fails, a local viewer lets you scrub through the run gate by gate and
watch where the state went wrong. The same test works whether you wrote the
circuit in Qiskit, PennyLane, or Cirq, because Qlens converts all three to
one convention at the door.

### Run details, technical

`qlens.run(circuit)` detects the backend from the circuit's object type (or
an explicit `backend=`). The backend binds any parameters, then walks the
circuit gate by gate, evolving a statevector and converting it to Qlens's
canonical big-endian convention at its own boundary. Each gate becomes a
frozen `Snapshot`: position, one canonical lowercase gate name shared across
every backend, the framework's native name, the qubit indices, the numeric
params, and the full statevector after that gate. Measurements are recorded
structurally onto `ExecutionResult.measurements` without collapsing the
state, so capture stays pure unitary evolution. Sampled counts stay lazy
behind a closure, so a purely structural inspection never pays the sampling
cost.

The returned `ExecutionResult` is what the assertions consume.
`assert_distribution` draws counts and runs the caller's chosen test
(chi-square, an exact simulated p-value, total variation distance, or KS).
`assert_state` compares by fidelity up to global phase. `assert_separable`
and `assert_entangled` reduce a named subsystem to its purity through
Schmidt values, catching the un-uncomputed ancilla no distribution check can
see. Every assertion funnels through one `_record` seam that feeds two
consumers, the tracer and the coverage session. With `trace=True` the run
spools snapshot arrays to `.npz` and emits gate, qstate, and assertion
events through TraceAct under a per-run event budget. If a coverage session
is open, the run records which gate positions executed and which positions
an assertion validated. Project defaults resolve once from `[tool.qlens]`
and are stamped onto every traced run.

### Failure modes

Failures are typed and named per cause, and nothing changes your test method
behind your back.

- **Non-unitary instructions:** `reset`, `initialize`, and classical
  feed-forward raise `UnsupportedCircuitError`; Qlens captures pure
  statevector evolution. Measurement is the deliberate exception, captured
  as a structural marker rather than refused.
- **Unbound parameters** raise with the count and the fix (pass values via
  `args=`).
- **Backend resolution:** `BackendNotFoundError` for an unknown name,
  `BackendNotInstalledError` for a registered backend whose provider is not
  installed.
- **Assertion failure** raises `QlensAssertionError`, an `AssertionError`
  subclass, so pytest treats it natively, carrying the measured numbers in
  the message.
- **Statistical unreliability:** when a chosen test's assumptions do not
  hold (a sparse chi-square, a tvd tolerance below the sampling noise
  floor), Qlens builds one verdict and routes it through
  `on_unreliable_statistics` (warn, raise, or ignore) as a
  `QlensStatisticsWarning`. It names the alternatives rather than switching
  methods silently.
- **Bookkeeping never breaks a run:** tracing and coverage recording swallow
  their own exceptions, so a failing sink or hook cannot touch the test
  result.
- **Mutation testing** refuses a gate outside its canonical simulator's
  vocabulary rather than mutating around it.

### Observability

- **Traces:** every run can record as a TraceAct trace correlated by run id:
  one gate event per circuit layer (or per gate), a final qstate event, and
  one assertion event per `assert_*` call, all under a per-run event budget
  computed from the circuit, so `budget_hit` becomes a meaningful anomaly
  signal instead of an expected artifact. Heavy statevector arrays spool to
  `.npz` sidecars; events carry references, not the arrays.
- **The viewer (`qlens view`):** an amplitude waterfall across every gate
  position, the statevector at any point against what a test expected, an
  A/B diff between two positions, clickable assertion pass/fail markers, and
  a built-in reading guide for people new to quantum computing. Live runs
  stream in over SSE.
- **Post-hoc metrics at zero simulator cost:** gate coverage (which
  positions ran, which an assertion checked, via `pytest --qlens-cov`) and a
  mutation score (which injected bugs the tests caught) are computed from
  recorded data after the fact.
- **One verdict, three surfaces:** the reliability verdict is computed once
  and shown identically in the warning, the trace event, and the viewer, so
  all three tell the same story.

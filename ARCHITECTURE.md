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
        │  assert_equivalent()            │
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
     │   ExecutionResult / Snapshot              │  (canonical shapes
     │   (big-endian, one gate vocabulary,       │   and one gate name
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

**Registry (`backends/_registry.py`).** Discovers backends exclusively through the `qlens.backends` entry-point group; the first-party backends register in qlens's own pyproject.toml through that group. Detection polls each backend's `handles()` classmethod, which identifies circuit types by module-name inspection without importing the framework. Backends load lazily and are cached per process.

**Backend contract (`backends/base.py`).** The public, semver-governed ABC: `run`, `operator_matrix`, `is_unitary`, `equivalent`, `counts`, plus `name` and `handles()`. Semantic requirements live in CONVENTIONS.md; every output crossing a backend boundary is in canonical form.

**QiskitBackend.** Walks `circuit.data` evolving a `qiskit.quantum_info.Statevector` gate by gate (no Aer dependency), takes matrices from `quantum_info.Operator`, samples through `qiskit.primitives.StatevectorSampler`. Converts everything from Qiskit's little-endian conventions at the boundary: bitstrings reverse, statevectors and matrices permute by reversing qubit axis order.

**PennyLaneBackend.** Builds the QNode's tape via `pennylane.workflow.construct_tape`, interleaves `qml.Snapshot()` markers after every operation (with leading identities so the device allocates all wires in canonical order), and executes once through the `qml.snapshots` transform on `default.qubit`. Matrices come from `qml.matrix` with an explicit wire order; counts execute a fresh tape measuring all wires. PennyLane's native conventions match the canonical form, so no reordering happens.

**CirqBackend.** Applies each operation's unitary onto a running state tensor through `cirq.apply_unitary`, which keeps capture linear in gate count where simulating a growing prefix per gate would be quadratic. Matrices come from `Circuit.unitary` with an explicit qubit order and terminal measurements no longer ignored, so a measured circuit raises here as it does on the other backends. Cirq's conventions already match the canonical form, so no reordering happens. Qubit count follows Cirq's own model: a circuit has the qubits its operations touch, and an idle qubit needs an explicit `cirq.I` to take an axis.

**Gate vocabulary (`_gates.py`).** The frameworks spell the same gate three ways (`cx` / `CNOT` / `CNOT`, `h` / `Hadamard` / `H`), and absorbing that's a backend's job rather than a caller's. Each backend normalizes at its own boundary through one alias map held as data, so supporting a new framework's spellings is an entry there rather than a branch in the backend. The framework's own name survives on `Snapshot.native_gate`, and a gate outside the vocabulary passes through lowercased rather than being forced into a canonical name it doesn't have.

**Statistics (`_stats.py`).** Framework-neutral: chi-square and KS wrappers over scipy, unitarity deviation, and the phase-invariant matrix comparison shared by backends that lack a native up-to-phase equivalence check.

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
   │ Inspector           │   qlens.inspect(result)  — live results
   │ (cursor, diff)      │   Inspector.from_trace() — stored traces
   └───────────────────┘
```

**Tracing adapter (`tracing/`).** Emits one TraceAct trace per run through the public API only (`ActionTrace.start`, `trace.event`), modelled on TraceAct's LangChain adapter: traces start without entering the ambient context, close via direct `__exit__`, and any recording failure leaves the run's result intact. Gate events group by qubit-disjoint layers (`_layers.py`) by default; per-gate granularity is `trace="gates"`. Event budgets compute from the circuit with a 1000-event floor. Assertion events append to the still-open trace until the pytest plugin, `finish_traces()`, or interpreter exit closes it.

**Sidecar spool (`tracing/_spool.py`).** Amplitude arrays never enter trace records (TraceAct's payload budget would truncate them); every snapshot spools to a compressed `.npz` keyed by gate position, and events carry `statevector_ref` strings. `load_snapshots()` rebuilds a full snapshot list from a stored record plus sidecar.

**Viewer server (`viewer/server.py`).** Stdlib `ThreadingHTTPServer` over a TraceAct source, read through `TraceLog` (which handles JSONL, folders, SQLite, and in-flight stub dedup). JSON endpoints for run lists, circuit structure, per-position amplitudes, the waterfall grid, and an SSE stream that emits run summaries as they land or change.

**Waterfall reduction (`viewer/_waterfall.py`).** The division of labour between server and browser. A 10-qubit, 400-gate run is 400k complex amplitudes; sending that as JSON isn't an option, so the reduction runs here in numpy and the payload is two base64 `uint8` planes at display resolution. Magnitude is normalized against a high percentile rather than the maximum (position 0 is a basis state at magnitude 1 and would otherwise set the scale for the whole run) and pre-warped before quantizing, since a linear 8-bit ramp puts an amplitude field almost entirely in the bottom bucket. Row banding keeps each band's largest-magnitude row, carrying that row's phase with it. Unpacked grids memoise on `(path, mtime)`, which is what makes scrubbing, threshold changes, and zooming cheap; `/api/state` reads exact amplitudes from the same cache.

A viewport (`pos_from`/`pos_to`, `row_from`/`row_to`) slices that cached grid rather than re-reading the sidecar. Row banding isn't a mode: it applies only while the requested row span still exceeds the display height, so zooming far enough stops it by itself and each row becomes one basis state. Brightness stays scaled against the whole run, so two zoom levels of one run are comparable. A cell ceiling (`--max-cells`) bounds the payload, costs rows rather than positions when it bites, and is reported rather than applied silently.

**Viewer frontend (`viewer/static/`).** Seven ES modules served as-is: no bundler, no framework, no external requests. `draw.js` owns the canvas surfaces (waterfall, probability bars, delta bars) and the OKLCH-to-sRGB colour table the design tokens are authored in; `ui.js` is element construction and the small components; `logic.js` holds the decisions about recorded data that carry no DOM, so they can be tested without a browser (ordering the assertion table, ranking which recorded expectation a statevector is measured against, expanding a sparse expectation onto the basis, labelling a gate and resolving what else runs in its layer); `copy.js` holds every explanatory string in both a plain-language and an expert register; `guide.js` is the reading guide, the reliability notice, and the settings panel; `debug.js` is a bounded ring every interaction handler records into, reachable from the console as `qlens.debug()`; `app.js` is state, layout, and fetching. Canvas rather than SVG at every size, because the waterfall's whole point is staying readable at full resolution and a 400k-cell field isn't 400k DOM nodes.

One rule holds the interaction layer together: a pointer gesture never rebuilds the surface it's bound to. Scrubbing updates the existing elements in place and renders once when the gesture settles, because a render inside a handler detaches the canvas, and every listener that runs after it in the same dispatch then measures an element with no size. Three defects traced back to that, which is also why every handler records into `debug.js` rather than being reasoned about.

The two typefaces ship in `viewer/static/fonts/` (both SIL OFL 1.1) and are served from the package, so the viewer renders identically on a machine that has never installed them.

**Sample runs (`viewer/_demo.py`).** `qlens view --demo` generates sample runs on the bundled reference simulator and records them through the ordinary path, so the demo needs no provider framework installed and shows exactly what an ordinary test produces.

**Settings and reliability (`_config.py`, `_reliability.py`).** A test method is chosen by the caller, never by Qlens. `_config` resolves the defaults from `[tool.qlens]` in the nearest pyproject.toml, validated at the point they're set rather than at assertion time, and records the effective values onto every traced run. `_reliability` decides whether the chosen method's assumptions hold for the data it was handed and builds one verdict string used by the warning, the trace event, and the viewer alike, so all three say the same thing.

**Inspector (`_inspect.py`).** A cursor over captured snapshots: stepping is list indexing, never re-execution. Works identically over a live `ExecutionResult` and a stored trace record resolved through the sidecar.

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

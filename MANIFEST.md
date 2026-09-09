# Qlens manifest

Last updated: 2026-09-03 11:29:02 UTC

A per-file map of the codebase: one line per source file, what it defines and
what it touches, so a reader can orient before opening anything.

## Core (`src/qlens/`)

- `__init__.py` — public API: `run()`, the `assert_*` functions, `inspect`, `mutate`, `coverage`, and the exported types; holds `__version__`.
- `_execution.py` — the `ExecutionResult`, `Snapshot`, and `Measurement` dataclasses every backend fills in; lazy counts behind a closure.
- `_errors.py` — the exception taxonomy under one `QlensError` base (`QlensAssertionError`, `UnsupportedCircuitError`, backend-resolution errors).
- `_assertions.py` — the `assert_*` testing API; funnels every assertion through one `_record` seam feeding tracing and coverage.
- `_stats.py` — framework-neutral statistics and linear algebra: chi-square/KS over scipy, unitarity deviation, phase-invariant matrix comparison, the Schmidt split behind separability.
- `_reliability.py` — decides whether a chosen statistical test's assumptions hold and builds the one verdict string used by the warning, trace event, and viewer.
- `_config.py` — project settings resolved from `[tool.qlens]` in the nearest `pyproject.toml` (reads the filesystem); validated when set.
- `_gates.py` — one canonical gate vocabulary; per-backend alias maps held as data, framework names kept on `Snapshot.native_gate`.
- `_inspect.py` — the `inspect` API: a cursor over captured snapshots (step, diff, probabilities), no re-execution; also rebuilds from a stored trace.
- `_layers.py` — partitions a gate sequence into qubit-disjoint layers for per-layer trace capture (pure, no framework).
- `_simulate.py` — a canonical pure-numpy statevector simulator over Qlens's gate vocabulary; the replay engine behind mutation.
- `_mutations.py` — the four mutation operators (reversed control/target, gate substitution, injected phase, deleted gate) over a canonical op list.
- `_mutate.py` — `qlens.mutate`: mutation-tests a circuit against its own checks, replays mutants on `_simulate`, discards equivalents by unitary comparison.
- `coverage.py` — gate coverage: a session recording which gate positions ran and which an assertion checked; coverage.py-style report; `qlens.coverage` API.
- `pytest_plugin.py` — bundled pytest plugin (registers under `pytest11`): the `qlens` marker, `assert_*` fixtures, trace finalization, the `--qlens-cov` flag.

## Backends (`src/qlens/backends/`)

- `__init__.py` — re-exports the public backend contract and registry.
- `base.py` — the semver-governed `Backend` ABC (`run`, `operator_matrix`, `is_unitary`, `equivalent`, `counts`, `name`, `handles()`).
- `_registry.py` — backend discovery through the `qlens.backends` entry-point group, lazy load, detection by `handles()`.
- `_qiskit.py` — Qiskit backend; walks `circuit.data` via `quantum_info.Statevector`, converts little-endian to canonical. Imports `qiskit`.
- `_pennylane.py` — PennyLane backend; rewrites the QNode tape with `qml.Snapshot` markers on `default.qubit`. Imports `pennylane`.
- `_cirq.py` — Cirq backend; applies unitaries onto a running state tensor via `cirq.apply_unitary`. Imports `cirq`.

## Conformance (`src/qlens/conformance/`)

- `__init__.py` — `run_conformance(backend)`: checks snapshots, states, matrices, unitarity, distributions, and equivalence.
- `_circuits.py` — canonical conformance circuits as neutral gate programs.
- `_builders.py` — first-party interpreters from the neutral vocabulary to concrete Qiskit/PennyLane/Cirq circuits.
- `_reference.py` — an independent pure-numpy reference simulator, the executable ground truth for CONVENTIONS.md (kept separate from `_simulate`).

## Tracing (`src/qlens/tracing/`)

- `__init__.py` — TraceAct integration: module-level settings, `record_run`, the assertion-recording seam; opens/closes per-run traces.
- `_adapter.py` — emits one TraceAct trace per run: gate/qstate/assertion events under a per-run event budget. Writes JSONL through TraceAct.
- `_spool.py` — statevector sidecar spooling: writes/reads compressed `.npz` files, parses `statevector_ref` strings. Touches the filesystem.

## Viewer (`src/qlens/viewer/`)

- `__init__.py` — viewer package initializer.
- `cli.py` — the `qlens` command line (`qlens view`, `--demo`); starts the server.
- `server.py` — the viewer server: stdlib `ThreadingHTTPServer` with JSON and SSE endpoints over a TraceAct source. Serves HTTP on localhost, reads trace JSONL and sidecars.
- `_waterfall.py` — server-side reduction of a run's spooled statevectors into base64 display planes; memoised on `(path, mtime)`.
- `_demo.py` — sample runs for `qlens view --demo`, recorded through the ordinary path on the reference simulator.

## Viewer frontend (`src/qlens/viewer/static/`)

- `index.html` — the viewer's single-page HTML shell.
- `styles.css` — viewer styles.
- `app.js` — viewer entry: wiring, state, and data transport (fetch + SSE) in the browser.
- `logic.js` — pure decisions about recorded data, no DOM (unit-tested by `tests/js/logic.test.js`).
- `draw.js` — canvas surfaces: the waterfall heatmap, amplitude bars, delta bars (unit-tested by `tests/js/draw.test.js`).
- `ui.js` — element construction and the small components the panels are built from (unit-tested by `tests/js/ui.test.js`).
- `guide.js` — the reading guide, reliability notice, and settings panel.
- `copy.js` — every explanatory string in the viewer, in two registers.
- `debug.js` — a recorder for what the viewer did, for diagnostics.

## Tooling (`scripts/`)

- `keycall_preflight.py` — validates the audit keys and confirms the primary model through KeyCall before the billable shiplock audit runs; reads `AUDIT_API_KEY`/`AUDIT_FALLBACK_API_KEY` (provider/key) from the environment, exits nonzero on a bad key or missing model. Imports `keycall`, makes a model-list call per provider.

## Tests (`tests/`)

- `conftest.py` — shared fixtures: paired circuit builders across backends; enables `pytester`.
- `test_execution.py` — `qlens.run`: snapshot capture, canonical ordering, lazy counts.
- `test_assertions.py` — `assert_unitary`, `assert_equivalent`, `assert_distribution`: failure paths first.
- `test_positional_assertions.py` — assertions that name a position in the run (`at=`).
- `test_separability.py` — separability maths, then the `assert_separable`/`assert_entangled` assertions.
- `test_statistics.py` — the distribution tests and their reliability checks.
- `test_config.py` — project settings: validation, loading, precedence.
- `test_gate_names.py` — one gate vocabulary across every backend.
- `test_registry.py` — backend discovery, dispatch, detection failure modes.
- `test_cirq_backend.py` — Cirq backend behaviour beyond conformance.
- `test_conformance.py` — first-party backends certify through the public conformance path.
- `test_simulate.py` — the canonical simulator, cross-checked against the real backends.
- `test_measurements.py` — structural measurement capture across the three backends.
- `test_mutate.py` — mutation operators, scoring, and equivalent-discard.
- `test_coverage.py` — gate coverage: recording, denominators, report, the pytest flag.
- `test_inspect.py` — Inspector boundary and failure paths, then the debugging flow.
- `test_layers.py` — layer grouping, adversarial orderings first.
- `test_tracing.py` — tracing round-trips against real TraceAct sinks.
- `test_spool.py` — sidecar spooling: malformed refs and missing files first.
- `test_viewer.py` — viewer server over real HTTP against a live server.
- `test_waterfall.py` — waterfall reduction: degenerate and hostile inputs first.
- `test_cli.py` — the `qlens` command line, argument handling.
- `test_demo.py` — the bundled sample runs.
- `test_pytest_plugin.py` — the bundled pytest plugin, exercised through real pytest runs.
- `test_bug_patterns.py` — the four bug patterns Qlens claims to catch, each reproduced and caught.
- `test_assertion_source.py` — where an assertion event says it came from.
- `test_quickstart.py` — USAGE.md's quickstart code, executed as written.
- `test_docs.py` — docs checked against current behaviour.
- `test_shiplock.py` — the shiplock docs-vs-code gate, run inside the suite.
- `js/logic.test.js` — the viewer's decisions about recorded data.
- `js/draw.test.js` — colour mapping and pointer arithmetic from `draw.js`.
- `js/ui.test.js` — number and label formatting from `ui.js`.

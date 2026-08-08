# Changelog

## 0.2.0 — 2026-08-08

Phase 2 groundwork: trace recording, step-through inspection, and the viewer server. The designed viewer UI ships separately; this release carries the full data and API layer it renders.

### Added

- `qlens.run(circuit, trace=True)` records the execution as a TraceAct trace: `gate` events per qubit-disjoint circuit layer, a final `qstate` snapshot event, and `assertion` events appended by any `assert_*` call against the traced result. `trace="gates"` records per-gate events and snapshots instead.
- Statevector sidecar spooling: amplitude arrays write to `<state_dir>/<trace_id>.npz` and trace events carry `statevector_ref` strings; both capture modes spool every position.
- Per-run event budgets computed from the circuit, with a 1000-event floor (`qlens.tracing.configure(max_events=...)`); a thousand-gate circuit stays under budget in layer mode.
- `qlens.tracing.configure(state_dir=..., project=..., correlation_id=...)` for spool location and experiment grouping; `finish_traces()` closes open run traces, and the pytest plugin closes them automatically at each test's end.
- `qlens.inspect(result)`: cursor-based step-through over captured snapshots (`step`, `step_back`, `goto`, `probabilities`, `diff` with fidelity and per-basis-state amplitude deltas), plus `Inspector.from_trace(record, state_dir)` for stored traces. No re-execution anywhere.
- `qlens view <source>`: a local viewer server over TraceAct trace sources with a JSON API (`/api/circuits`, `/api/circuit`, `/api/state`, `/api/stream` Server-Sent Events for live sessions) and a placeholder page exercising all endpoints.
- Layer grouping (`gates grouped greedily by qubit-disjointness`) as the default trace granularity.

### Changed

- `traceact>=0.14` is now a required dependency: the trace layer and viewer are core infrastructure.

## 0.1.0 — 2026-08-08

Initial release: Phase 1 (instrumented execution + testing assertions).

### Added

- `qlens.run(circuit)`: instrumented execution with a statevector snapshot after every gate, for Qiskit `QuantumCircuit` and PennyLane `QNode` objects. Backend auto-detected from the circuit type. Parameterized circuits bind through `args=(...)`.
- `qlens.assert_distribution(result, expected)`: chi-square (discrete counts) and KS (continuous samples) validation of sampled output against an expected distribution, with seedable sampling for reproducible CI runs.
- `qlens.assert_unitary(circuit)`: unitarity check within numerical tolerance.
- `qlens.assert_equivalent(circuit_a, circuit_b)`: same-unitary check up to global phase.
- Bundled pytest plugin (`pytest11` entry point): `qlens_run`, `assert_distribution`, `assert_unitary`, `assert_equivalent` fixtures and the `qlens` marker.
- Public backend contract (`qlens.backends.Backend`) with entry-point discovery under the `qlens.backends` group; first-party backends register through the same mechanism available to third-party packages.
- Canonical semantic conventions (CONVENTIONS.md): big-endian bitstrings and basis ordering on every backend, with conversion at the backend boundary.
- Conformance suite (`qlens.conformance`): 17 canonical circuits plus 5 equivalence pairs with expectations computed by a bundled pure-numpy reference simulator; `run_conformance(backend)` certifies any backend implementation.

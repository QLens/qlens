# Changelog

## 0.3.0 — 2026-08-09

The viewer UI, and the data it needed.

### Added

- The viewer frontend: four views over a recorded run — Timeline (amplitude waterfall over every gate position, with the circuit's wire strip on the same axis and a transport), State (statevector at the cursor with the expected distribution overlaid), Diff (two pinned positions with fidelity and per-basis-state deltas), and Assertions (every check with its metrics, source, and a coverage strip). Keyboard transport, click-to-jump assertion markers, and a collapse control that drops basis states below a threshold. Plain ES modules and canvas; no build step and no external requests.
- `qlens view --demo` generates three sample runs and opens on those, so the viewer has something to show without a project wired up. They execute on the bundled reference simulator and record through the ordinary path, so no provider framework is needed: a dense variational ansatz with a failing check, a sparse-subspace circuit where the collapse control has something to drop, and a GHZ state with phase winding.
- `GET /api/waterfall?trace_id=` returns every captured position at display resolution as two base64 `uint8` planes (magnitude, phase), with `max_rows` and `threshold` parameters. Magnitude normalizes against a high percentile of the field rather than its maximum.
- Assertion events carry `position`, `source` (`file:line` of the call), `details` (the measured statistic, p-value, tolerance, shots, deviation, atol), and `expected` (the reference distribution, normalized). Non-finite metrics record as `null`.
- `assert_unitary` and `assert_equivalent` attach to the open traced run when exactly one is open, so checks made against a circuit rather than a result still appear on the run's timeline.
- `launch.sh`, `launch.command`, and `launch.bat`: create or reuse an environment and start the viewer, falling back to `--demo` when given no source.

### Changed

- `qlens view` takes its source argument optionally; without a source or `--demo` it explains which to pass.
- `GET /api/state` reads through the same in-process grid cache as the waterfall, so scrubbing does not decompress a sidecar per request.

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

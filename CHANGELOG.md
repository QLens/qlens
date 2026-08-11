# Changelog

## 0.5.0 — 2026-08-10

A third backend, one gate vocabulary across all of them, and a waterfall that says what happened where.

### Added

- Cirq backend, registered through the same public entry-point group a third-party backend uses and certified against the shipped conformance suite. `pip install qlens[cirq]`. Capture applies each operation's unitary onto a running state tensor, so a long circuit costs one pass rather than one simulation per gate.
- `Snapshot.native_gate`: what the framework itself called a gate, kept alongside the canonical name so nothing is lost in translation.
- The viewer's typefaces ship inside the package (Space Grotesk and Commit Mono, both SIL OFL 1.1), so it renders as designed on a machine that has never installed them.
- **Open state** on an assertion's row, opening the State tab measured against what that particular check expected.
- A test suite over the viewer's own logic, run by Node's built-in test runner. No packages, no build step, and nothing added to what Qlens installs.
- Hovering the amplitude waterfall or the wire strip names the column: the gate and its parameters, the layer it runs in, the other gates in that layer, and any check recorded there. A rule spans both surfaces so the readout is attributable to a place in the field, which matters when a column is a couple of pixels wide.
- The layer is reported alongside the gate. Gates in one layer share no qubit and so run together, which makes the layer the honest answer to what is active at a point rather than the single gate the cursor landed on.
- Double-clicking a column on the waterfall or the strip opens the State tab on that position. Any expectation pinned from elsewhere in the run is released on the way, since a check from another position has nothing to say about this one.
- Zoom and pan on the waterfall. Scroll to zoom the time axis, shift-scroll for the basis-state axis, shift-drag to frame a region, `+`/`-`/`0` from the keyboard. When a run is taller than the panel the field groups basis states into rows and draws the loudest of each group, so zooming in is what gives a state its own row back. There's no mode for this: rows group only while the range asked for is taller than the panel, and zooming far enough stops it. The panel says `1 row = 4 states` while a row still stands for several, and says which slice of the run is on screen whenever it isn't all of it.
- The field lists its gestures under the transport, so none of them have to be discovered.
- `/api/waterfall` takes a viewport: `pos_from`/`pos_to` and `row_from`/`row_to`, reduced from the grid already in memory rather than re-read from the sidecar. It reports the viewport it served, since a range arriving inverted or past the end of the run is clamped to one that exists.
- `qlens view --max-cells N` bounds how large a single waterfall request may get. Hitting it costs rows rather than positions, and the payload says `capped` rather than quietly returning something coarser than was asked for.
- Every interaction handler in the viewer records what it decided, into a ring readable from the browser console as `qlens.debug()`. Events carry the values a branch tested, not only that it ran. Always on.

### Changed

- `Snapshot.gate` is now one name per gate across every backend: a controlled-NOT reports `cx` whether the framework spelled it `cx` or `CNOT`, and a Hadamard reports `h` whether it was `h`, `Hadamard`, or `H`. A gate outside Qlens's vocabulary keeps the framework's own name rather than being forced into a canonical one it doesn't have. See CONVENTIONS.md for the mapping.
- Gate parameters agree across backends too. Rotations report radians everywhere, and a gate whose name already fixes its rotation reports nothing anywhere, rather than carrying an exponent on the frameworks that model it as a power.
- The State tab's expected overlay prefers a failing check when several apply at one position, and names which one it drew, with a picker when there's a choice. It previously took the first check recorded there, which on a position holding both a passing and a failing check meant every divergence read as zero.
- A position holding more than one check lists all of them, rather than the first recorded.
- The largest-divergence rows break ties on probability, so a check the run agreed with lists its largest outcomes rather than an arbitrary sixteen.
- An assertion with no position sorts to the end of the table in both directions rather than to the top when sorting descending.
- Playback opens at 0.5×, a pace a gate can be read at.
- Static assets are served `no-store` rather than `no-cache`, so a tab left open across a restart can't run the previous version's JavaScript against the new server. Vendored fonts stay cached: a font can't run, so it can't skew.

### Fixed

- A Cirq circuit ending in a measurement raises `UnsupportedCircuitError` from `operator_matrix` as the other backends do. Cirq's own `unitary()` ignores a terminal measurement by default, which would have made `assert_unitary` answer differently depending on the framework.
- A pointer gesture no longer rebuilds the surface it's bound to. Scrubbing updates the existing elements and renders once when the gesture settles; a render inside a handler detached the canvas, and every listener running after it in the same dispatch then measured an element with no size. Double-click on the field never fired for this reason, and a scrub could jump to the end of the run.

## 0.4.0 — 2026-08-10

Assertions that name a point in the run, and a choice of how a distribution is compared.

### Added

- `at=` on `assert_distribution`: check the state captured after a given gate position rather than the circuit's final state. The assertion then marks that position in the viewer's timeline, so checks spread across a run instead of stacking at its end.
- `qlens.assert_state(result, expected, fidelity=0.99, at=None)` compares a captured statevector against an expected one by fidelity, ignoring global phase.
- `ExecutionResult.counts(at=...)` samples the state at any captured position.
- `test="chi_square_exact"` computes the p-value by simulation instead of the asymptotic formula, which holds however rare an outcome is. `test="tvd"` compares by total variation distance, where `tolerance` is a distance rather than a significance level.
- Reliability reporting. Chi-square's p-value assumes every outcome is expected several times over; where that doesn't hold the p-value can be wrong in either direction. Qlens detects the condition, reports it through `on_unreliable_statistics` (`warn`, `error`, or `ignore`), and names the alternatives. It never changes the test method on the caller's behalf. `tvd` is checked the same way against the sampling noise floor at the given shot count.
- Project settings in `pyproject.toml` under `[tool.qlens]` (`distribution_test`, `on_unreliable_statistics`, `min_expected_count`, `resamples`), loaded by the pytest plugin at collection, settable at runtime with `qlens.configure()`, and overridable per call. The settings in force are recorded onto every traced run.
- Assertion events carry `method` and `reliability`; run summaries carry `settings` and `assertions_unreliable`.
- A reading guide in the viewer, written for someone new to quantum computing, reachable from the top bar at any time and from the ⓘ on each panel. A settings panel holds viewer preferences and **Reset dismissed notices**, which brings back the guided tour and anything else clicked away.
- Flagged checks show an `UNRELIABLE` badge in the assertions table, with the explanation and copyable alternatives on the open row.
- `qlens.QlensStatisticsWarning`, and an `assert_state` pytest fixture.
- Two registers for every explanation in the viewer, Simple and Advanced, switchable from the guide header or Settings and persisted across sessions.
- A Reset control on the Diff tab, restoring the comparison to the ends of the run.

### Changed

- The assertions table sorts on any column and its widths are draggable, both persisted. Detail gets the flexible column, so the long text is what grows.
- The failure and unreliable counts in the top bar are buttons, opening the Assertions tab.
- Bars on the State tab report themselves: hovering names the basis state with its observed value, expected value, and divergence, and clicking isolates one bar by dimming the rest. Clicking it again, or switching tab or run, releases it.
- Panel geometry measures a rendered panel rather than deriving from the viewport minus assumed padding, so drawings track their panel through a window resize.
- A run opens at its first gate rather than its last, and the Diff tab opens comparing the two ends of the run rather than a position against itself.
- Playback speeds are 0.25×, 0.5×, 1×, and 2×, defaulting to 1×, paced for following a state as it evolves.
- The reading guide holds a constant size and scrolls internally, rather than resizing to each topic.

### Fixed

- The guided tour rendered as an empty overlay when the viewer opened in a background tab, where `requestAnimationFrame` doesn't fire. Its anchors are now measured synchronously.
- The tour could follow a tab switch and anchor its annotations to whatever canvas was on screen.
- Tour notes anchored to a column near the right edge were pinned against the frame; each now takes whichever side of its anchor has room.
- Playback rebuilt the whole page on every frame, which destroyed the pause button between a click's press and release and reset the page scroll continuously. The transport now updates only the playhead, readout, and bars in place.

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
- `GET /api/state` reads through the same in-process grid cache as the waterfall, so scrubbing doesn't decompress a sidecar per request.

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

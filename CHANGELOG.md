# Changelog

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

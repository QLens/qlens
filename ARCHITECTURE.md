# Qlens Architecture

```
┌──────────────────────────────────────────────────┐
│        User circuits (Qiskit / PennyLane)          │
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
   ┌─────────▼────┐  ┌──────▼─────────┐      ┌──────────────────┐
   │ QiskitBackend  │  │ PennyLaneBackend │  ←──│ third-party        │
   │ (Statevector   │  │ (tape rewrite +  │      │ backends via the   │
   │  .evolve walk, │  │  qml.snapshots,  │      │ same entry-point   │
   │  endian flip)  │  │  no conversion)  │      │ group              │
   └───────┬──────┘  └──────┬─────────┘      └──────────────────┘
           │                │
     ┌─────▼────────────────▼─────┐
     │   ExecutionResult / Snapshot  │   (canonical shapes,
     │   (big-endian, CONVENTIONS.md)│    CONVENTIONS.md)
     └───────────────────────────────┘

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

**Statistics (`_stats.py`).** Framework-neutral: chi-square and KS wrappers over scipy, unitarity deviation, and the phase-invariant matrix comparison shared by backends that lack a native up-to-phase equivalence check.

**Conformance (`conformance/`).** Canonical circuits expressed as neutral gate programs, with expected results computed by a bundled pure-numpy reference simulator written directly in the canonical conventions. `run_conformance(backend)` checks snapshots, final states, operator matrices, unitarity, sampled distributions, and equivalence verdicts. First-party backends certify through this same public path in the test suite; a third-party backend supplies one interpreter function from the neutral vocabulary to its own circuit type.

## Execution flow, one test

1. Test calls `qlens.run(circuit)`.
2. Registry polls `handles()` across registered backends; the match loads.
3. Backend captures a per-gate statevector walk into `Snapshot` objects, converting to canonical form at its boundary.
4. `ExecutionResult` returns; counts are a lazy callback into the backend, cached per shot count.
5. `assert_distribution(result, expected)` draws counts, runs the chi-square test, and raises `QlensAssertionError` if the p-value falls below the significance level.

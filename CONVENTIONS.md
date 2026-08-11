# Qlens Semantic Conventions

Quantum frameworks disagree on output semantics: Qiskit writes bitstrings little-endian (qubit 0 rightmost), PennyLane writes them big-endian; statevector basis ordering, wire ordering, and phase handling differ the same way. Qlens defines one canonical convention for every observable output. Every backend converts at its own boundary, so nothing downstream of a `Backend` method ever sees a framework-native ordering.

This document is normative for backend implementations. The executable form of these rules is the reference simulator in `qlens.conformance._reference`, and the conformance suite (`qlens.conformance.run_conformance`) checks an implementation against it.

## Bitstrings: big-endian

Qubit 0 is the leftmost character. The string reads left to right in qubit order.

| Circuit | Canonical outcome | Never |
|---|---|---|
| X on qubit 0 of 2 | `"10"` | `"01"` |
| X on qubit 2 of 3 | `"001"` | `"100"` |

Applies to `counts()` keys and to `expected` mappings in `assert_distribution`.

## Statevector basis ordering: big-endian

Index `i` of a statevector is basis state `|b>` where `b` is `i` written as an `n`-bit big-endian bitstring. Qubit 0 is the most significant bit.

For the state after H on qubit 0 of a 2-qubit register, `(|00> + |10>)/sqrt(2)`:

| Index | Basis state | Amplitude |
|---|---|---|
| 0 | `|00>` | `1/sqrt(2)` |
| 1 | `|01>` | `0` |
| 2 | `|10>` | `1/sqrt(2)` |
| 3 | `|11>` | `0` |

A little-endian leak puts the second amplitude at index 1 instead of index 2; the conformance suite's `bell` case fails on this immediately.

## Operator matrices

Same big-endian basis ordering on both axes. `operator_matrix()` returns the dense unitary of the whole circuit; circuits containing measurement or reset have no operator and raise `UnsupportedCircuitError`.

## Qubit indices

Qubits are indexed `0..n-1` in the framework's own register/wire order, normalized to integers. In `Snapshot.qubits`, control qubits come before targets, matching gate-definition order (`cx` is `(control, target)`, `ccx` is `(control, control, target)`).

For frameworks with non-integer wire labels (PennyLane allows any hashable), wires sort into canonical order: numerically for integer labels, by string otherwise. Idle wires the device declares still count: an untouched qubit contributes its bit to every counts key and its axis to every statevector.

## Snapshots

One `Snapshot` per gate, in execution order, positions numbered from 0. Structural pseudo-instructions (barriers, delays) produce no snapshot. A circuit with no gates yields a single snapshot holding the initial `|0...0>` state.

## Gate names

`Snapshot.gate` is one lowercase name per gate across every backend. The frameworks disagree about spelling, and absorbing that's a backend's job rather than a caller's: a controlled-NOT reports `cx` whether the framework called it `cx`, `CNOT`, or something else again.

| Canonical | Qiskit | PennyLane | Cirq |
|---|---|---|---|
| `i` | `id` | `Identity` | `I` |
| `x` | `x` | `PauliX` | `X` |
| `h` | `h` | `Hadamard` | `H` |
| `sdg` | `sdg` | `Adjoint(S)` | `S**-1` |
| `sx` | `sx` | `SX` | `X**0.5` |
| `cx` | `cx` | `CNOT` | `CNOT` |
| `ccx` | `ccx` | `Toffoli` | `TOFFOLI` |
| `cswap` | `cswap` | `CSWAP` | `FREDKIN` |
| `p` | `p` | `PhaseShift` | — |
| `u` | `u` | `Rot` | — |

A gate outside this vocabulary keeps the framework's own name, lowercased, rather than being forced into a canonical one it doesn't have. `Snapshot.native_gate` always holds what the framework itself called the gate, so nothing is lost in translation and a backend-specific gate is still identifiable.

`Snapshot.params` follows the same rule. Rotations report their angle in radians (`p0`) on every backend. A gate whose canonical name already fixes its rotation reports no parameters anywhere, even where the framework models it as a power of another gate and carries an exponent.

## Counts

`counts(circuit, shots=n)` returns `dict[str, int]` with values summing to `n`, keys all of length `num_qubits` over `{0, 1}`. Zero-count outcomes are omitted. Any measurement the user's circuit declares is ignored: every backend measures all qubits in the computational basis, so identical circuits produce identically-shaped counts on every backend.

A `seed` argument must make sampling reproducible: identical circuit, shots, and seed return identical counts on repeated calls within one backend and version. Seeds aren't required to reproduce across backends or versions.

## Tolerances

- `atol` in `is_unitary` bounds the largest absolute deviation of U†U from the identity.
- `atol` in `equivalent` bounds elementwise deviation after global-phase alignment. Equivalence ignores global phase and nothing else: Z and RZ(pi) are equivalent (they differ by the global factor `i`); X and Y aren't (relative phase).
- `tolerance` in `assert_distribution` is a significance level, not a distance; see USAGE.md.

## Global phase

Statevectors and matrices are reported as computed, with no phase normalization. Only `equivalent()` and the conformance suite's state comparisons are phase-invariant.

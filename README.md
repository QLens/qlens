# Qlens

A testing, debugging, and observability SDK for quantum programs, simulator-first.

Quantum software development lacks the testing and debugging ergonomics classical developers take for granted. Qlens packages statevector inspection, statistical output validation, and circuit equivalence checking into one pip-installable SDK for Qiskit and PennyLane, with a `pytest`-native testing API built on instrumented execution that captures the statevector after every gate.

```python
import qlens
from qiskit import QuantumCircuit


def test_bell_distribution():
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)

    result = qlens.run(circuit)
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5})
```

The same test body works against a PennyLane `QNode` unchanged, and produces the same canonical results: Qlens defines one semantic convention (big-endian bitstrings, canonical basis ordering) and every backend converts at its own boundary.

## Install

```bash
pip install qlens[qiskit]
```

Extras: `qlens[qiskit]`, `qlens[pennylane]`, or both. Python 3.11+. Simulator-only; no quantum hardware access is involved anywhere.

## What it does

- `qlens.run(circuit)`: instrumented execution capturing the statevector after every gate, with lazy sampled counts.
- `qlens.assert_distribution(result, expected)`: chi-square or KS validation of measurement output against an expected distribution, without hand-rolling the statistics.
- `qlens.assert_unitary(circuit)`: unitarity within numerical tolerance.
- `qlens.assert_equivalent(a, b)`: same unitary up to global phase, across different gate decompositions.
- A bundled pytest plugin: fixtures and a `qlens` marker, registered on install.
- A public backend contract with entry-point discovery, so further frameworks (Cirq and beyond) plug in as separate packages certified against a shipped conformance suite.

## Documentation

- [USAGE.md](https://github.com/qlens/qlens/blob/main/USAGE.md): the full manual with runnable examples.
- [CONVENTIONS.md](https://github.com/qlens/qlens/blob/main/CONVENTIONS.md): the semantic conventions every backend follows.
- [ARCHITECTURE.md](https://github.com/qlens/qlens/blob/main/ARCHITECTURE.md): component diagram and contracts.
- [CHANGELOG.md](https://github.com/qlens/qlens/blob/main/CHANGELOG.md): dated changes per version.

## Status

Pre-release. Not yet published to PyPI.

## License

MIT.

---

Built by Mo Shehu — [mohammedshehu.com](https://mohammedshehu.com)

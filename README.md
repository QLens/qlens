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
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=0)
```

The same test body works against a PennyLane `QNode` unchanged, and produces the same canonical results: Qlens defines one semantic convention (big-endian bitstrings, canonical basis ordering) and every backend converts at its own boundary.

## Install

```bash
pip install qlens[qiskit]
```

Extras: `qlens[qiskit]`, `qlens[pennylane]`, or both. Python 3.11+. Simulator-only; no quantum hardware access is involved anywhere.

## What it does

- `qlens.run(circuit)`: instrumented execution capturing the statevector after every gate, with lazy sampled counts.
- `qlens.assert_distribution(result, expected)`: validates measurement output against an expected distribution by chi-square, a simulated p-value, total variation distance, or KS. When a method's assumptions don't hold for your data, Qlens says so and names the alternatives rather than switching methods behind your back.
- `qlens.assert_state(result, expected, at=96)`: the statevector at any point in the run, compared by fidelity up to global phase. `at=` works on `assert_distribution` too, so checks mark the position they apply to.
- `qlens.assert_unitary(circuit)`: unitarity within numerical tolerance.
- `qlens.assert_equivalent(a, b)`: same unitary up to global phase, across different gate decompositions.
- `qlens.inspect(result)`: step-through debugging over the captured snapshots (cursor, per-position probabilities, state diffs with fidelity), with no re-execution.
- `qlens.run(circuit, trace=True)`: records the run as a [TraceAct](https://github.com/traceact/traceact) trace with statevector sidecars, assertion pass/fail events, and per-run event budgets.
- `qlens view traces.jsonl`: a local viewer over recorded runs — the amplitude waterfall across every gate position, the statevector at any point against what a test expected, an A/B diff between two positions, and clickable assertion markers. A built-in reading guide explains all of it for people new to quantum computing. `qlens view --demo` opens it on sample runs.
- Project settings in `pyproject.toml` under `[tool.qlens]`, or `qlens.configure()`, choosing how distributions are compared and what happens when a test's assumptions don't hold. Any call overrides them, and the settings in force are recorded onto the run.
- A bundled pytest plugin: fixtures, a `qlens` marker, and automatic trace finalization per test.
- A public backend contract with entry-point discovery, so further frameworks (Cirq and beyond) plug in as separate packages certified against a shipped conformance suite.

## Documentation

- [USAGE.md](https://github.com/QLens/qlens/blob/main/USAGE.md): the full manual with runnable examples.
- [CONVENTIONS.md](https://github.com/QLens/qlens/blob/main/CONVENTIONS.md): the semantic conventions every backend follows.
- [ARCHITECTURE.md](https://github.com/QLens/qlens/blob/main/ARCHITECTURE.md): component diagram and contracts.
- [CHANGELOG.md](https://github.com/QLens/qlens/blob/main/CHANGELOG.md): dated changes per version.

## Status

Published on [PyPI](https://pypi.org/project/qlens/). Early: the public API
follows semver and the surfaces described here are the ones to build against,
but expect it to keep growing quickly.

## License

MIT.

---

Built by Mo Shehu — [mohammedshehu.com](https://mohammedshehu.com)

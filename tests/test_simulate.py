"""The canonical simulator, cross-checked against the real backends.

The mutation engine replays a captured gate list on ``_simulate`` rather
than on the framework that produced it. That only holds if the replay
matches the framework gate for gate, so the load-bearing test here runs
real circuits through each backend and through the simulator and asserts
the states agree. If the gate table ever drifts from what a backend does,
one of these fails.
"""

from __future__ import annotations

import numpy as np
import pytest

import qlens
from qlens._simulate import (
    GateOp,
    UnsupportedGateError,
    is_supported,
    matrix_for,
    qubit_count,
    simulate,
    unitary,
)
from qlens._stats import phase_invariant_allclose
from qlens.backends._registry import detect_backend
from qlens.conformance._builders import BUILDERS
from qlens.conformance._circuits import CASES

BACKENDS = ["qiskit", "pennylane", "cirq"]


def _ops(result: qlens.ExecutionResult) -> list[GateOp]:
    return [
        GateOp(s.gate, s.qubits, s.params)
        for s in result.snapshots
        if s.gate != "initial"
    ]


# -- the load-bearing cross-check -----------------------------------------


@pytest.mark.parametrize("backend_name", BACKENDS)
@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_replay_matches_backend_state_by_state(case, backend_name):
    """Every captured snapshot equals the simulator's replay of it."""
    pytest.importorskip(backend_name)
    circuit = BUILDERS[backend_name](case.program, case.num_qubits)
    result = qlens.run(circuit)
    replayed = simulate(_ops(result), case.num_qubits)
    captured = [s.statevector for s in result.snapshots if s.gate != "initial"]
    assert len(replayed) == len(captured)
    for got, want in zip(replayed, captured, strict=True):
        # Strict, not phase-invariant: a per-gate global-phase disagreement
        # would become a real relative phase once a control is involved, so
        # the states must match exactly, not merely up to phase.
        np.testing.assert_allclose(got, want, atol=1e-9)


def test_replay_covers_the_extended_vocabulary_against_qiskit():
    """The gates the neutral conformance set doesn't reach: daggers, sqrt-X,
    the controlled-rotation and three-qubit families, iswap, phase, u."""
    qiskit = pytest.importorskip("qiskit")
    qc = qiskit.QuantumCircuit(3)
    qc.h(0)
    qc.sdg(0)
    qc.tdg(1)
    qc.sx(2)
    qc.cy(0, 1)
    qc.ch(1, 2)
    qc.cp(0.5, 0, 1)
    qc.crx(0.7, 1, 2)
    qc.cry(0.3, 0, 2)
    qc.crz(0.9, 2, 0)
    qc.p(0.4, 0)
    qc.u(0.5, 0.6, 0.7, 1)
    qc.iswap(0, 1)
    qc.ccz(0, 1, 2)
    qc.ccx(0, 1, 2)
    qc.cswap(0, 1, 2)

    result = qlens.run(qc)
    ops = _ops(result)
    replayed = simulate(ops, 3)
    captured = [s.statevector for s in result.snapshots if s.gate != "initial"]
    for got, want in zip(replayed, captured, strict=True):
        np.testing.assert_allclose(got, want, atol=1e-9)

    # And the composed unitary matches Qiskit's own operator.
    reference = detect_backend(qc).operator_matrix(qc)
    assert phase_invariant_allclose(unitary(ops, 3), reference, atol=1e-9)


# -- matrix properties -----------------------------------------------------


@pytest.mark.parametrize(
    "op",
    [
        GateOp("x", (0,)),
        GateOp("h", (0,)),
        GateOp("sx", (0,)),
        GateOp("rz", (0,), {"p0": 1.1}),
        GateOp("u", (0,), {"p0": 0.5, "p1": 0.6, "p2": 0.7}),
        GateOp("cx", (0, 1)),
        GateOp("cswap", (0, 1, 2)),
        GateOp("ccx", (0, 1, 2)),
        GateOp("iswap", (0, 1)),
    ],
)
def test_every_gate_matrix_is_unitary(op):
    matrix = matrix_for(op)
    identity = np.eye(matrix.shape[0])
    np.testing.assert_allclose(matrix.conj().T @ matrix, identity, atol=1e-12)


def test_controlled_gate_acts_only_when_the_control_is_set():
    # cx leaves |00>,|01> alone and flips the target on |10>,|11>.
    cx = matrix_for(GateOp("cx", (0, 1)))
    for basis, expected in {0: 0, 1: 1, 2: 3, 3: 2}.items():
        column = cx[:, basis]
        assert np.argmax(np.abs(column)) == expected


def test_qubit_count_and_support_agree_with_the_table():
    assert qubit_count("h") == 1
    assert qubit_count("cx") == 2
    assert qubit_count("ccx") == 3
    assert qubit_count("cswap") == 3
    assert is_supported("crz")
    assert not is_supported("wobble")


def test_an_unmodelled_gate_is_refused_not_guessed():
    with pytest.raises(UnsupportedGateError, match="wobble"):
        matrix_for(GateOp("wobble", (0,)))
    with pytest.raises(UnsupportedGateError):
        qubit_count("wobble")


def test_a_wrong_arity_gate_is_refused():
    # cx built against three qubits is a capture bug, not a bigger gate.
    with pytest.raises(UnsupportedGateError, match="acts on 2 qubit"):
        matrix_for(GateOp("cx", (0, 1, 2)))


def test_empty_op_list_is_the_ground_state():
    (state,) = simulate([], 2)
    np.testing.assert_allclose(state, [1, 0, 0, 0], atol=1e-12)

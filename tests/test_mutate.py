"""Mutation testing: the operators, the scoring, and the equivalent-discard.

The claims worth pinning are behavioural, not cosmetic: a strong check
kills mutants a weak one lets survive; a mutant that computes the same
unitary is set aside rather than counted; and a circuit the simulator
cannot replay is refused up front instead of mutated into nonsense.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import qlens
from qlens._mutations import (
    all_mutations,
    delete_gate,
    inject_phase,
    reverse_control_target,
    substitute_gate,
)
from qlens._simulate import GateOp

pytest.importorskip("qiskit")

from qiskit import QuantumCircuit

ROOT2 = 1 / math.sqrt(2)


def bell_circuit() -> QuantumCircuit:
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.cx(0, 1)
    return qc


def bell_state() -> np.ndarray:
    return np.array([ROOT2, 0, 0, ROOT2], dtype=np.complex128)


# -- the operators, on their own ------------------------------------------


def test_reverse_control_target_swaps_the_two_qubits():
    ops = [GateOp("cx", (0, 1))]
    (mutant,) = reverse_control_target(ops)
    assert mutant.ops[0].qubits == (1, 0)


def test_reverse_skips_single_qubit_gates():
    assert reverse_control_target([GateOp("h", (0,))]) == []


def test_substitute_produces_same_shape_siblings_only():
    (ops) = [GateOp("h", (0,))]
    siblings = {m.ops[0].gate for m in substitute_gate(ops)}
    assert "h" not in siblings  # never itself
    assert {"x", "y", "z", "s", "t", "sx"} <= siblings  # same 1-qubit class
    assert "cx" not in siblings  # never a different arity


def test_substitute_carries_parameters_across_the_swap():
    (mutant, *_) = [m for m in substitute_gate([GateOp("rx", (0,), {"p0": 0.7})])]
    assert mutant.ops[0].params == {"p0": 0.7}
    assert mutant.ops[0].gate in {"ry", "rz", "p"}


def test_inject_phase_inserts_one_extra_gate():
    (mutant,) = inject_phase([GateOp("h", (0,))])
    assert [op.gate for op in mutant.ops] == ["h", "z"]


def test_delete_gate_removes_exactly_one():
    ops = [GateOp("h", (0,)), GateOp("cx", (0, 1))]
    mutants = delete_gate(ops)
    assert [len(m.ops) for m in mutants] == [1, 1]
    assert [m.ops[0].gate for m in mutants] == ["cx", "h"]


def test_all_mutations_rejects_an_unknown_operator():
    with pytest.raises(ValueError, match="unknown mutation operator"):
        all_mutations([GateOp("h", (0,))], operators=["delete_gate", "nope"])


# -- end to end -----------------------------------------------------------


def test_a_strong_check_kills_more_than_a_weak_one():
    # A check that only looks at qubit 0's marginal cannot see a broken
    # entangler; a full-state check can.
    def weak(result: qlens.ExecutionResult) -> None:
        counts = result.counts(shots=4000, seed=1)
        zero = sum(c for b, c in counts.items() if b[0] == "0")
        assert abs(zero / 4000 - 0.5) < 0.1

    def strong(result: qlens.ExecutionResult) -> None:
        qlens.assert_state(result, bell_state())

    weak_report = qlens.mutate(bell_circuit(), weak)
    strong_report = qlens.mutate(bell_circuit(), strong)
    assert strong_report.score > weak_report.score
    assert len(strong_report.survived) < len(weak_report.survived)


def test_the_bell_state_check_catches_the_broken_entangler():
    def check(result: qlens.ExecutionResult) -> None:
        qlens.assert_state(result, bell_state())

    report = qlens.mutate(bell_circuit(), check)
    # The reversed-CX mutant makes a different state and must be killed.
    reversed_cx = [
        r for r in report.results if r.operator == "reverse_control_target"
    ]
    assert reversed_cx and all(r.outcome == "killed" for r in reversed_cx)


def test_an_equivalent_mutant_is_discarded_not_counted():
    # Reversing the control and target of a CZ changes nothing: CZ is
    # symmetric, so that mutant computes the same unitary and must land in
    # the equivalent bucket, never as a survivor.
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.h(1)
    qc.cz(0, 1)

    def check(result: qlens.ExecutionResult) -> None:
        qlens.assert_state(result, qlens.run(qc).final_statevector)

    report = qlens.mutate(qc, check, operators=["reverse_control_target"])
    assert any(r.outcome == "equivalent" for r in report.results)
    # An equivalent mutant is out of the denominator.
    assert report.scored + len(report.equivalent) == len(report.results)


def test_equivalents_do_not_drag_the_score_down():
    # A perfect check should score 1.0 even where some mutants are
    # equivalent: those are excluded, not counted as survivors. The CZ
    # circuit has a reversed-CZ mutant that is equivalent (CZ is symmetric)
    # alongside mutants a full-state check kills.
    qc = QuantumCircuit(2)
    qc.h(0)
    qc.h(1)
    qc.cz(0, 1)
    expected = qlens.run(qc).final_statevector

    def check(result: qlens.ExecutionResult) -> None:
        qlens.assert_state(result, expected)

    report = qlens.mutate(qc, check)
    assert report.survived == []
    assert report.score == 1.0
    assert report.equivalent  # there is at least one, and it didn't hurt the score


def test_max_mutants_caps_and_is_deterministic_under_seed():
    def check(result: qlens.ExecutionResult) -> None:
        qlens.assert_state(result, bell_state())

    a = qlens.mutate(bell_circuit(), check, max_mutants=3, seed=7)
    b = qlens.mutate(bell_circuit(), check, max_mutants=3, seed=7)
    assert len(a.results) == 3
    assert [r.description for r in a.results] == [r.description for r in b.results]


def test_a_gate_the_simulator_cannot_replay_is_refused():
    # A circuit carrying a gate outside the canonical vocabulary can't be
    # mutated, and says so rather than silently dropping it.
    qc = QuantumCircuit(2)
    qc.rzz(0.5, 0, 1)  # rzz is not in the canonical simulator's table

    def check(result: qlens.ExecutionResult) -> None:
        pass

    with pytest.raises(qlens.QlensError, match="can't replay gate"):
        qlens.mutate(qc, check)


@pytest.mark.parametrize("backend_name", ["qiskit", "pennylane", "cirq"])
def test_mutation_runs_uniformly_across_backends(backend_name):
    # The point of replaying on Qlens's own simulator: one path mutates a
    # Qiskit circuit, a PennyLane function, and a Cirq circuit alike.
    pytest.importorskip(backend_name)
    from qlens.conformance._builders import BUILDERS

    program = (("h", (0,), ()), ("cx", (0, 1), ()))
    circuit = BUILDERS[backend_name](program, 2)

    def check(result: qlens.ExecutionResult) -> None:
        qlens.assert_state(result, bell_state())

    report = qlens.mutate(circuit, check)
    assert report.scored > 0
    assert report.score == 1.0  # the Bell state check kills every non-equivalent mutant


def test_the_report_summary_reads_cleanly():
    def check(result: qlens.ExecutionResult) -> None:
        qlens.assert_state(result, bell_state())

    report = qlens.mutate(bell_circuit(), check)
    summary = report.summary()
    assert "mutation score" in summary
    assert "killed" in summary and "equivalent" in summary

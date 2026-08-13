"""Separability: the maths, then the assertions built on it.

Refusals and degenerate subsystems first. A purity check answers with a
number for almost any input, including inputs that mean nothing — the
whole register, an empty subset, a qubit that doesn't exist — so the
cases worth pinning are the ones where a plausible number would be the
wrong answer.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import qlens
from qlens._errors import QlensAssertionError, QlensError
from qlens._stats import schmidt_coefficients, subsystem_purity

pytest.importorskip("qiskit")

from qiskit import QuantumCircuit

ROOT2 = 1 / math.sqrt(2)


def bell() -> np.ndarray:
    return np.array([ROOT2, 0, 0, ROOT2], dtype=np.complex128)


def ghz(n: int) -> np.ndarray:
    state = np.zeros(2**n, dtype=np.complex128)
    state[0] = state[-1] = ROOT2
    return state


# -- the maths ---------------------------------------------------------


def test_a_product_state_has_one_schmidt_coefficient() -> None:
    plus_zero = np.array([ROOT2, 0, ROOT2, 0], dtype=np.complex128)
    values = schmidt_coefficients(plus_zero, [0], 2)
    assert values[0] == pytest.approx(1.0)
    assert values[1] == pytest.approx(0.0, abs=1e-12)


def test_a_bell_state_splits_its_weight_evenly() -> None:
    values = schmidt_coefficients(bell(), [0], 2)
    assert values == pytest.approx([ROOT2, ROOT2])


def test_purity_is_one_for_a_product_state_and_a_half_for_a_bell_pair() -> None:
    assert subsystem_purity(np.array([1, 0, 0, 0], dtype=np.complex128), [0], 2) == 1.0
    assert subsystem_purity(bell(), [0], 2) == pytest.approx(0.5)


def test_either_half_of_a_bell_pair_reads_the_same() -> None:
    """Entanglement is a property of the split, not of one side of it."""
    assert subsystem_purity(bell(), [0], 2) == pytest.approx(
        subsystem_purity(bell(), [1], 2)
    )


def test_a_subsystem_need_not_be_contiguous() -> None:
    """Qubits 0 and 2 entangled, qubit 1 idle between them. A split that
    assumed contiguous qubits would report the wrong side as correlated."""
    state = np.zeros(8, dtype=np.complex128)
    state[0b000] = state[0b101] = ROOT2
    assert subsystem_purity(state, [0], 3) == pytest.approx(0.5)
    assert subsystem_purity(state, [2], 3) == pytest.approx(0.5)
    assert subsystem_purity(state, [1], 3) == pytest.approx(1.0)
    # The entangled pair together is separable from the idle qubit.
    assert subsystem_purity(state, [0, 2], 3) == pytest.approx(1.0)


def test_qubit_order_within_the_subset_does_not_change_the_answer() -> None:
    """A property of the maths rather than of the sorting: permuting the
    subset permutes the matrix's rows, and a permutation is unitary, so
    the singular values are untouched. Pinned because a caller passing
    [2, 0] must get the same verdict as one passing [0, 2]."""
    assert subsystem_purity(ghz(3), [2, 0], 3) == pytest.approx(
        subsystem_purity(ghz(3), [0, 2], 3)
    )


def test_purity_is_scale_invariant() -> None:
    """A statevector arrives normalized, but the measure must not depend
    on that: an unnormalized state is still just as entangled."""
    assert subsystem_purity(bell() * 7.5, [0], 2) == pytest.approx(0.5)


def test_an_all_zero_state_does_not_divide_by_zero() -> None:
    assert subsystem_purity(np.zeros(4, dtype=np.complex128), [0], 2) == 0.0


def test_a_global_phase_does_not_change_entanglement() -> None:
    phased = bell() * np.exp(1j * 0.9)
    assert subsystem_purity(phased, [0], 2) == pytest.approx(0.5)


def test_partial_entanglement_lands_between_the_extremes() -> None:
    """Purity is a measure, not a flag: a barely-entangled state must read
    as barely entangled rather than as maximally so."""
    state = np.array([0.99, 0, 0, math.sqrt(1 - 0.99**2)], dtype=np.complex128)
    purity = subsystem_purity(state, [0], 2)
    assert 0.9 < purity < 1.0


# -- refusals ----------------------------------------------------------


def circuit_result(builder: QuantumCircuit) -> qlens.ExecutionResult:
    return qlens.run(builder)


@pytest.fixture()
def bell_result() -> qlens.ExecutionResult:
    c = QuantumCircuit(2)
    c.h(0)
    c.cx(0, 1)
    return qlens.run(c)


def test_naming_no_qubits_is_refused(bell_result: qlens.ExecutionResult) -> None:
    with pytest.raises(QlensError, match="at least one qubit"):
        qlens.assert_separable(bell_result, [])


def test_naming_the_whole_register_is_refused(
    bell_result: qlens.ExecutionResult,
) -> None:
    """Purity of the whole register is always 1, so answering would report
    every circuit as separable — a passing check that proves nothing."""
    with pytest.raises(QlensError, match="whole 2-qubit register"):
        qlens.assert_separable(bell_result, [0, 1])


def test_a_duplicate_qubit_is_refused(bell_result: qlens.ExecutionResult) -> None:
    with pytest.raises(QlensError, match="duplicates"):
        qlens.assert_separable(bell_result, [0, 0])


def test_a_qubit_outside_the_register_is_refused(
    bell_result: qlens.ExecutionResult,
) -> None:
    with pytest.raises(QlensError, match=r"outside the circuit's 0\.\.1 range"):
        qlens.assert_separable(bell_result, [5])
    with pytest.raises(QlensError, match="outside"):
        qlens.assert_separable(bell_result, [-1])


# -- the assertions ----------------------------------------------------


def test_an_entangled_qubit_fails_the_separability_check(
    bell_result: qlens.ExecutionResult,
) -> None:
    with pytest.raises(QlensAssertionError) as excinfo:
        qlens.assert_separable(bell_result, [0])
    message = str(excinfo.value)
    assert "q0" in message
    assert "0.500000" in message, "the message must carry the measured purity"


def test_an_idle_qubit_passes_the_separability_check() -> None:
    c = QuantumCircuit(3)
    c.h(0)
    c.cx(0, 1)  # q2 never touched
    qlens.assert_separable(qlens.run(c), [2])


def test_a_separable_qubit_fails_the_entanglement_check() -> None:
    c = QuantumCircuit(2)
    c.h(0)
    c.x(1)
    with pytest.raises(QlensAssertionError, match="separable"):
        qlens.assert_entangled(qlens.run(c), [0])


def test_an_entangled_qubit_passes_the_entanglement_check(
    bell_result: qlens.ExecutionResult,
) -> None:
    qlens.assert_entangled(bell_result, [0])


def test_the_two_assertions_are_complements(
    bell_result: qlens.ExecutionResult,
) -> None:
    """Whatever one accepts, the other must reject. A state cannot be both
    a product state and correlated with the rest."""
    for qubits in ([0], [1]):
        qlens.assert_entangled(bell_result, qubits)
        with pytest.raises(QlensAssertionError):
            qlens.assert_separable(bell_result, qubits)


def test_at_checks_the_position_named_not_the_end_of_the_run() -> None:
    """The whole point of a positional check: the ancilla is entangled in
    the middle of this circuit and separable again by the end."""
    c = QuantumCircuit(2)
    c.h(0)
    c.cx(0, 1)  # position 1: entangled
    c.cx(0, 1)  # position 2: mirrored back
    result = qlens.run(c)

    qlens.assert_entangled(result, [1], at=1)
    qlens.assert_separable(result, [1], at=2)
    qlens.assert_separable(result, [1])  # the end of the run

    with pytest.raises(QlensAssertionError):
        qlens.assert_separable(result, [1], at=1)


def test_a_negative_position_counts_from_the_end() -> None:
    c = QuantumCircuit(2)
    c.h(0)
    c.cx(0, 1)
    result = qlens.run(c)
    qlens.assert_entangled(result, [0], at=-1)


def test_tolerance_admits_a_state_a_hair_off_separable() -> None:
    """Rounding across a long circuit leaves a purity fractionally below 1,
    and a check that fired on that would be unusable."""
    c = QuantumCircuit(2)
    c.ry(1e-7, 0)  # a rotation far below any meaningful entanglement
    c.cx(0, 1)
    result = qlens.run(c)
    qlens.assert_separable(result, [0], atol=1e-6)
    with pytest.raises(QlensAssertionError):
        qlens.assert_separable(result, [0], atol=1e-30)

"""The four bug patterns Qlens claims to catch, each reproduced and caught.

Every case here is a documented pattern from the empirical literature on
quantum program bugs, written twice: once correct, once with the fault
injected. Each pair pins two things — that the buggy version really is
buggy, and that the assertion named in the catalog is the one that finds
it. A catalog entry nothing exercises is a claim, not a feature.

The pairs also serve the mutation engine: each fault is what one mutation
operator will do to a correct circuit, so these are the mutants a test
suite has to kill.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import qlens
from qlens._errors import QlensAssertionError

pytest.importorskip("qiskit")

from qiskit import QuantumCircuit

SHOTS = 4096
SEED = 7


# -- 1. wrong qubit order ----------------------------------------------
#
# The most-cited quantum-specific pattern, and the one the frameworks
# invite: Qiskit labels bitstrings little-endian, PennyLane and Cirq
# big-endian. A control and target the wrong way round survives every
# structural check — the circuit is still unitary, still the right depth,
# still uses the right gates.


def controlled_pair(flipped: bool = False) -> QuantumCircuit:
    c = QuantumCircuit(2)
    c.x(0)
    c.cx(1, 0) if flipped else c.cx(0, 1)
    return c


def test_a_reversed_control_and_target_changes_the_state() -> None:
    good = qlens.run(controlled_pair()).final_statevector
    bad = qlens.run(controlled_pair(flipped=True)).final_statevector
    assert not np.allclose(good, bad)


def test_a_reversed_control_and_target_is_caught_by_a_state_check() -> None:
    good = qlens.run(controlled_pair()).final_statevector
    with pytest.raises(QlensAssertionError, match="fidelity"):
        qlens.assert_state(qlens.run(controlled_pair(flipped=True)), good)


def test_a_reversed_control_and_target_stays_unitary() -> None:
    """Which is why a structural check can't find it: nothing about the
    circuit is malformed, only wrong."""
    qlens.assert_unitary(controlled_pair(flipped=True))


# -- 2. wrong gate -----------------------------------------------------
#
# A same-arity substitution: h for x on one wire. This is the single
# largest semantically-checkable category in the bug-fix study.


def entangler(wrong_gate: bool = False) -> QuantumCircuit:
    c = QuantumCircuit(2)
    c.h(0)
    c.h(1) if wrong_gate else c.x(1)
    c.cx(0, 1)
    return c


def test_a_substituted_gate_changes_the_distribution() -> None:
    good = qlens.run(entangler()).counts(shots=SHOTS, seed=SEED)
    bad = qlens.run(entangler(wrong_gate=True)).counts(shots=SHOTS, seed=SEED)
    assert good != bad


def test_a_substituted_gate_is_caught_by_a_distribution_check() -> None:
    with pytest.raises(QlensAssertionError):
        qlens.assert_distribution(
            qlens.run(entangler(wrong_gate=True)),
            {"01": 0.5, "10": 0.5},
            seed=SEED,
        )


# -- 3. a phase error measurement cannot see ---------------------------
#
# The pattern that most justifies capturing statevectors at all. A
# relative phase leaves every measurement probability untouched, so the
# counts are byte-identical and every distribution check passes. Only a
# state check sees it — and it matters, because phase is what later
# interference depends on.


def ghz_with_phase(bug: float = 0.0) -> QuantumCircuit:
    c = QuantumCircuit(3)
    c.h(0)
    c.cx(0, 1)
    c.cx(1, 2)
    if bug:
        c.p(bug, 1)
    return c


def test_a_phase_error_leaves_the_counts_identical() -> None:
    good = qlens.run(ghz_with_phase()).counts(shots=SHOTS, seed=SEED)
    bad = qlens.run(ghz_with_phase(math.pi / 3)).counts(shots=SHOTS, seed=SEED)
    assert good == bad, "if this ever differs, the pattern has stopped being subtle"


def test_a_phase_error_passes_every_distribution_check() -> None:
    """Not a bug in assert_distribution: measurement genuinely cannot
    distinguish these states. It's the reason the state check exists."""
    bad = qlens.run(ghz_with_phase(math.pi / 3))
    qlens.assert_distribution(bad, {"000": 0.5, "111": 0.5}, seed=SEED)


def test_a_phase_error_is_caught_by_a_state_check() -> None:
    good = qlens.run(ghz_with_phase()).final_statevector
    with pytest.raises(QlensAssertionError, match="fidelity"):
        qlens.assert_state(qlens.run(ghz_with_phase(math.pi / 3)), good)


def test_a_global_phase_is_not_reported_as_a_bug() -> None:
    """The complement, and the line the check has to hold: an overall
    phase factor is the same physical state, and flagging it would make
    the assertion useless."""
    good = qlens.run(ghz_with_phase())
    qlens.assert_state(good, good.final_statevector * np.exp(1j * 1.1))


# -- 4. an ancilla that was not uncomputed ------------------------------
#
# Mirroring a computation back is what releases a scratch qubit. Skip it
# and the ancilla stays entangled with the data, which destroys the
# interference the algorithm depends on. The symptom appears at the end
# of the run; the cause is the missing gate.


def with_ancilla(uncompute: bool = True) -> QuantumCircuit:
    c = QuantumCircuit(2)  # q0 data, q1 ancilla
    c.h(0)
    c.cx(0, 1)
    if uncompute:
        c.cx(0, 1)
    c.h(0)
    return c


def test_a_leaked_ancilla_destroys_the_interference() -> None:
    """The end-of-run symptom: a deterministic answer becomes a coin flip."""
    clean = qlens.run(with_ancilla()).counts(shots=SHOTS, seed=SEED)
    leaked = qlens.run(with_ancilla(uncompute=False)).counts(shots=SHOTS, seed=SEED)
    assert clean == {"00": SHOTS}
    assert len(leaked) == 4, "the answer has spread across every outcome"


def test_a_leaked_ancilla_is_caught_by_a_separability_check() -> None:
    with pytest.raises(QlensAssertionError, match="entangled"):
        qlens.assert_separable(qlens.run(with_ancilla(uncompute=False)), [1])


def test_an_uncomputed_ancilla_passes() -> None:
    qlens.assert_separable(qlens.run(with_ancilla()), [1])


def test_the_separability_check_names_the_gate_that_should_have_released_it() -> None:
    """Why the positional form is the point. Checked at the end of the run
    both circuits differ, but checked at the mirroring position the fault
    is attributable to one gate rather than to the whole circuit."""
    leaked = qlens.run(with_ancilla(uncompute=False))
    # Position 1 is the compute step: entangled in both versions.
    qlens.assert_entangled(leaked, [1], at=1)
    # Position 2 is where the mirror should have been; in the correct
    # circuit the ancilla is free by here.
    clean = qlens.run(with_ancilla())
    qlens.assert_separable(clean, [1], at=2)
    with pytest.raises(QlensAssertionError):
        qlens.assert_separable(leaked, [1], at=2)


def marginal(result: qlens.ExecutionResult, qubit: int, num_qubits: int) -> list[float]:
    """Probability of 0 and 1 on one qubit, tracing out the others."""
    shift = num_qubits - 1 - qubit  # big-endian: qubit 0 is most significant
    return [
        float(
            sum(
                abs(a) ** 2
                for i, a in enumerate(result.final_statevector)
                if (i >> shift) & 1 == bit
            )
        )
        for bit in (0, 1)
    ]


def before_interference(uncompute: bool = True) -> QuantumCircuit:
    """The leak while it's still silent: nothing downstream depends on the
    interference yet, so no measurement of the data has gone wrong."""
    c = QuantumCircuit(2)
    c.h(0)
    c.cx(0, 1)
    if uncompute:
        c.cx(0, 1)
    return c


def test_a_leaked_ancilla_is_invisible_in_the_data_qubit_alone() -> None:
    """Before anything interferes, the data qubit's own statistics are
    identical either way. A check that watches only the data passes on
    the buggy circuit."""
    clean = qlens.run(before_interference())
    leaked = qlens.run(before_interference(uncompute=False))
    assert marginal(clean, 0, 2) == pytest.approx(marginal(leaked, 0, 2))
    assert marginal(clean, 0, 2) == pytest.approx([0.5, 0.5])


def test_separability_finds_the_leak_while_it_is_still_silent() -> None:
    """The same circuit the marginal can't distinguish. Separability sees
    it because it asks about the correlation rather than about either
    qubit's own statistics — and it needs no expected state to do it."""
    qlens.assert_separable(qlens.run(before_interference()), [1])
    with pytest.raises(QlensAssertionError, match="entangled"):
        qlens.assert_separable(qlens.run(before_interference(uncompute=False)), [1])

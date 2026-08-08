"""assert_unitary, assert_equivalent, assert_distribution: failure paths
first, then success paths, across both backends."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from conftest import bell_program

import qlens

# A deliberately non-unitary matrix, close enough to unitary to pass
# framework input validation being skipped, far enough to fail atol=1e-8.
_ALMOST_UNITARY = np.array([[1.0, 0.0], [0.0, 0.999]], dtype=np.complex128)


# -- assert_unitary ---------------------------------------------------------


def test_unitary_failure_qiskit() -> None:
    qiskit = pytest.importorskip("qiskit")
    from qiskit.circuit.library import UnitaryGate

    circuit = qiskit.QuantumCircuit(1)
    circuit.append(UnitaryGate(_ALMOST_UNITARY, check_input=False), [0])
    with pytest.raises(qlens.QlensAssertionError, match="not unitary"):
        qlens.assert_unitary(circuit)


def test_unitary_failure_pennylane() -> None:
    qml = pytest.importorskip("pennylane")

    @qml.qnode(qml.device("default.qubit", wires=1))
    def circuit() -> Any:
        qml.QubitUnitary(_ALMOST_UNITARY, wires=0, unitary_check=False)
        return qml.state()

    with pytest.raises(qlens.QlensAssertionError, match="not unitary"):
        qlens.assert_unitary(circuit)


def test_unitary_failure_is_assertion_error(build: Any) -> None:
    # QlensAssertionError must be catchable as plain AssertionError so
    # pytest treats it as a failure, not an error.
    assert issubclass(qlens.QlensAssertionError, AssertionError)


def test_unitary_passes(build: Any) -> None:
    qlens.assert_unitary(build(bell_program(), 2))


def test_unitary_loose_atol_accepts_perturbation() -> None:
    qiskit = pytest.importorskip("qiskit")
    from qiskit.circuit.library import UnitaryGate

    circuit = qiskit.QuantumCircuit(1)
    circuit.append(UnitaryGate(_ALMOST_UNITARY, check_input=False), [0])
    qlens.assert_unitary(circuit, atol=0.01)


# -- assert_equivalent ------------------------------------------------------


def test_equivalent_failure(build: Any) -> None:
    bell = build(bell_program(), 2)
    bell_with_z = build((("h", (0,), ()), ("cx", (0, 1), ()), ("z", (1,), ())), 2)
    with pytest.raises(qlens.QlensAssertionError, match="not equivalent"):
        qlens.assert_equivalent(bell, bell_with_z)


def test_equivalent_cross_framework_rejected() -> None:
    pytest.importorskip("qiskit")
    pytest.importorskip("pennylane")
    from qlens.conformance._builders import BUILDERS

    program = bell_program()
    with pytest.raises(qlens.QlensError, match="across frameworks"):
        qlens.assert_equivalent(
            BUILDERS["qiskit"](program, 2), BUILDERS["pennylane"](program, 2)
        )


def test_equivalent_different_decompositions(build: Any) -> None:
    swap = build((("swap", (0, 1), ()),), 2)
    decomposed = build((("cx", (0, 1), ()), ("cx", (1, 0), ()), ("cx", (0, 1), ())), 2)
    qlens.assert_equivalent(swap, decomposed)


def test_equivalent_ignores_global_phase(build: Any) -> None:
    z_gate = build((("z", (0,), ()),), 1)
    rz_pi = build((("rz", (0,), (float(np.pi),)),), 1)
    qlens.assert_equivalent(z_gate, rz_pi)


# -- assert_distribution ----------------------------------------------------


def test_distribution_rejects_wrong_expectation(build: Any) -> None:
    result = qlens.run(build(bell_program(), 2))
    # A Bell state never yields "01"/"10"; expecting uniform over all four
    # outcomes must fail decisively.
    with pytest.raises(qlens.QlensAssertionError, match="distribution mismatch"):
        qlens.assert_distribution(
            result, {"00": 0.25, "01": 0.25, "10": 0.25, "11": 0.25}
        )


def test_distribution_impossible_outcome_rejects() -> None:
    # Counts contain an outcome the expectation says is impossible.
    with pytest.raises(qlens.QlensAssertionError):
        qlens.assert_distribution({"00": 900, "01": 100}, {"00": 1.0})


def test_distribution_tolerance_out_of_range() -> None:
    with pytest.raises(qlens.QlensError, match="tolerance"):
        qlens.assert_distribution({"0": 10}, {"0": 1.0}, tolerance=0.0)


def test_distribution_empty_counts_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        qlens.assert_distribution({}, {"0": 1.0})


def test_distribution_wrong_result_type() -> None:
    with pytest.raises(qlens.QlensError, match="cannot extract counts"):
        qlens.assert_distribution(3.14, {"0": 1.0})


def test_distribution_unknown_test_name() -> None:
    with pytest.raises(qlens.QlensError, match="unknown test"):
        qlens.assert_distribution({"0": 10}, {"0": 1.0}, test="anova")  # type: ignore[arg-type]


def test_distribution_ks_rejects_counts_mapping() -> None:
    with pytest.raises(qlens.QlensError, match="continuous"):
        qlens.assert_distribution({"0": 10}, "uniform", test="ks")


def test_distribution_bell_passes(build: Any) -> None:
    result = qlens.run(build(bell_program(), 2))
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=7)


def test_counts_seed_reproducible(build: Any) -> None:
    result = qlens.run(build(bell_program(), 2))
    first = result.counts(512, seed=42)
    # A fresh run must reproduce the same draw for the same seed.
    second = qlens.run(build(bell_program(), 2)).counts(512, seed=42)
    assert first == second


def test_distribution_accepts_raw_counts() -> None:
    qlens.assert_distribution({"00": 505, "11": 495}, {"00": 0.5, "11": 0.5})


def test_distribution_accepts_relative_weights() -> None:
    qlens.assert_distribution({"00": 505, "11": 495}, {"00": 1, "11": 1})


def test_distribution_ks_two_sample() -> None:
    rng = np.random.default_rng(7)
    samples = rng.normal(size=400)
    reference = rng.normal(size=400)
    qlens.assert_distribution(samples, reference, test="ks")


def test_distribution_ks_named_reference_rejects_shifted() -> None:
    rng = np.random.default_rng(7)
    samples = rng.uniform(low=0.3, size=400)
    with pytest.raises(qlens.QlensAssertionError):
        qlens.assert_distribution(samples, "uniform", test="ks")

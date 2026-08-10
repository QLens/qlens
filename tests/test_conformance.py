"""First-party backends certify through the same public conformance
suite a third-party backend would use."""

from __future__ import annotations

import numpy as np
import pytest

from qlens.backends import get_backend
from qlens.conformance import CASES, EQUIVALENCE_PAIRS, run_conformance
from qlens.conformance._reference import simulate, unitary


def test_reference_bell_state() -> None:
    # The reference simulator is the ground truth; pin its own output for
    # the canonical example so a regression there cannot silently
    # re-baseline every backend.
    state = simulate((("h", (0,), ()), ("cx", (0, 1), ())), 2)
    assert np.allclose(state, np.array([1, 0, 0, 1]) / np.sqrt(2))


def test_reference_unitary_is_unitary() -> None:
    matrix = unitary((("h", (0,), ()), ("cx", (0, 1), ())), 2)
    assert np.allclose(matrix.conj().T @ matrix, np.eye(4))


def test_case_inventory_meets_prd_minimum() -> None:
    # PRD Phase 1 requires 15+ circuits spanning single-qubit, multi-qubit,
    # and parameterized categories.
    assert len(CASES) + len(EQUIVALENCE_PAIRS) >= 15
    categories = {case.category for case in CASES}
    assert categories == {"single_qubit", "multi_qubit", "parameterized"}


def test_qiskit_conformance() -> None:
    pytest.importorskip("qiskit")
    assert run_conformance(get_backend("qiskit")) == []


def test_pennylane_conformance() -> None:
    pytest.importorskip("pennylane")
    assert run_conformance(get_backend("pennylane")) == []


def test_cirq_conformance() -> None:
    pytest.importorskip("cirq")
    assert run_conformance(get_backend("cirq")) == []

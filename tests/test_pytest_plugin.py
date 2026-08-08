"""The bundled pytest plugin, exercised through real pytest runs via
pytester — not by calling fixture functions directly."""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("qiskit")


def test_fixtures_available_and_bell_test_passes(pytester: Any) -> None:
    pytester.makepyfile(
        """
        import pytest
        from qiskit import QuantumCircuit

        @pytest.mark.qlens
        def test_bell(qlens_run, assert_distribution):
            circuit = QuantumCircuit(2)
            circuit.h(0)
            circuit.cx(0, 1)
            result = qlens_run(circuit)
            assert_distribution(result, {"00": 0.5, "11": 0.5})
        """
    )
    outcome = pytester.runpytest()
    outcome.assert_outcomes(passed=1)


def test_failing_assertion_reports_as_failure_not_error(pytester: Any) -> None:
    pytester.makepyfile(
        """
        from qiskit import QuantumCircuit

        def test_wrong_expectation(qlens_run, assert_distribution):
            circuit = QuantumCircuit(2)
            circuit.h(0)
            circuit.cx(0, 1)
            result = qlens_run(circuit)
            assert_distribution(result, {"01": 0.5, "10": 0.5})
        """
    )
    outcome = pytester.runpytest()
    outcome.assert_outcomes(failed=1, errors=0)


def test_qlens_marker_selects_tests(pytester: Any) -> None:
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.qlens
        def test_marked():
            pass

        def test_unmarked():
            pass
        """
    )
    outcome = pytester.runpytest("-m", "qlens")
    outcome.assert_outcomes(passed=1, deselected=1)

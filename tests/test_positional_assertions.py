"""Assertions that name a position in the run.

Against real circuits rather than hand-built results, because the point
of `at=` is that it addresses the frames a backend actually captured,
and an idealized stand-in would not catch an off-by-one against them.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

import qlens
from qlens import _config as config
from qlens._errors import QlensAssertionError, QlensError

pytest.importorskip("qiskit")

SQ2 = 1.0 / math.sqrt(2.0)


@pytest.fixture(autouse=True)
def _default_settings() -> Any:
    config.reset()
    yield
    config.reset()


def bell() -> Any:
    from qiskit import QuantumCircuit

    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    return circuit


# -- addressing the right frame ---------------------------------------


def test_at_names_the_state_after_that_gate() -> None:
    """Position 0 is after H alone: an even split over |00> and |10>,
    big-endian. Only position 1 is the entangled pair. A check that
    accepted either would not be addressing anything."""
    result = qlens.run(bell())
    qlens.assert_distribution(result, {"00": 0.5, "10": 0.5}, at=0, seed=0)
    with pytest.raises(QlensAssertionError):
        qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, at=0, seed=0)


def test_omitting_at_still_measures_the_final_state() -> None:
    result = qlens.run(bell())
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=0)


def test_negative_at_indexes_from_the_end() -> None:
    result = qlens.run(bell())
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, at=-1, seed=0)


def test_at_beyond_the_run_is_an_error_not_a_clamp() -> None:
    """Silently measuring the last frame instead would let a test claim
    to check a position the circuit never reached."""
    result = qlens.run(bell())
    with pytest.raises(IndexError):
        qlens.assert_distribution(result, {"00": 1.0}, at=99, seed=0)


def test_at_needs_a_result_not_a_counts_mapping() -> None:
    with pytest.raises(QlensError, match="no positions"):
        qlens.assert_distribution({"00": 512, "11": 512}, {"00": 0.5, "11": 0.5}, at=0)


def test_positional_counts_are_cached_per_position() -> None:
    result = qlens.run(bell())
    first = result.counts(1024, seed=1, at=0)
    assert result.counts(1024, seed=1, at=0) is first
    assert result.counts(1024, seed=1, at=1) is not first


def test_positional_counts_use_canonical_bitstrings() -> None:
    result = qlens.run(bell())
    assert set(result.counts(2048, seed=0, at=0)) <= {"00", "10"}
    assert set(result.counts(2048, seed=0, at=1)) <= {"00", "11"}


# -- assert_state ------------------------------------------------------


def test_assert_state_at_a_position() -> None:
    result = qlens.run(bell())
    qlens.assert_state(result, [SQ2, 0, SQ2, 0], at=0)
    qlens.assert_state(result, [SQ2, 0, 0, SQ2], at=1)


def test_assert_state_ignores_global_phase() -> None:
    result = qlens.run(bell())
    phased = np.array([SQ2, 0, 0, SQ2]) * np.exp(1j * 2.0)
    qlens.assert_state(result, phased)


def test_assert_state_rejects_a_relative_phase_difference() -> None:
    """Relative phase is physical; a fidelity check that missed it would
    accept a state no measurement can equate with the target."""
    result = qlens.run(bell())
    with pytest.raises(QlensAssertionError, match="fidelity"):
        qlens.assert_state(result, [SQ2, 0, 0, -SQ2])


def test_assert_state_reports_the_measured_fidelity() -> None:
    result = qlens.run(bell())
    with pytest.raises(QlensAssertionError, match=r"fidelity 0\.\d+ < required"):
        qlens.assert_state(result, [1, 0, 0, 0])


def test_assert_state_rejects_a_mismatched_width() -> None:
    result = qlens.run(bell())
    with pytest.raises(QlensError, match="same qubit count"):
        qlens.assert_state(result, [1, 0])


def test_assert_state_rejects_an_impossible_fidelity() -> None:
    result = qlens.run(bell())
    for bad in (0.0, 1.5, -1):
        with pytest.raises(QlensError, match="fidelity must be"):
            qlens.assert_state(result, [SQ2, 0, 0, SQ2], fidelity=bad)


def test_assert_state_threshold_is_honoured() -> None:
    result = qlens.run(bell())
    # |00> overlaps the Bell state with fidelity 0.5.
    qlens.assert_state(result, [1, 0, 0, 0], fidelity=0.4)
    with pytest.raises(QlensAssertionError):
        qlens.assert_state(result, [1, 0, 0, 0], fidelity=0.6)


# -- test selection ----------------------------------------------------


def test_project_default_selects_the_test() -> None:
    """Chosen so the two methods disagree: 0.9 as a distance accepts
    almost anything, while 0.9 as a significance level accepts almost
    nothing. Only one of them lets this through."""
    config.configure(distribution_test="tvd")
    result = qlens.run(bell())
    qlens.assert_distribution(result, {"00": 0.9, "11": 0.1}, tolerance=0.9, seed=0)

    config.configure(distribution_test="chi_square")
    with pytest.raises(QlensAssertionError):
        qlens.assert_distribution(result, {"00": 0.9, "11": 0.1}, tolerance=0.9, seed=0)


def test_a_call_overrides_the_project_default() -> None:
    config.configure(distribution_test="tvd")
    result = qlens.run(bell())
    qlens.assert_distribution(
        result, {"00": 0.5, "11": 0.5}, test="chi_square_exact", seed=0
    )


def test_unknown_test_name_rejected() -> None:
    result = qlens.run(bell())
    with pytest.raises(QlensError, match="chi_square_exact"):
        qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, test="wilcoxon")


def test_tvd_tolerance_is_a_distance_not_a_significance_level() -> None:
    result = qlens.run(bell())
    with pytest.raises(QlensError, match=r"distance in \[0, 1\]"):
        qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, test="tvd", tolerance=1.5)
    # 1.0 is a legal distance where it would be an illegal p-value.
    qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, test="tvd", tolerance=1.0)


def test_tvd_rejects_a_distribution_that_is_far_away() -> None:
    result = qlens.run(bell())
    with pytest.raises(QlensAssertionError, match="total variation distance"):
        qlens.assert_distribution(
            result, {"01": 0.5, "10": 0.5}, test="tvd", tolerance=0.1, seed=0
        )


def test_p_value_tolerance_still_bounded() -> None:
    result = qlens.run(bell())
    with pytest.raises(QlensError, match=r"tolerance must be in \(0, 1\)"):
        qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, tolerance=1.0)


# -- the policy reaches the assertion ----------------------------------


def test_sparse_data_warns_through_the_assertion() -> None:
    result = qlens.run(bell())
    heavy = {"00": 0.5, "01": 0.4999, "10": 0.0001, "11": 0.0}
    with (
        pytest.warns(qlens.QlensStatisticsWarning, match="chi_square_exact"),
        pytest.raises(QlensAssertionError),
    ):
        qlens.assert_distribution(result, heavy, test="chi_square", seed=0)


def test_error_policy_stops_the_assertion() -> None:
    config.configure(on_unreliable_statistics="error")
    result = qlens.run(bell())
    heavy = {"00": 0.5, "01": 0.4999, "10": 0.0001, "11": 0.0}
    with pytest.raises(QlensError, match="wrong in either direction"):
        qlens.assert_distribution(result, heavy, test="chi_square", seed=0)


def test_exact_test_never_warns_about_sparseness() -> None:
    """It has no cell-count assumption to violate."""
    import warnings

    config.configure(resamples=200)
    result = qlens.run(bell())
    heavy = {"00": 0.5, "01": 0.4999, "10": 0.0001, "11": 0.0}
    with warnings.catch_warnings():
        warnings.simplefilter("error", qlens.QlensStatisticsWarning)
        with pytest.raises(QlensAssertionError):
            qlens.assert_distribution(
                result, heavy, test="chi_square_exact", seed=0
            )


# -- what reaches the trace --------------------------------------------


def test_the_recorded_position_is_the_one_the_assertion_named(tmp_path: Any) -> None:
    """The whole point of `at=` for the viewer: a check made at position
    0 has to mark position 0, not the end of the run."""
    import json

    from traceact import JsonlSink, TraceConfig, configure, reset_config

    from qlens import tracing

    source = tmp_path / "traces.jsonl"
    configure(config=TraceConfig(sink_mode="blocking"), sinks=[JsonlSink(str(source))])
    tracing.configure(state_dir=str(tmp_path / "qstates"))
    try:
        result = qlens.run(bell(), trace=True)
        qlens.assert_distribution(result, {"00": 0.5, "10": 0.5}, at=0, seed=0)
        qlens.assert_state(result, [SQ2, 0, 0, SQ2], at=1)
        qlens.assert_distribution(result, {"00": 0.5, "11": 0.5}, seed=0)
        tracing.finish_traces()
    finally:
        reset_config()
        tracing.configure(state_dir="data/qstates", project=None, correlation_id=None)

    record = [json.loads(line) for line in source.read_text().splitlines()][-1]
    recorded = [
        (e["assertion"], e.get("position"), e.get("method"))
        for e in record["events"]
        if e["kind"] == "assertion"
    ]
    assert recorded == [
        ("assert_distribution", 0, "chi_square"),
        ("assert_state", 1, "fidelity"),
        ("assert_distribution", 1, "chi_square"),
    ]

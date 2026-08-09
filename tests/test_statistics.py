"""The distribution tests and their reliability checks.

The point of this module is the cases where a test returns a
confident-looking number that means nothing: distributions concentrated
on a few outcomes, tolerances finer than sampling noise, outcomes an
expectation calls impossible. Agreement on easy data is checked last.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pytest

from qlens import _config as config
from qlens import _reliability as reliability
from qlens._errors import QlensError
from qlens._reliability import QlensStatisticsWarning
from qlens._stats import (
    chi_square_exact_test,
    chi_square_test,
    sparse_cells,
    state_fidelity,
    total_variation_distance,
    tvd_noise_floor,
)

# One dominant outcome and a long tail of rare ones: the shape that
# breaks the asymptotic p-value, and the shape real circuits produce.
HEAVY_TAIL = {
    "00": 0.9,
    "01": 0.0999,
    "10": 0.0001,
    "11": 0.00001,
}


@pytest.fixture(autouse=True)
def _default_settings() -> Any:
    config.reset()
    yield
    config.reset()


def draw(probabilities: dict[str, float], shots: int, seed: int) -> dict[str, int]:
    """Counts sampled from a distribution, the way a correct circuit would."""
    labels = sorted(probabilities)
    weights = np.array([probabilities[k] for k in labels], dtype=float)
    weights = weights / weights.sum()
    counts = np.random.default_rng(seed).multinomial(shots, weights)
    return {label: int(count) for label, count in zip(labels, counts, strict=True) if count}


# -- the failure this whole feature exists for -------------------------


def test_asymptotic_p_value_is_unstable_on_a_heavy_tail() -> None:
    """The motivating defect: on sparse data the chi-square p-value
    swings across orders of magnitude on the sampling seed alone, so it
    both flakes and misses errors. Nothing fixes this in-place; the
    remedy is to use a different test, which is why the reliability
    machinery exists."""
    pvalues = [chi_square_test(draw(HEAVY_TAIL, 1024, s), HEAVY_TAIL)[1] for s in range(30)]
    assert min(pvalues) < 0.05 < max(pvalues)
    # Correct data, yet it would fail a 0.05-level assertion sometimes.
    assert sum(p < 0.05 for p in pvalues) > 1


def test_exact_p_value_is_stable_on_the_same_data() -> None:
    """The simulated p-value makes no asymptotic assumption, so correct
    data passes at close to the nominal rate instead of at random."""
    pvalues = [
        chi_square_exact_test(draw(HEAVY_TAIL, 1024, s), HEAVY_TAIL, resamples=2000, seed=0)[1]
        for s in range(30)
    ]
    assert sum(p < 0.05 for p in pvalues) <= 3  # nominal is ~1.5 of 30


def test_tvd_is_stable_on_the_same_data() -> None:
    distances = [
        total_variation_distance(draw(HEAVY_TAIL, 1024, s), HEAVY_TAIL) for s in range(30)
    ]
    assert max(distances) < 0.05  # correct data never drifts far


# -- reliability verdicts ---------------------------------------------


def test_sparse_cells_counts_what_is_under_the_threshold() -> None:
    counts = draw(HEAVY_TAIL, 1024, 0)
    below, live, smallest = sparse_cells(counts, HEAVY_TAIL, 5.0)
    # 0.0001 and 0.00001 of 1024 shots are both far under 5.
    assert below == 2
    assert live == 4
    assert smallest == pytest.approx(1024 * 0.00001 / sum(HEAVY_TAIL.values()), rel=1e-6)


def test_sparse_cells_ignores_outcomes_with_no_expectation() -> None:
    """An outcome given zero probability is not a thinly populated cell,
    it is an excluded one. Counting it would report every expectation
    that omits an outcome as unreliable."""
    expected = {"00": 0.5, "01": 0.5, "10": 0.0, "11": 0.0}
    below, live, _ = sparse_cells({"00": 512, "01": 512}, expected, 5.0)
    assert (below, live) == (0, 2)


def test_sparse_verdict_names_the_alternatives() -> None:
    verdict = reliability.sparse_chi_square(2, 4, 0.01, 5.0)
    assert not verdict.reliable
    assert verdict.code == "sparse_cells"
    assert "chi_square_exact" in " ".join(verdict.remedies)
    assert "tvd" in " ".join(verdict.remedies)
    assert verdict.detail["cells_below_threshold"] == 2


def test_well_populated_data_is_reported_reliable() -> None:
    uniform = {"00": 0.25, "01": 0.25, "10": 0.25, "11": 0.25}
    below, live, smallest = sparse_cells(draw(uniform, 1024, 0), uniform, 5.0)
    assert below == 0
    assert reliability.sparse_chi_square(below, live, smallest, 5.0).reliable


def test_tolerance_under_the_noise_floor_is_flagged() -> None:
    uniform = {"00": 0.5, "11": 0.5}
    floor = tvd_noise_floor(uniform, 1024, resamples=2000, seed=0)
    assert floor > 0  # sampling never reproduces a distribution exactly
    verdict = reliability.tolerance_below_noise(floor / 10, floor, 1024)
    assert not verdict.reliable
    assert verdict.code == "tolerance_below_noise"
    assert reliability.tolerance_below_noise(floor * 2, floor, 1024).reliable


def test_noise_floor_falls_as_shots_rise() -> None:
    uniform = {format(i, "03b"): 0.125 for i in range(8)}
    low = tvd_noise_floor(uniform, 256, resamples=2000, seed=0)
    high = tvd_noise_floor(uniform, 16384, resamples=2000, seed=0)
    assert high < low / 2


# -- policies ----------------------------------------------------------


def test_warn_policy_raises_a_warning_naming_the_remedies() -> None:
    verdict = reliability.sparse_chi_square(2, 4, 0.01, 5.0)
    with pytest.warns(QlensStatisticsWarning, match="chi_square_exact"):
        reliability.report(verdict, "warn", "assert_distribution")


def test_error_policy_refuses_the_result() -> None:
    verdict = reliability.sparse_chi_square(2, 4, 0.01, 5.0)
    with pytest.raises(QlensError, match="wrong in either direction"):
        reliability.report(verdict, "error", "assert_distribution")


def test_ignore_policy_is_silent() -> None:
    verdict = reliability.sparse_chi_square(2, 4, 0.01, 5.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        reliability.report(verdict, "ignore", "assert_distribution")


def test_a_reliable_verdict_never_reports() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        reliability.report(reliability.RELIABLE, "error", "assert_distribution")


# -- degenerate inputs -------------------------------------------------


def test_impossible_outcome_rejects_under_both_chi_square_tests() -> None:
    counts = {"00": 500, "11": 500}
    expected = {"00": 1.0}
    for statistic, pvalue in (
        chi_square_test(counts, expected),
        chi_square_exact_test(counts, expected, resamples=200, seed=0),
    ):
        assert pvalue == 0.0
        assert statistic == float("inf")


def test_exact_p_value_is_never_exactly_zero_otherwise() -> None:
    """A simulated p-value of 0 would claim more certainty than the
    number of resamples supports."""
    counts = {"00": 1024}
    expected = {"00": 0.5, "11": 0.5}
    _, pvalue = chi_square_exact_test(counts, expected, resamples=200, seed=0)
    assert 0 < pvalue <= 1 / 201


def test_empty_counts_rejected() -> None:
    for fn in (chi_square_test, chi_square_exact_test, total_variation_distance):
        with pytest.raises(ValueError, match="nothing to test"):
            fn({}, {"00": 1.0})


def test_expectation_with_no_mass_rejected() -> None:
    for fn in (chi_square_test, chi_square_exact_test, total_variation_distance):
        with pytest.raises(ValueError, match="no positive mass"):
            fn({"00": 10}, {"00": 0.0})


def test_tvd_bounds() -> None:
    assert total_variation_distance({"00": 10}, {"00": 1.0}) == pytest.approx(0.0)
    # No overlap at all is the maximum distance.
    assert total_variation_distance({"00": 10}, {"11": 1.0}) == pytest.approx(1.0)


def test_tvd_accepts_relative_weights() -> None:
    """Callers may pass counts or weights rather than probabilities."""
    counts = {"00": 500, "11": 500}
    assert total_variation_distance(counts, {"00": 3, "11": 3}) == pytest.approx(0.0)


# -- fidelity ----------------------------------------------------------


def test_fidelity_ignores_global_phase() -> None:
    state = np.array([1, 1], dtype=np.complex128) / np.sqrt(2)
    assert state_fidelity(state, state * np.exp(1j * 1.234)) == pytest.approx(1.0)


def test_fidelity_normalizes_its_inputs() -> None:
    """A stored statevector can carry a small norm error, and a caller's
    expected state is often written unnormalized. Scaling must not change
    the verdict, which is only true if both sides are normalized."""
    state = np.array([1, 1], dtype=np.complex128)
    assert state_fidelity(state, state) == pytest.approx(1.0)
    assert state_fidelity(state * 7, state * 0.001) == pytest.approx(1.0)
    half = np.array([1, 0], dtype=np.complex128)
    assert state_fidelity(state * 3, half) == pytest.approx(0.5)


def test_fidelity_of_orthogonal_states_is_zero() -> None:
    assert state_fidelity(
        np.array([1, 0], dtype=np.complex128), np.array([0, 1], dtype=np.complex128)
    ) == pytest.approx(0.0)


def test_fidelity_is_sensitive_to_relative_phase() -> None:
    """Relative phase is physical, unlike global phase, and a check that
    missed it would pass states no measurement basis can equate.

    The pair is deliberately complex: with real amplitudes the overlap
    is the same whether or not the first argument is conjugated, so a
    plain dot product would look correct here."""
    plus_i = np.array([1, 1j], dtype=np.complex128) / np.sqrt(2)
    minus_i = np.array([1, -1j], dtype=np.complex128) / np.sqrt(2)
    assert state_fidelity(plus_i, minus_i) == pytest.approx(0.0)
    # Conjugating the wrong side would report these as identical.
    assert state_fidelity(plus_i, plus_i) == pytest.approx(1.0)


def test_fidelity_of_a_zero_vector_is_zero_not_a_division_error() -> None:
    assert state_fidelity(np.zeros(2, dtype=np.complex128), np.array([1, 0], dtype=np.complex128)) == 0.0

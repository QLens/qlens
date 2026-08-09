"""Statistical tests and linear-algebra helpers shared across backends.

Everything here is framework-neutral: plain numpy/scipy over canonical
Qlens shapes (big-endian counts dicts, big-endian matrices).
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import numpy.typing as npt
from scipy import stats


def phase_invariant_allclose(
    a: npt.NDArray[np.complex128],
    b: npt.NDArray[np.complex128],
    *,
    atol: float,
) -> bool:
    """Whether two matrices are equal up to a global complex phase.

    Aligns the phases using the largest-magnitude entry of ``a`` (robust
    against zero entries), then compares elementwise. Shapes must match.
    """
    if a.shape != b.shape:
        return False
    idx = np.unravel_index(np.argmax(np.abs(a)), a.shape)
    if np.abs(a[idx]) < atol or np.abs(b[idx]) < atol:
        # a is (numerically) the zero matrix, or b is zero where a is not.
        return bool(np.allclose(a, b, atol=atol))
    phase = b[idx] / a[idx]
    phase /= np.abs(phase)
    return bool(np.allclose(a * phase, b, atol=atol))


def max_unitarity_deviation(matrix: npt.NDArray[np.complex128]) -> float:
    """Largest absolute deviation of U†U from the identity."""
    product = matrix.conj().T @ matrix
    return float(np.max(np.abs(product - np.eye(matrix.shape[0]))))


def chi_square_test(
    counts: Mapping[str, int],
    expected: Mapping[str, float],
) -> tuple[float, float]:
    """Chi-square goodness-of-fit test of observed counts against an
    expected probability distribution. Returns (statistic, p-value).

    ``expected`` maps bitstrings to probabilities (normalized here, so
    relative weights are accepted). Outcomes observed but absent from
    ``expected`` get probability zero, which is an automatic reject
    (p=0.0) if they carry any counts — a state the expectation says is
    impossible appeared. The statistic is infinite in that case: the
    contribution of a nonzero count against a zero expectation diverges.
    """
    total_shots = sum(counts.values())
    if total_shots == 0:
        raise ValueError("counts is empty; nothing to test")
    norm = sum(expected.values())
    if norm <= 0:
        raise ValueError("expected distribution has no positive mass")

    outcomes = sorted(set(counts) | set(expected))
    observed = np.array([counts.get(o, 0) for o in outcomes], dtype=float)
    probabilities = np.array([expected.get(o, 0.0) / norm for o in outcomes], dtype=float)

    impossible = (probabilities == 0.0) & (observed > 0)
    if impossible.any():
        return float("inf"), 0.0
    # Drop zero-probability outcomes (all unobserved by now) — they
    # contribute nothing and break the chi-square denominator.
    keep = probabilities > 0.0
    observed, probabilities = observed[keep], probabilities[keep]
    if len(observed) == 1:
        # Single possible outcome and all counts landed on it.
        return 0.0, 1.0
    result = stats.chisquare(f_obs=observed, f_exp=probabilities * total_shots)
    return float(result.statistic), float(result.pvalue)


def chi_square_pvalue(
    counts: Mapping[str, int],
    expected: Mapping[str, float],
) -> float:
    """p-value alone from :func:`chi_square_test`."""
    return chi_square_test(counts, expected)[1]


def ks_test(
    samples: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64] | str,
    reference_args: tuple[float, ...] = (),
) -> tuple[float, float]:
    """Kolmogorov-Smirnov test. Returns (statistic, p-value).

    Two-sample when ``reference`` is an array of samples; one-sample
    against a named scipy distribution (e.g. "uniform", "norm") when it
    is a string, with ``reference_args`` passed through as the
    distribution's parameters.
    """
    if isinstance(reference, str):
        result = stats.kstest(samples, reference, args=reference_args)
    else:
        result = stats.ks_2samp(samples, reference)
    return float(result.statistic), float(result.pvalue)


def ks_pvalue(
    samples: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64] | str,
    reference_args: tuple[float, ...] = (),
) -> float:
    """p-value alone from :func:`ks_test`."""
    return ks_test(samples, reference, reference_args)[1]


def _aligned(
    counts: Mapping[str, int], expected: Mapping[str, float]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64], int]:
    """Observed counts and expected probabilities over a shared outcome
    list, plus the shot total. Outcomes in either mapping appear in both."""
    total = sum(counts.values())
    if total == 0:
        raise ValueError("counts is empty; nothing to test")
    norm = sum(expected.values())
    if norm <= 0:
        raise ValueError("expected distribution has no positive mass")
    outcomes = sorted(set(counts) | set(expected))
    observed = np.array([counts.get(o, 0) for o in outcomes], dtype=np.float64)
    probabilities = np.array(
        [expected.get(o, 0.0) / norm for o in outcomes], dtype=np.float64
    )
    return observed, probabilities, total


def _chi_square_statistic(
    observed: npt.NDArray[np.float64], expected_counts: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Pearson statistic, summed over the last axis so a whole batch of
    simulated tables reduces in one pass."""
    keep = expected_counts > 0
    difference = observed[..., keep] - expected_counts[keep]
    return np.sum(difference * difference / expected_counts[keep], axis=-1)


def chi_square_exact_test(
    counts: Mapping[str, int],
    expected: Mapping[str, float],
    *,
    resamples: int = 10_000,
    seed: int | None = None,
) -> tuple[float, float]:
    """Chi-square statistic with a simulated p-value. Returns
    (statistic, p-value).

    The p-value comes from drawing ``resamples`` tables from ``expected``
    at the same shot count and asking how often they produce a statistic
    at least as extreme as the observed one. That holds whatever the
    expected counts are, where the usual chi-square reference
    distribution needs every cell to be reasonably well populated.

    An outcome observed but given zero probability still rejects
    outright: no simulated table can ever produce it.
    """
    observed, probabilities, total = _aligned(counts, expected)
    if ((probabilities == 0.0) & (observed > 0)).any():
        return float("inf"), 0.0

    expected_counts = probabilities * total
    statistic = float(_chi_square_statistic(observed, expected_counts))

    rng = np.random.default_rng(seed)
    simulated = rng.multinomial(total, probabilities, size=resamples).astype(np.float64)
    null = _chi_square_statistic(simulated, expected_counts)
    # The observed table counts as one of its own reference draws, which
    # keeps the p-value from ever being reported as exactly zero.
    pvalue = float((np.count_nonzero(null >= statistic) + 1) / (resamples + 1))
    return statistic, pvalue


def total_variation_distance(
    counts: Mapping[str, int], expected: Mapping[str, float]
) -> float:
    """Half the summed absolute difference between the observed and
    expected distributions, in [0, 1].

    0 is identical, 1 is no overlap. Unlike a p-value this is a distance:
    0.02 means the two distributions disagree about 2% of their mass, at
    any number of outcomes and any shot count.
    """
    observed, probabilities, total = _aligned(counts, expected)
    return float(0.5 * np.sum(np.abs(observed / total - probabilities)))


def tvd_noise_floor(
    expected: Mapping[str, float],
    shots: int,
    *,
    resamples: int = 10_000,
    seed: int | None = None,
    quantile: float = 0.95,
) -> float:
    """How large a TVD sampling alone produces, at this shot count.

    Finite sampling never reproduces a distribution perfectly, so even a
    correct circuit lands some distance from its expectation. A tolerance
    below this floor rejects correct circuits most of the time, which is
    what makes it worth reporting alongside the measured distance.
    """
    norm = sum(expected.values())
    if norm <= 0:
        raise ValueError("expected distribution has no positive mass")
    probabilities = np.array(
        [v / norm for v in expected.values()], dtype=np.float64
    )
    rng = np.random.default_rng(seed)
    simulated = rng.multinomial(shots, probabilities, size=resamples) / shots
    distances = 0.5 * np.sum(np.abs(simulated - probabilities), axis=-1)
    return float(np.quantile(distances, quantile))


def sparse_cells(
    counts: Mapping[str, int], expected: Mapping[str, float], threshold: float
) -> tuple[int, int, float]:
    """How badly a chi-square's assumptions are strained by this data.

    Returns (cells below the threshold, cells with any expectation, the
    smallest nonzero expected count).
    """
    _, probabilities, total = _aligned(counts, expected)
    expected_counts = probabilities * total
    live = expected_counts[expected_counts > 0]
    if live.size == 0:
        return 0, 0, 0.0
    return int(np.count_nonzero(live < threshold)), int(live.size), float(live.min())


def state_fidelity(
    a: npt.NDArray[np.complex128], b: npt.NDArray[np.complex128]
) -> float:
    """|<a|b>|^2 for two statevectors, in [0, 1].

    Global phase cancels in the modulus, so two states that differ only
    by an overall phase factor score 1.0. They are the same physical
    state, and no measurement can tell them apart.
    """
    overlap = complex(np.vdot(a, b))
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm == 0:
        return 0.0
    return float(abs(overlap / norm) ** 2)

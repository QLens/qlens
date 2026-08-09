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

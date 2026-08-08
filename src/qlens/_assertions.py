"""The assert_* testing API.

Each assertion auto-detects the backend from the circuit object via the
registry, so tests never name a backend explicitly. Failures raise
QlensAssertionError (an AssertionError subclass) with the measured
numbers in the message.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import numpy as np

from qlens._errors import QlensAssertionError, QlensError
from qlens._execution import ExecutionResult
from qlens._stats import chi_square_pvalue, ks_pvalue, max_unitarity_deviation
from qlens.backends._registry import detect_backend

DEFAULT_ATOL = 1e-8
DEFAULT_SHOTS = 1024


def assert_unitary(
    circuit: Any, *, atol: float = DEFAULT_ATOL, args: tuple[Any, ...] = ()
) -> None:
    """Assert the circuit's operation is unitary within tolerance."""
    backend = detect_backend(circuit)
    matrix = backend.operator_matrix(circuit, args=args)
    deviation = max_unitarity_deviation(matrix)
    if deviation > atol:
        raise QlensAssertionError(
            f"circuit is not unitary: max deviation of U†U from identity is "
            f"{deviation:.3e} (atol={atol:.1e})"
        )


def assert_equivalent(
    circuit_a: Any,
    circuit_b: Any,
    *,
    atol: float = DEFAULT_ATOL,
    args: tuple[Any, ...] = (),
) -> None:
    """Assert two circuits compute the same unitary up to global phase.

    Both circuits must come from the same framework; cross-framework
    equivalence is out of scope for Phase 1.
    """
    backend_a = detect_backend(circuit_a)
    backend_b = detect_backend(circuit_b)
    if backend_a.name != backend_b.name:
        raise QlensError(
            f"cannot compare circuits across frameworks ({backend_a.name} vs "
            f"{backend_b.name}); build both circuits in one framework"
        )
    if not backend_a.equivalent(circuit_a, circuit_b, atol=atol, args=args):
        raise QlensAssertionError(
            "circuits are not equivalent: their unitaries differ beyond "
            f"atol={atol:.1e} (up to global phase)"
        )


def assert_distribution(
    result: ExecutionResult | Mapping[str, int] | Any,
    expected: Mapping[str, float] | str,
    *,
    tolerance: float = 0.05,
    test: Literal["chi_square", "ks"] = "chi_square",
    shots: int = DEFAULT_SHOTS,
    reference_args: tuple[float, ...] = (),
) -> None:
    """Assert sampled output matches an expected distribution.

    ``result``: an ExecutionResult (counts drawn lazily at ``shots``), a
    raw counts mapping, or, for the KS test, an array of continuous
    samples.

    ``expected``: a mapping of big-endian bitstrings to probabilities (or
    relative weights) for the chi-square test; for the KS test, either an
    array of reference samples or a scipy distribution name (with
    ``reference_args``).

    ``tolerance`` is the significance level: the assertion passes when
    the test's p-value is >= tolerance, i.e. the data gives no grounds at
    that level to reject "output matches expected." Smaller tolerance =
    laxer test. See USAGE.md for choosing between chi_square and ks.
    """
    if not 0.0 < tolerance < 1.0:
        raise QlensError(f"tolerance must be in (0, 1), got {tolerance}")

    if test == "chi_square":
        if not isinstance(expected, Mapping):
            raise QlensError(
                "chi_square expects a mapping of bitstrings to probabilities; "
                "for continuous references use test='ks'"
            )
        counts = _as_counts(result, shots)
        pvalue = chi_square_pvalue(counts, expected)
    elif test == "ks":
        if isinstance(result, ExecutionResult) or isinstance(result, Mapping):
            raise QlensError(
                "ks compares continuous samples; pass an array of samples as "
                "result (for counts use test='chi_square')"
            )
        samples = np.asarray(result, dtype=np.float64)
        if isinstance(expected, Mapping):
            raise QlensError(
                "ks expects an array of reference samples or a scipy "
                "distribution name as expected"
            )
        pvalue = ks_pvalue(samples, expected, reference_args)
    else:
        raise QlensError(f"unknown test {test!r}; use 'chi_square' or 'ks'")

    if pvalue < tolerance:
        raise QlensAssertionError(
            f"distribution mismatch: {test} p-value {pvalue:.4g} < "
            f"significance level {tolerance}"
        )


def _as_counts(result: ExecutionResult | Mapping[str, int] | Any, shots: int) -> dict[str, int]:
    if isinstance(result, ExecutionResult):
        return result.counts(shots)
    if isinstance(result, Mapping):
        return dict(result)
    raise QlensError(
        f"cannot extract counts from {type(result).__qualname__}; pass an "
        "ExecutionResult or a mapping of bitstrings to counts"
    )

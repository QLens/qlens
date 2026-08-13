"""The assert_* testing API.

Each assertion auto-detects the backend from the circuit object via the
registry, so tests never name a backend explicitly. Failures raise
QlensAssertionError (an AssertionError subclass) with the measured
numbers in the message.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from qlens import _config as config
from qlens import _reliability as reliability
from qlens._errors import QlensAssertionError, QlensError
from qlens._execution import ExecutionResult
from qlens._stats import (
    chi_square_exact_test,
    chi_square_test,
    ks_test,
    max_unitarity_deviation,
    sparse_cells,
    state_fidelity,
    subsystem_purity,
    total_variation_distance,
    tvd_noise_floor,
)
from qlens.backends._registry import detect_backend

DEFAULT_ATOL = 1e-8
DEFAULT_SHOTS = 1024
DEFAULT_TOLERANCE = 0.05
DEFAULT_FIDELITY = 0.99
# How far a subsystem's purity may sit below 1 and still count as a
# product state. Simulator arithmetic is exact up to floating point, so
# this only absorbs accumulated rounding across a long circuit, not
# physical noise.
DEFAULT_PURITY_ATOL = 1e-9


def assert_unitary(
    circuit: Any, *, atol: float = DEFAULT_ATOL, args: tuple[Any, ...] = ()
) -> None:
    """Assert the circuit's operation is unitary within tolerance."""
    backend = detect_backend(circuit)
    matrix = backend.operator_matrix(circuit, args=args)
    deviation = max_unitarity_deviation(matrix)
    details = {"deviation": float(deviation), "atol": float(atol)}
    if deviation > atol:
        error = QlensAssertionError(
            f"circuit is not unitary: max deviation of U†U from identity is "
            f"{deviation:.3e} (atol={atol:.1e})"
        )
        _record(None, "assert_unitary", "unitarity", error, details=details)
        raise error
    _record(None, "assert_unitary", "unitarity", None, details=details)


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
    details = {"atol": float(atol)}
    if not backend_a.equivalent(circuit_a, circuit_b, atol=atol, args=args):
        error = QlensAssertionError(
            "circuits are not equivalent: their unitaries differ beyond "
            f"atol={atol:.1e} (up to global phase)"
        )
        _record(None, "assert_equivalent", "equivalence", error, details=details)
        raise error
    _record(None, "assert_equivalent", "equivalence", None, details=details)


def assert_distribution(
    result: ExecutionResult | Mapping[str, int] | Any,
    expected: Mapping[str, float] | str,
    *,
    tolerance: float | None = None,
    test: str | None = None,
    shots: int = DEFAULT_SHOTS,
    seed: int | None = None,
    at: int | None = None,
    reference_args: tuple[float, ...] = (),
) -> None:
    """Assert sampled output matches an expected distribution.

    ``result``: an ExecutionResult (counts drawn lazily at ``shots``), a
    raw counts mapping, or, for the KS test, an array of continuous
    samples.

    ``expected``: a mapping of big-endian bitstrings to probabilities (or
    relative weights) for the discrete tests; for the KS test, either an
    array of reference samples or a scipy distribution name (with
    ``reference_args``).

    ``at``: measure the state captured after that gate position instead
    of the circuit's final state. The assertion then marks that position
    in the viewer's timeline rather than the end of the run.

    ``test`` picks how the comparison is made, defaulting to the project
    setting (see qlens.configure):

    ==================  =======================================================
    chi_square          Pearson's test. Its p-value assumes every outcome is
                        expected several times over.
    chi_square_exact    The same statistic with the p-value simulated rather
                        than looked up, which holds however rare an outcome is.
    tvd                 Total variation distance. ``tolerance`` becomes a
                        distance in [0, 1] rather than a significance level.
    ks                  Kolmogorov-Smirnov, for continuous samples.
    ==================  =======================================================

    ``tolerance`` means whichever the chosen test uses, and defaults
    accordingly: a significance level of 0.05 for the p-value tests,
    a distance of 0.05 for tvd. Qlens never changes ``test`` on your
    behalf; when the chosen one's assumptions do not hold for the data,
    it says so through ``on_unreliable_statistics``.
    """
    method = test if test is not None else config.settings.distribution_test
    if method not in ("chi_square", "chi_square_exact", "tvd", "ks"):
        raise QlensError(
            f"unknown test {method!r}; use chi_square, chi_square_exact, tvd, or ks"
        )
    if tolerance is None:
        tolerance = DEFAULT_TOLERANCE
    if method == "tvd":
        if not 0.0 <= tolerance <= 1.0:
            raise QlensError(
                f"tvd tolerance is a distance in [0, 1], got {tolerance}"
            )
    elif not 0.0 < tolerance < 1.0:
        raise QlensError(f"tolerance must be in (0, 1), got {tolerance}")

    if method == "ks":
        _assert_ks(result, expected, tolerance, reference_args)
        return
    _assert_discrete(result, expected, method, tolerance, shots, seed, at)


def _assert_discrete(
    result: Any,
    expected: Mapping[str, float] | str,
    method: str,
    tolerance: float,
    shots: int,
    seed: int | None,
    at: int | None,
) -> None:
    if not isinstance(expected, Mapping):
        raise QlensError(
            f"{method} expects a mapping of bitstrings to probabilities; "
            "for continuous references use test='ks'"
        )
    counts = _as_counts(result, shots, seed, at)
    resamples = config.settings.resamples

    if method == "tvd":
        distance = total_variation_distance(counts, expected)
        floor = tvd_noise_floor(expected, sum(counts.values()), resamples=resamples, seed=seed)
        verdict = reliability.tolerance_below_noise(tolerance, floor, sum(counts.values()))
        passed = distance <= tolerance
        details = {
            "distance": distance,
            "tolerance": tolerance,
            "noise_floor": floor,
            "shots": float(sum(counts.values())),
        }
        message = (
            f"distribution mismatch: total variation distance {distance:.4g} > "
            f"tolerance {tolerance:g}"
        )
    else:
        if method == "chi_square_exact":
            statistic, pvalue = chi_square_exact_test(
                counts, expected, resamples=resamples, seed=seed
            )
            verdict = reliability.RELIABLE
        else:
            statistic, pvalue = chi_square_test(counts, expected)
            below, live, smallest = sparse_cells(
                counts, expected, config.settings.min_expected_count
            )
            verdict = reliability.sparse_chi_square(
                below, live, smallest, config.settings.min_expected_count
            )
        passed = pvalue >= tolerance
        details = {
            "statistic": statistic,
            "p_value": pvalue,
            "tolerance": tolerance,
            "shots": float(sum(counts.values())),
        }
        message = (
            f"distribution mismatch: {method} p-value {pvalue:.4g} < "
            f"significance level {tolerance}"
        )

    reliability.report(verdict, config.settings.on_unreliable_statistics, "assert_distribution")
    _finish(
        result, "assert_distribution", "distribution", message if not passed else None,
        details=details, expected=expected, at=at, method=method, verdict=verdict,
    )


def _assert_ks(
    result: Any,
    expected: Mapping[str, float] | str,
    tolerance: float,
    reference_args: tuple[float, ...],
) -> None:
    if isinstance(result, (ExecutionResult, Mapping)):
        raise QlensError(
            "ks compares continuous samples; pass an array of samples as "
            "result (for counts use a discrete test)"
        )
    if isinstance(expected, Mapping):
        raise QlensError(
            "ks expects an array of reference samples or a scipy "
            "distribution name as expected"
        )
    samples = np.asarray(result, dtype=np.float64)
    statistic, pvalue = ks_test(samples, expected, reference_args)
    details = {"statistic": statistic, "p_value": pvalue, "tolerance": tolerance}
    message = (
        f"distribution mismatch: ks p-value {pvalue:.4g} < "
        f"significance level {tolerance}"
    )
    _finish(
        result, "assert_distribution", "distribution",
        message if pvalue < tolerance else None,
        details=details, expected=None, at=None, method="ks",
        verdict=reliability.RELIABLE,
    )


def assert_state(
    result: ExecutionResult,
    expected: Any,
    *,
    fidelity: float = DEFAULT_FIDELITY,
    at: int | None = None,
) -> None:
    """Assert the captured statevector matches an expected one.

    Compared by fidelity |<expected|actual>|^2, which ignores global
    phase: two states differing only by an overall phase factor are the
    same physical state and score 1.0.

    ``at`` picks the gate position to compare, defaulting to the end of
    the run, and is where the viewer marks the assertion.
    """
    if not 0.0 < fidelity <= 1.0:
        raise QlensError(f"fidelity must be in (0, 1], got {fidelity}")
    actual = result.statevector_at(at if at is not None else -1)
    reference = np.asarray(expected, dtype=np.complex128)
    if reference.shape != actual.shape:
        raise QlensError(
            f"expected state has {reference.size} amplitudes but the circuit "
            f"has {actual.size}; both must cover the same qubit count"
        )
    measured = state_fidelity(reference, actual)
    details = {"fidelity": measured, "required": float(fidelity)}
    message = (
        f"statevector mismatch: fidelity {measured:.4f} < required {fidelity:.4f}"
    )
    _finish(
        result, "assert_state", "state", message if measured < fidelity else None,
        details=details, expected=None, at=at, method="fidelity",
        verdict=reliability.RELIABLE,
    )


def assert_separable(
    result: ExecutionResult,
    qubits: Sequence[int],
    *,
    atol: float = DEFAULT_PURITY_ATOL,
    at: int | None = None,
) -> None:
    """Assert ``qubits`` carry no correlation with the rest of the register.

    A structural check: it asserts a property rather than a value, so it
    needs no expected statevector. That matters for the case it exists
    for — an ancilla that wasn't uncomputed. Mirroring a computation back
    is what returns a scratch qubit to the rest of the circuit, and when
    the mirror is missing the ancilla stays entangled with the data. The
    interference the algorithm depends on is then destroyed, and the only
    symptom at the end of the run is an answer that has gone from certain
    to a coin flip.

    Measured as the purity of the subsystem after tracing out the rest.
    Exactly 1 is a product state; below 1 is entanglement.

    ``at`` picks the gate position to check, defaulting to the end of the
    run, and is where the viewer marks the assertion. Checking an ancilla
    at the position it should have been released names the gate that
    should have released it, rather than the far end of the circuit where
    the symptom appears.
    """
    purity, count = _purity_at(result, qubits, at)
    details = {"purity": purity, "atol": float(atol), "qubits": float(count)}
    failure = None
    if purity < 1.0 - atol:
        names = ", ".join(f"q{q}" for q in sorted(qubits))
        failure = (
            f"{names} still entangled with the rest of the register: purity "
            f"{purity:.6f} < 1 (tolerance {atol:g}). An ancilla that was not "
            f"uncomputed leaves exactly this trace"
        )
    _finish(
        result, "assert_separable", "state", failure,
        details=details, expected=None, at=at, method="purity",
        verdict=reliability.RELIABLE,
    )


def assert_entangled(
    result: ExecutionResult,
    qubits: Sequence[int],
    *,
    atol: float = DEFAULT_PURITY_ATOL,
    at: int | None = None,
) -> None:
    """Assert ``qubits`` are correlated with the rest of the register.

    The complement of :func:`assert_separable`, and the check for a
    control that never took effect: a multiply-controlled operation whose
    controls are routed wrongly can leave the target unentangled from the
    qubits that were supposed to drive it, which no amount of looking at
    the final distribution makes obvious.

    Passing means the subsystem's purity is below 1, so measuring these
    qubits does say something about the others.
    """
    purity, count = _purity_at(result, qubits, at)
    details = {"purity": purity, "atol": float(atol), "qubits": float(count)}
    failure = None
    if purity >= 1.0 - atol:
        names = ", ".join(f"q{q}" for q in sorted(qubits))
        failure = (
            f"{names} are separable from the rest of the register: purity "
            f"{purity:.6f} is 1 within tolerance {atol:g}, so they carry no "
            f"correlation with it"
        )
    _finish(
        result, "assert_entangled", "state", failure,
        details=details, expected=None, at=at, method="purity",
        verdict=reliability.RELIABLE,
    )


def _purity_at(
    result: ExecutionResult, qubits: Sequence[int], at: int | None
) -> tuple[float, int]:
    """Subsystem purity at a position, with the arguments validated first.

    A subset naming every qubit, or none of them, has nothing on the other
    side to be correlated with, so it is refused rather than answered with
    a purity of 1 that would read as a passing separability check.
    """
    chosen = list(qubits)
    if not chosen:
        raise QlensError("qubits must name at least one qubit")
    unique = sorted(set(chosen))
    if len(unique) != len(chosen):
        raise QlensError(f"qubits contains duplicates: {chosen}")
    total = result.num_qubits
    out_of_range = [q for q in unique if not 0 <= q < total]
    if out_of_range:
        raise QlensError(
            f"qubits {out_of_range} outside the circuit's 0..{total - 1} range"
        )
    if len(unique) == total:
        raise QlensError(
            f"qubits names the whole {total}-qubit register; separability is a "
            f"statement about a subsystem and the rest, so leave at least one out"
        )
    state = result.statevector_at(at if at is not None else -1)
    return subsystem_purity(state, unique, total), len(unique)


def _finish(
    result: Any,
    name: str,
    target: str,
    failure: str | None,
    *,
    details: dict[str, float],
    expected: Mapping[str, float] | None,
    at: int | None,
    method: str,
    verdict: reliability.Reliability,
) -> None:
    """Record the assertion, then raise if it failed."""
    error = QlensAssertionError(failure) if failure is not None else None
    _record(
        result, name, target, error,
        details=details, expected=expected, at=at, method=method, verdict=verdict,
    )
    if error is not None:
        raise error


def _record(
    result: Any,
    name: str,
    target: str,
    error: BaseException | None,
    *,
    details: dict[str, float] | None = None,
    expected: Mapping[str, float] | None = None,
    at: int | None = None,
    method: str | None = None,
    verdict: Any = None,
) -> None:
    """Append an assertion event to the result's open trace or the
    ambient TraceAct trace. Never raises; no-op when nothing is tracing.

    ``details`` carries the measured numbers the viewer's assertion table
    shows; ``expected`` the reference distribution it ghosts behind the
    observed bars.
    """
    from qlens import tracing

    tracing.record_assertion(
        result, name, target, error,
        details=details, expected=expected, at=at, method=method, verdict=verdict,
    )


def _as_counts(
    result: ExecutionResult | Mapping[str, int] | Any,
    shots: int,
    seed: int | None,
    at: int | None = None,
) -> dict[str, int]:
    if isinstance(result, ExecutionResult):
        return result.counts(shots, seed=seed, at=at)
    if at is not None:
        raise QlensError(
            "at= needs an ExecutionResult; a raw counts mapping has no "
            "positions to measure at"
        )
    if isinstance(result, Mapping):
        return dict(result)
    raise QlensError(
        f"cannot extract counts from {type(result).__qualname__}; pass an "
        "ExecutionResult or a mapping of bitstrings to counts"
    )

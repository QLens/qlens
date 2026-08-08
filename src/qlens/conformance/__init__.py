"""Backend conformance suite.

Canonical circuits with reference-computed expectations, public and
importable. A backend implementation certifies by passing
:func:`run_conformance`; Qlens's own backends certify through exactly
this path in their test suites.

A third-party backend author supplies a ``build`` callable that
interprets the neutral gate program for their framework (see
``qlens.conformance._builders`` for the first-party examples)::

    from qlens.conformance import run_conformance
    failures = run_conformance(MyBackend(), build=my_builder)
    assert not failures
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from qlens._stats import chi_square_pvalue, max_unitarity_deviation, phase_invariant_allclose
from qlens.backends.base import Backend
from qlens.conformance._builders import BUILDERS
from qlens.conformance._circuits import (
    CASES,
    EQUIVALENCE_PAIRS,
    ConformanceCase,
    EquivalencePair,
    Program,
)

__all__ = [
    "CASES",
    "EQUIVALENCE_PAIRS",
    "ConformanceCase",
    "EquivalencePair",
    "Program",
    "run_conformance",
]

_STATE_ATOL = 1e-8
_UNITARY_ATOL = 1e-8
# Deliberately loose: a correct backend fails a 0.001-level chi-square
# roughly once per thousand runs per case. Sampling checks guard against
# wrong distributions, not statistical noise.
_SAMPLING_ALPHA = 1e-3
_SAMPLING_SHOTS = 4096


def run_conformance(
    backend: Backend,
    build: Callable[[Program, int], Any] | None = None,
) -> list[str]:
    """Run every conformance check against a backend implementation.

    Returns a list of human-readable failure descriptions; empty means
    the backend conforms. ``build`` interprets a neutral gate program
    into the backend's circuit type; first-party backends resolve their
    bundled builder automatically.
    """
    if build is None:
        if backend.name not in BUILDERS:
            raise ValueError(
                f"no bundled builder for backend {backend.name!r}; pass build="
            )
        build = BUILDERS[backend.name]

    failures: list[str] = []
    for case in CASES:
        failures.extend(_check_case(backend, build, case))
    for pair in EQUIVALENCE_PAIRS:
        failures.extend(_check_pair(backend, build, pair))
    return failures


def _check_case(
    backend: Backend,
    build: Callable[[Program, int], Any],
    case: ConformanceCase,
) -> list[str]:
    failures: list[str] = []
    circuit = build(case.program, case.num_qubits)

    result = backend.run(circuit)
    if result.num_qubits != case.num_qubits:
        failures.append(
            f"{case.name}: run() reported {result.num_qubits} qubits, "
            f"expected {case.num_qubits}"
        )
    if len(result.snapshots) != len(case.program):
        failures.append(
            f"{case.name}: run() captured {len(result.snapshots)} snapshots "
            f"for {len(case.program)} gates"
        )
    final = result.final_statevector
    if not phase_invariant_allclose(
        case.expected_final_state.reshape(-1, 1), final.reshape(-1, 1), atol=_STATE_ATOL
    ):
        failures.append(
            f"{case.name}: final statevector deviates from reference "
            f"(check basis ordering/endianness against CONVENTIONS.md)"
        )

    matrix = backend.operator_matrix(circuit)
    if not phase_invariant_allclose(case.expected_unitary, matrix, atol=_UNITARY_ATOL):
        failures.append(f"{case.name}: operator matrix deviates from reference")
    if max_unitarity_deviation(matrix) > _UNITARY_ATOL:
        failures.append(f"{case.name}: operator matrix is not unitary")
    if not backend.is_unitary(circuit, atol=_UNITARY_ATOL):
        failures.append(f"{case.name}: is_unitary() returned False for a unitary circuit")

    counts = backend.counts(circuit, shots=_SAMPLING_SHOTS)
    if sum(counts.values()) != _SAMPLING_SHOTS:
        failures.append(
            f"{case.name}: counts sum to {sum(counts.values())}, "
            f"expected {_SAMPLING_SHOTS}"
        )
    if any(len(k) != case.num_qubits or set(k) - {"0", "1"} for k in counts):
        failures.append(f"{case.name}: counts keys are not {case.num_qubits}-bit strings")
    elif chi_square_pvalue(counts, case.expected_probabilities) < _SAMPLING_ALPHA:
        failures.append(
            f"{case.name}: sampled distribution deviates from reference "
            f"(check bitstring endianness against CONVENTIONS.md)"
        )
    return failures


def _check_pair(
    backend: Backend,
    build: Callable[[Program, int], Any],
    pair: EquivalencePair,
) -> list[str]:
    circuit_a = build(pair.program_a, pair.num_qubits)
    circuit_b = build(pair.program_b, pair.num_qubits)
    verdict = backend.equivalent(circuit_a, circuit_b, atol=_UNITARY_ATOL)
    if verdict != pair.equivalent:
        expected = "equivalent" if pair.equivalent else "non-equivalent"
        return [f"{pair.name}: equivalent() returned {verdict}, circuits are {expected}"]
    return []

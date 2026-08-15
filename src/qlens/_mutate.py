"""qlens.mutate: mutation testing for quantum circuits.

Mutation testing asks a blunt question of a test suite: if the circuit
were subtly wrong, would the tests notice? :func:`mutate` answers it by
making each change in the bug-pattern catalog (see :mod:`qlens._mutations`)
and running the circuit's own checks against the result. A mutant whose
check fails is *killed*; one whose check passes *survived*, and every
survivor is a bug the suite would let through.

This is where the simulator pays off. On hardware a surviving mutant is
ambiguous: the test might have missed it, or the mutant might compute the
same unitary as the original and be impossible to catch. On a simulator
the two are distinguished, by comparing unitaries up to global phase. An
*equivalent* mutant is set aside rather than counted against the suite,
so the kill score measures the tests, not the arithmetic of which changes
happen to cancel.

The mutant is replayed on Qlens's own canonical simulator
(:mod:`qlens._simulate`), not on the framework that built the circuit, so
one code path mutates Qiskit, PennyLane and Cirq circuits alike, including
the PennyLane circuits that are Python functions with no gate list to edit.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from qlens._errors import QlensAssertionError, QlensError
from qlens._execution import ExecutionResult, Snapshot
from qlens._mutations import Mutation, all_mutations
from qlens._simulate import GateOp, is_supported, simulate, unitary
from qlens._stats import phase_invariant_allclose

# A mutant whose unitary matches the original up to this tolerance is
# treated as equivalent. Loose enough to absorb rounding across a long
# replay, tight enough that a one-gate difference never hides under it.
_EQUIVALENCE_ATOL = 1e-9

Check = Callable[[ExecutionResult], None]


@dataclass(frozen=True)
class MutantResult:
    """One mutant's fate under the test suite."""

    mutation: Mutation
    outcome: str  # "killed" | "survived" | "equivalent"
    detail: str | None = None  # the kill message, when killed

    @property
    def description(self) -> str:
        return self.mutation.description

    @property
    def operator(self) -> str:
        return self.mutation.operator


@dataclass(frozen=True)
class MutationReport:
    """The outcome of a mutation run: what was killed, survived, skipped."""

    results: tuple[MutantResult, ...]

    @property
    def killed(self) -> list[MutantResult]:
        return [r for r in self.results if r.outcome == "killed"]

    @property
    def survived(self) -> list[MutantResult]:
        return [r for r in self.results if r.outcome == "survived"]

    @property
    def equivalent(self) -> list[MutantResult]:
        return [r for r in self.results if r.outcome == "equivalent"]

    @property
    def scored(self) -> int:
        """Mutants the suite was asked to catch (equivalents excluded)."""
        return len(self.killed) + len(self.survived)

    @property
    def score(self) -> float:
        """Fraction of scored mutants the suite killed, in [0, 1].

        Equivalent mutants are excluded from the denominator: no test can
        kill one, so counting it would penalize a suite for arithmetic it
        cannot see. A run with nothing to score is 1.0 by convention.
        """
        return 1.0 if self.scored == 0 else len(self.killed) / self.scored

    def summary(self) -> str:
        return (
            f"mutation score {self.score:.0%}: {len(self.killed)} killed, "
            f"{len(self.survived)} survived, {len(self.equivalent)} equivalent "
            f"(of {len(self.results)} mutants)"
        )


def mutate(
    circuit: Any,
    check: Check,
    *,
    backend: str | None = None,
    args: tuple[Any, ...] = (),
    operators: Sequence[str] | None = None,
    max_mutants: int | None = None,
    seed: int | None = None,
) -> MutationReport:
    """Mutation-test ``circuit`` against its own ``check``.

    ``check`` receives the :class:`~qlens.ExecutionResult` of a mutant and
    asserts what the circuit is supposed to do, the way a test would:
    call ``qlens.assert_state``, ``assert_distribution``, ``assert_separable``
    and the rest against it. An :class:`AssertionError` (which every
    ``qlens.assert_*`` raises on failure) kills the mutant; returning
    without raising means it survived.

    ``operators`` selects which of the four mutation operators to apply
    (default all; see :mod:`qlens._mutations`). ``max_mutants`` caps how
    many are run, sampled deterministically under ``seed`` when the cap
    bites. ``backend`` and ``args`` are forwarded to :func:`qlens.run` for
    the original circuit.

    Every mutant is replayed on Qlens's canonical simulator, so the
    circuit must use only gates that simulator models; a gate outside its
    vocabulary raises rather than being mutated around.
    """
    original = _run(circuit, backend=backend, args=args)
    ops = _ops_from(original)
    num_qubits = original.num_qubits
    reference = unitary(ops, num_qubits)

    mutations = all_mutations(ops, operators)
    if max_mutants is not None and len(mutations) > max_mutants:
        mutations = random.Random(seed).sample(mutations, max_mutants)

    results = [
        _score_one(mutation, reference, num_qubits, check) for mutation in mutations
    ]
    return MutationReport(tuple(results))


def _score_one(
    mutation: Mutation,
    reference: npt.NDArray[np.complex128],
    num_qubits: int,
    check: Check,
) -> MutantResult:
    mutant_unitary = unitary(list(mutation.ops), num_qubits)
    if phase_invariant_allclose(mutant_unitary, reference, atol=_EQUIVALENCE_ATOL):
        return MutantResult(mutation, "equivalent")
    result = _build_result(mutation.ops, num_qubits)
    try:
        check(result)
    except AssertionError as failure:
        return MutantResult(mutation, "killed", str(failure) or type(failure).__name__)
    return MutantResult(mutation, "survived")


def _run(circuit: Any, *, backend: str | None, args: tuple[Any, ...]) -> ExecutionResult:
    from qlens import run

    return run(circuit, backend=backend, args=args)


def _ops_from(result: ExecutionResult) -> list[GateOp]:
    """Canonical gate ops from a run, refusing any the simulator can't replay."""
    ops: list[GateOp] = []
    for snapshot in result.snapshots:
        if snapshot.gate == "initial":
            continue
        if not is_supported(snapshot.gate):
            raise QlensError(
                f"mutation can't replay gate {snapshot.gate!r} at position "
                f"{snapshot.position}: it is outside the canonical simulator's "
                f"vocabulary, so a mutant of this circuit couldn't be run"
            )
        ops.append(GateOp(snapshot.gate, snapshot.qubits, snapshot.params))
    return ops


def _build_result(ops: tuple[GateOp, ...], num_qubits: int) -> ExecutionResult:
    """A full ExecutionResult for a mutant, replayed on the simulator.

    Carries per-gate snapshots so positional checks (``assert_state(at=)``,
    ``assert_separable``) work on a mutant the same way they do on an
    ordinary run, plus a counts function that samples the mutant's final
    state.
    """
    states = simulate(list(ops), num_qubits)
    if not ops:
        snapshots = [
            Snapshot(0, "initial", (), {}, states[0]),
        ]
    else:
        snapshots = [
            Snapshot(index, op.gate, op.qubits, dict(op.params), state)
            for index, (op, state) in enumerate(zip(ops, states, strict=True))
        ]

    final = snapshots[-1].statevector

    def counts_fn(shots: int, seed: int | None) -> dict[str, int]:
        return _sample(final, num_qubits, shots, seed)

    return ExecutionResult(
        backend="qlens-mutant",
        num_qubits=num_qubits,
        snapshots=snapshots,
        _counts_fn=counts_fn,
    )


def _sample(
    state: npt.NDArray[np.complex128], num_qubits: int, shots: int, seed: int | None
) -> dict[str, int]:
    probabilities = np.abs(state) ** 2
    total = probabilities.sum()
    if total <= 0:
        raise QlensAssertionError("mutant state has zero norm; nothing to sample")
    rng = np.random.default_rng(seed)
    drawn = rng.multinomial(shots, probabilities / total)
    return {
        format(index, f"0{num_qubits}b"): int(count)
        for index, count in enumerate(drawn)
        if count
    }

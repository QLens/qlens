"""Execution result shapes.

These dataclasses are public API, shared by every backend. Field vocabulary
(position, gate, qubits) matches the TraceAct event vocabulary planned for
Phase 2, so captured executions map onto trace events without reshaping.

All statevectors follow the canonical conventions in CONVENTIONS.md:
big-endian basis ordering (qubit 0 is the leftmost bit of a basis label).
Backends convert at their own boundary; nothing downstream of these
dataclasses ever sees a provider-native ordering.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import numpy.typing as npt

from qlens._errors import QlensError


@dataclass(frozen=True)
class Snapshot:
    """State captured immediately after one gate application.

    position: 0-based index of the gate in execution order.
    gate: canonical lowercase gate name, one spelling across every
        backend (see CONVENTIONS.md). A gate outside Qlens's vocabulary
        keeps the framework's own name, lowercased.
    native_gate: what the framework itself called this gate. Defaults to
        ``gate``, which is what a backend reporting no distinct native
        spelling means.
    qubits: qubit indices the gate acted on, control qubits first.
    params: numeric gate parameters by name; empty for non-parameterized gates.
    statevector: full statevector after this gate, big-endian basis order.
    """

    position: int
    gate: str
    qubits: tuple[int, ...]
    params: dict[str, float]
    statevector: npt.NDArray[np.complex128]
    native_gate: str = ""

    def __post_init__(self) -> None:
        # Frozen, so the default has to be filled in the long way round.
        if not self.native_gate:
            object.__setattr__(self, "native_gate", self.gate)


@dataclass
class ExecutionResult:
    """Everything captured from one instrumented circuit execution.

    Counts are lazy: sampling only runs when .counts() is first called,
    so a purely structural inspection never pays the sampling cost.
    """

    backend: str
    num_qubits: int
    snapshots: list[Snapshot]
    _counts_fn: Callable[[int, int | None], dict[str, int]] = field(repr=False)
    _counts_cache: dict[tuple[int, int | None, int | None], dict[str, int]] = field(
        default_factory=dict, repr=False
    )
    # Set by qlens.run(trace=...): the open TracedRun this execution
    # recorded to, so later assert_* calls append to the same trace.
    traced_run: Any = field(default=None, repr=False, compare=False)

    def statevector_at(self, position: int) -> npt.NDArray[np.complex128]:
        """Statevector immediately after the gate at the given position.

        Accepts negative indices with normal Python semantics.
        """
        return self.snapshots[position].statevector

    @property
    def final_statevector(self) -> npt.NDArray[np.complex128]:
        """Statevector after the last gate.

        For an empty circuit this is the |0...0> state, which backends
        provide as a single position-less snapshot; see CONVENTIONS.md.
        """
        return self.snapshots[-1].statevector

    def counts(
        self, shots: int = 1024, *, seed: int | None = None, at: int | None = None
    ) -> dict[str, int]:
        """Measurement counts over all qubits in the computational basis.

        Keys are big-endian bitstrings (qubit 0 leftmost). ``seed`` makes
        sampling reproducible run to run, which keeps CI assertions at a
        given significance level from failing at that level's rate by
        chance. Results are cached per (shots, seed, at); repeated calls
        with the same values do not re-sample.

        ``at`` measures the state captured after that gate position
        instead of the circuit's final state, with the usual negative
        indexing. It samples from the captured statevector rather than
        through the backend, so a seeded ``counts(at=-1)`` need not match
        a seeded ``counts()`` draw for draw even though both describe the
        same distribution.
        """
        key = (shots, seed, at)
        if key not in self._counts_cache:
            self._counts_cache[key] = (
                self._counts_fn(shots, seed)
                if at is None
                else self._sample_at(at, shots, seed)
            )
        return self._counts_cache[key]

    def _sample_at(self, position: int, shots: int, seed: int | None) -> dict[str, int]:
        """Measurement counts for the state captured at one position.

        Sampled here rather than through the backend: the backend's
        counts function measures whatever the circuit ends on, and a
        mid-circuit position has no such object to hand it. The captured
        statevector is already canonical, so drawing from it directly
        gives the same convention every backend converges on.
        """
        state = self.snapshots[position].statevector
        probabilities = np.abs(state) ** 2
        total = probabilities.sum()
        if total <= 0:
            raise QlensError(
                f"the state captured at position {position} has zero norm; "
                "nothing to sample"
            )
        rng = np.random.default_rng(seed)
        drawn = rng.multinomial(shots, probabilities / total)
        return {
            format(index, f"0{self.num_qubits}b"): int(count)
            for index, count in enumerate(drawn)
            if count
        }

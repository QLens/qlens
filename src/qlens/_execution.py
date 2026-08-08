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

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class Snapshot:
    """State captured immediately after one gate application.

    position: 0-based index of the gate in execution order.
    gate: canonical lowercase gate name (see CONVENTIONS.md).
    qubits: qubit indices the gate acted on, control qubits first.
    params: numeric gate parameters by name; empty for non-parameterized gates.
    statevector: full statevector after this gate, big-endian basis order.
    """

    position: int
    gate: str
    qubits: tuple[int, ...]
    params: dict[str, float]
    statevector: npt.NDArray[np.complex128]


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
    _counts_cache: dict[tuple[int, int | None], dict[str, int]] = field(
        default_factory=dict, repr=False
    )

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

    def counts(self, shots: int = 1024, *, seed: int | None = None) -> dict[str, int]:
        """Measurement counts over all qubits in the computational basis.

        Keys are big-endian bitstrings (qubit 0 leftmost). ``seed`` makes
        sampling reproducible run to run, which keeps CI assertions at a
        given significance level from failing at that level's rate by
        chance. Results are cached per (shots, seed); repeated calls with
        the same values do not re-sample.
        """
        key = (shots, seed)
        if key not in self._counts_cache:
            self._counts_cache[key] = self._counts_fn(shots, seed)
        return self._counts_cache[key]

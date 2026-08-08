"""The public backend contract.

This module is the integration surface for quantum framework backends,
first-party and third-party alike. A new provider (e.g. a Cirq backend)
implements this ABC, registers it under the ``qlens.backends`` entry-point
group, and certifies it against ``qlens.conformance`` — no changes to
Qlens core are involved.

The contract is semver-governed public API: adding a required method is a
breaking change. Semantic requirements (bitstring endianness, basis
ordering, qubit index conventions, tolerance meanings) are specified in
CONVENTIONS.md, which is normative for every implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import numpy.typing as npt

from qlens._execution import ExecutionResult


class Backend(ABC):
    """One implementation per quantum framework. Stateless.

    ``name`` must match the entry-point name the backend registers under.
    """

    name: str

    @classmethod
    @abstractmethod
    def handles(cls, circuit: object) -> bool:
        """Whether this backend recognizes the given circuit object.

        Must not import the provider package: check type identity via
        module-name inspection (``type(circuit).__module__``) so that
        probing is free when the provider is not installed. Must return
        False, never raise, for unrecognized objects.
        """

    @abstractmethod
    def run(self, circuit: Any, *, args: tuple[Any, ...] = ()) -> ExecutionResult:
        """Execute with per-gate statevector capture.

        ``args`` carries parameter values for parameterized circuits, in
        the form the framework expects (bound positionally). Snapshots
        must follow CONVENTIONS.md: one per gate in execution order, plus
        a single initial snapshot for the |0...0> state when the circuit
        contains no gates.
        """

    @abstractmethod
    def operator_matrix(self, circuit: Any, *, args: tuple[Any, ...] = ()) -> npt.NDArray[np.complex128]:
        """Dense unitary of the whole circuit, big-endian basis order.

        Raises UnsupportedCircuitError for circuits with no defined
        unitary (measurement, reset, classical control).
        """

    @abstractmethod
    def is_unitary(self, circuit: Any, *, atol: float, args: tuple[Any, ...] = ()) -> bool:
        """Whether the circuit's operator is unitary within tolerance."""

    @abstractmethod
    def equivalent(
        self, circuit_a: Any, circuit_b: Any, *, atol: float, args: tuple[Any, ...] = ()
    ) -> bool:
        """Whether two circuits compute the same unitary up to global phase."""

    @abstractmethod
    def counts(
        self,
        circuit: Any,
        *,
        shots: int,
        seed: int | None = None,
        args: tuple[Any, ...] = (),
    ) -> dict[str, int]:
        """Sample measurement counts over all qubits.

        Keys are big-endian bitstrings (qubit 0 leftmost), values sum to
        ``shots``. Any measurement the user's circuit declares is ignored;
        Qlens measures all qubits in the computational basis uniformly
        across backends.

        ``seed`` makes sampling reproducible: the same circuit, shots,
        and seed must return identical counts on repeated calls. Seeds
        are not required to reproduce across backends or versions.
        """

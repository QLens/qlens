"""Canonical conformance circuits.

Each case is a framework-neutral gate program; expected results come
from the reference simulator, never from a provider framework. The
neutral vocabulary is: i, x, y, z, h, s, t (single-qubit), cx, cz, swap
(two-qubit, control first), ccx (three-qubit, controls first), rx, ry,
rz (single-qubit, one angle parameter).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from qlens.conformance import _reference

Program = tuple[tuple[str, tuple[int, ...], tuple[float, ...]], ...]

_THETA = 0.7  # fixed angle for parameterized cases; arbitrary, non-special


@dataclass(frozen=True)
class ConformanceCase:
    """One canonical circuit with reference-computed expectations."""

    name: str
    category: str  # "single_qubit" | "multi_qubit" | "parameterized"
    num_qubits: int
    program: Program
    expected_final_state: npt.NDArray[np.complex128] = field(init=False, repr=False)
    expected_probabilities: dict[str, float] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        state = _reference.simulate(self.program, self.num_qubits)
        object.__setattr__(self, "expected_final_state", state)
        probs = np.abs(state) ** 2
        labels = [format(i, f"0{self.num_qubits}b") for i in range(len(probs))]
        object.__setattr__(
            self,
            "expected_probabilities",
            {label: float(p) for label, p in zip(labels, probs) if p > 1e-12},
        )

    @property
    def expected_unitary(self) -> npt.NDArray[np.complex128]:
        return _reference.unitary(self.program, self.num_qubits)


@dataclass(frozen=True)
class EquivalencePair:
    """Two programs and whether they compute the same unitary."""

    name: str
    num_qubits: int
    program_a: Program
    program_b: Program
    equivalent: bool


def _g(gate: str, *qubits: int, params: tuple[float, ...] = ()) -> tuple[str, tuple[int, ...], tuple[float, ...]]:
    return (gate, qubits, params)


CASES: tuple[ConformanceCase, ...] = (
    # -- single-qubit ------------------------------------------------------
    ConformanceCase("identity", "single_qubit", 1, (_g("i", 0),)),
    ConformanceCase("pauli_x", "single_qubit", 1, (_g("x", 0),)),
    ConformanceCase("pauli_y", "single_qubit", 1, (_g("y", 0),)),
    ConformanceCase("pauli_z_on_plus", "single_qubit", 1, (_g("h", 0), _g("z", 0))),
    ConformanceCase("hadamard", "single_qubit", 1, (_g("h", 0),)),
    ConformanceCase("s_on_plus", "single_qubit", 1, (_g("h", 0), _g("s", 0))),
    ConformanceCase("t_on_plus", "single_qubit", 1, (_g("h", 0), _g("t", 0))),
    # -- multi-qubit -------------------------------------------------------
    ConformanceCase("bell", "multi_qubit", 2, (_g("h", 0), _g("cx", 0, 1))),
    ConformanceCase(
        "ghz", "multi_qubit", 3, (_g("h", 0), _g("cx", 0, 1), _g("cx", 1, 2))
    ),
    ConformanceCase("cz_on_plus_plus", "multi_qubit", 2, (_g("h", 0), _g("h", 1), _g("cz", 0, 1))),
    ConformanceCase("swap_excitation", "multi_qubit", 2, (_g("x", 0), _g("swap", 0, 1))),
    ConformanceCase(
        "toffoli", "multi_qubit", 3, (_g("x", 0), _g("x", 1), _g("ccx", 0, 1, 2))
    ),
    ConformanceCase("product_state", "multi_qubit", 2, (_g("h", 0), _g("h", 1))),
    # -- parameterized -----------------------------------------------------
    ConformanceCase("rx_rotation", "parameterized", 1, (_g("rx", 0, params=(_THETA,)),)),
    ConformanceCase("ry_rotation", "parameterized", 1, (_g("ry", 0, params=(_THETA,)),)),
    ConformanceCase(
        "parameterized_entangler",
        "parameterized",
        2,
        (_g("ry", 0, params=(_THETA,)), _g("ry", 1, params=(-_THETA,)), _g("cx", 0, 1)),
    ),
    ConformanceCase(
        "rotation_cnot_ladder",
        "parameterized",
        3,
        (
            _g("rx", 0, params=(_THETA,)),
            _g("ry", 1, params=(2 * _THETA,)),
            _g("rz", 2, params=(3 * _THETA,)),
            _g("cx", 0, 1),
            _g("cx", 1, 2),
        ),
    ),
)

EQUIVALENCE_PAIRS: tuple[EquivalencePair, ...] = (
    EquivalencePair(
        "hh_equals_identity",
        1,
        (_g("h", 0), _g("h", 0)),
        (_g("i", 0),),
        equivalent=True,
    ),
    EquivalencePair(
        "decomposed_swap",
        2,
        (_g("swap", 0, 1),),
        (_g("cx", 0, 1), _g("cx", 1, 0), _g("cx", 0, 1)),
        equivalent=True,
    ),
    EquivalencePair(
        "global_phase_z_vs_rz",
        1,
        (_g("z", 0),),
        (_g("rz", 0, params=(float(np.pi),)),),
        equivalent=True,  # differ by global phase i, which equivalence ignores
    ),
    EquivalencePair(
        "bell_vs_ghz_prefix",
        2,
        (_g("h", 0), _g("cx", 0, 1)),
        (_g("h", 0), _g("cx", 0, 1), _g("z", 1)),
        equivalent=False,
    ),
    EquivalencePair(
        "x_vs_y",
        1,
        (_g("x", 0),),
        (_g("y", 0),),
        equivalent=False,  # differ by a relative (not global) phase
    ),
)

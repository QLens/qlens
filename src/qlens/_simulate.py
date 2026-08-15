"""A canonical statevector simulator over Qlens's own gate vocabulary.

The mutation engine needs to run a circuit it has changed. It cannot hand
the change back to the framework: a PennyLane circuit is a Python
function, not an editable gate list, so there is nowhere to put a swapped
control or a deleted gate. Instead it mutates the canonical gate list
Qlens already captured (:class:`~qlens._execution.Snapshot`) and replays
it here.

Replaying means owning gate matrices, so this module carries a table of
them keyed by canonical name. The convention is Qiskit's, which is the one
:mod:`qlens._gates` normalizes toward; ``test_simulate.py`` pins that the
replayed state matches every backend gate for gate, so the table cannot
drift from what the backends do.

Everything is big-endian, matching the rest of Qlens: qubit 0 is the most
significant axis of the reshaped tensor (see CONVENTIONS.md).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from qlens._errors import QlensError

Matrix = npt.NDArray[np.complex128]


class UnsupportedGateError(QlensError):
    """A captured gate has no matrix in the canonical simulator.

    Raised rather than guessed: a gate the table cannot build is one the
    mutation engine cannot replay, and inventing a matrix for it would
    report mutants against a circuit that was never run.
    """


@dataclass(frozen=True)
class GateOp:
    """One gate in a replayable circuit: canonical name, qubits, params.

    The mutation-facing counterpart of :class:`~qlens._execution.Snapshot`,
    carrying only what replay needs. ``qubits`` lists control qubits first,
    matching the snapshot convention. ``params`` maps ``p0``, ``p1``, ...
    to angle values, in the order the framework supplied them.
    """

    gate: str
    qubits: tuple[int, ...]
    params: dict[str, float] = field(default_factory=dict)

    def angles(self) -> list[float]:
        """Param values in index order (``p0``, ``p1``, ...)."""
        return [self.params[k] for k in sorted(self.params, key=_param_index)]


def _param_index(key: str) -> int:
    return int(key[1:]) if key[1:].isdigit() else 0


# -- one-qubit matrices ----------------------------------------------------

_SQRT2_INV = 1.0 / np.sqrt(2.0)

_ONE_Q_FIXED: dict[str, Matrix] = {
    "i": np.eye(2, dtype=complex),
    "x": np.array([[0, 1], [1, 0]], dtype=complex),
    "y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "z": np.array([[1, 0], [0, -1]], dtype=complex),
    "h": _SQRT2_INV * np.array([[1, 1], [1, -1]], dtype=complex),
    "s": np.array([[1, 0], [0, 1j]], dtype=complex),
    "sdg": np.array([[1, 0], [0, -1j]], dtype=complex),
    "t": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=complex),
    "tdg": np.array([[1, 0], [0, np.exp(-1j * np.pi / 4)]], dtype=complex),
    "sx": np.array(
        [[0.5 + 0.5j, 0.5 - 0.5j], [0.5 - 0.5j, 0.5 + 0.5j]], dtype=complex
    ),
    "sxdg": np.array(
        [[0.5 - 0.5j, 0.5 + 0.5j], [0.5 + 0.5j, 0.5 - 0.5j]], dtype=complex
    ),
}


def _rx(theta: float) -> Matrix:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=complex)


def _ry(theta: float) -> Matrix:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=complex)


def _rz(theta: float) -> Matrix:
    return np.array(
        [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]], dtype=complex
    )


def _phase(lam: float) -> Matrix:
    return np.array([[1, 0], [0, np.exp(1j * lam)]], dtype=complex)


def _u(theta: float, phi: float, lam: float) -> Matrix:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array(
        [
            [c, -np.exp(1j * lam) * s],
            [np.exp(1j * phi) * s, np.exp(1j * (phi + lam)) * c],
        ],
        dtype=complex,
    )


# name -> (param count, builder)
_ONE_Q_PARAM: dict[str, tuple[int, Callable[..., Matrix]]] = {
    "rx": (1, _rx),
    "ry": (1, _ry),
    "rz": (1, _rz),
    "p": (1, _phase),
    "u": (3, _u),
}


# -- two-qubit bare (non-controlled) matrices ------------------------------

_TWO_Q_BARE: dict[str, Matrix] = {
    "swap": np.array(
        [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex
    ),
    "iswap": np.array(
        [[1, 0, 0, 0], [0, 0, 1j, 0], [0, 1j, 0, 0], [0, 0, 0, 1]], dtype=complex
    ),
}


# -- controlled gates as (control count, base gate name) -------------------

_CONTROLLED: dict[str, tuple[int, str]] = {
    "cx": (1, "x"),
    "cy": (1, "y"),
    "cz": (1, "z"),
    "ch": (1, "h"),
    "csx": (1, "sx"),
    "cp": (1, "p"),
    "crx": (1, "rx"),
    "cry": (1, "ry"),
    "crz": (1, "rz"),
    "cu": (1, "u"),
    "ccx": (2, "x"),
    "ccz": (2, "z"),
    "cswap": (1, "swap"),
}


def _base_matrix(name: str, angles: list[float]) -> Matrix:
    """The matrix for a non-controlled gate, given its angles."""
    if name in _ONE_Q_FIXED:
        return _ONE_Q_FIXED[name]
    if name in _TWO_Q_BARE:
        return _TWO_Q_BARE[name]
    if name in _ONE_Q_PARAM:
        count, builder = _ONE_Q_PARAM[name]
        if len(angles) != count:
            raise UnsupportedGateError(
                f"gate {name!r} takes {count} parameter(s), got {len(angles)}"
            )
        return builder(*angles)
    raise UnsupportedGateError(f"no canonical matrix for gate {name!r}")


def _controlled(base: Matrix, num_controls: int) -> Matrix:
    """Wrap a base matrix in ``num_controls`` controls, controls first.

    The result acts as the identity unless every control qubit is 1, where
    it applies ``base`` to the target qubits. Control axes come first, so
    the qubit order is controls-then-targets, matching how the snapshot
    lists them.
    """
    dim_b = base.shape[0]
    dim_c = 2**num_controls
    tensor = np.eye(dim_c * dim_b, dtype=complex).reshape(dim_c, dim_b, dim_c, dim_b)
    all_ones = dim_c - 1
    tensor[all_ones, :, all_ones, :] = base
    return tensor.reshape(dim_c * dim_b, dim_c * dim_b)


def matrix_for(op: GateOp) -> Matrix:
    """The dense matrix for one gate, sized to ``op.qubits``.

    Raises :class:`UnsupportedGateError` for any gate the table cannot
    build, so the caller can refuse the whole circuit rather than replay a
    silent approximation of it.
    """
    name = op.gate
    angles = op.angles()
    if name in _CONTROLLED:
        num_controls, base_name = _CONTROLLED[name]
        matrix = _controlled(_base_matrix(base_name, angles), num_controls)
    else:
        matrix = _base_matrix(name, angles)
    expected = round(float(np.log2(matrix.shape[0])))
    if len(op.qubits) != expected:
        raise UnsupportedGateError(
            f"gate {name!r} acts on {expected} qubit(s), but was given "
            f"{len(op.qubits)}: {op.qubits}"
        )
    return matrix


def qubit_count(name: str) -> int:
    """How many qubits the named gate acts on."""
    if name in _CONTROLLED:
        num_controls, base_name = _CONTROLLED[name]
        return num_controls + qubit_count(base_name)
    if name in _TWO_Q_BARE:
        return 2
    if name in _ONE_Q_FIXED or name in _ONE_Q_PARAM:
        return 1
    raise UnsupportedGateError(f"unknown gate {name!r}")


def is_supported(name: str) -> bool:
    """Whether the canonical simulator can replay the named gate."""
    return (
        name in _ONE_Q_FIXED
        or name in _ONE_Q_PARAM
        or name in _TWO_Q_BARE
        or name in _CONTROLLED
    )


# -- application -----------------------------------------------------------


def _apply(state: Matrix, matrix: Matrix, qubits: tuple[int, ...], num_qubits: int) -> Matrix:
    """Apply a k-qubit ``matrix`` to ``qubits`` of a state, or a batch.

    ``state`` is either shape ``(2**num_qubits,)`` or
    ``(2**num_qubits, m)`` with each column an independent statevector.
    Batching lets :func:`unitary` evolve all basis columns in one pass.
    The named qubit axes move to the front, the matrix multiplies, and the
    axes move back; big-endian throughout (qubit q is axis q).
    """
    k = len(qubits)
    shape = state.shape
    tensor = state.reshape([2] * num_qubits + list(shape[1:]))
    rest = [ax for ax in range(num_qubits) if ax not in qubits]
    batch_axes = list(range(num_qubits, tensor.ndim))
    perm = list(qubits) + rest + batch_axes
    tensor = tensor.transpose(perm).reshape(2**k, -1)
    tensor = (matrix @ tensor).reshape([2] * num_qubits + list(shape[1:]))
    inverse = np.argsort(perm)
    return np.ascontiguousarray(tensor.transpose(inverse)).reshape(shape)


def simulate(ops: list[GateOp], num_qubits: int) -> list[npt.NDArray[np.complex128]]:
    """Statevector after each op, starting from |0...0>.

    Returns one array per op, in order. An empty op list returns a single
    |0...0> state, matching how the backends snapshot an empty circuit.
    """
    state = np.zeros(2**num_qubits, dtype=complex)
    state[0] = 1.0
    if not ops:
        return [state]
    states: list[npt.NDArray[np.complex128]] = []
    for op in ops:
        state = _apply(state, matrix_for(op), op.qubits, num_qubits)
        states.append(state)
    return states


def unitary(ops: list[GateOp], num_qubits: int) -> Matrix:
    """The dense unitary of the whole op list, big-endian basis order.

    Evolves the identity's columns (the basis states) through the ops in
    one batched pass, so the circuit matrix falls out without composing
    per-gate embeddings.
    """
    matrix = np.eye(2**num_qubits, dtype=complex)
    for op in ops:
        matrix = _apply(matrix, matrix_for(op), op.qubits, num_qubits)
    return matrix

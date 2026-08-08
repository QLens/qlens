"""Reference simulator: the executable ground truth for CONVENTIONS.md.

A minimal pure-numpy statevector simulator over the neutral gate
vocabulary, written directly in Qlens's canonical conventions (big-endian
basis ordering, qubit 0 leftmost). Conformance expectations are computed
here, never borrowed from any provider framework — a backend certifies
against this, not against another backend.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

_SQ2 = 1.0 / np.sqrt(2.0)

# Single- and multi-qubit gate matrices over the neutral vocabulary.
# Controlled/multi-qubit matrices are written big-endian: the first named
# qubit is the most significant bit of the basis index.
_FIXED: dict[str, npt.NDArray[np.complex128]] = {
    "i": np.eye(2, dtype=np.complex128),
    "x": np.array([[0, 1], [1, 0]], dtype=np.complex128),
    "y": np.array([[0, -1j], [1j, 0]], dtype=np.complex128),
    "z": np.array([[1, 0], [0, -1]], dtype=np.complex128),
    "h": np.array([[_SQ2, _SQ2], [_SQ2, -_SQ2]], dtype=np.complex128),
    "s": np.array([[1, 0], [0, 1j]], dtype=np.complex128),
    "t": np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=np.complex128),
    "cx": np.array(
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]], dtype=np.complex128
    ),
    "cz": np.diag([1, 1, 1, -1]).astype(np.complex128),
    "swap": np.array(
        [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=np.complex128
    ),
    "ccx": np.eye(8, dtype=np.complex128)[[0, 1, 2, 3, 4, 5, 7, 6]],
}


def gate_matrix(gate: str, params: tuple[float, ...]) -> npt.NDArray[np.complex128]:
    """Matrix for one neutral-vocabulary gate."""
    if gate in _FIXED:
        return _FIXED[gate]
    if gate in {"rx", "ry", "rz"}:
        (theta,) = params
        half = theta / 2.0
        if gate == "rx":
            return np.array(
                [[np.cos(half), -1j * np.sin(half)], [-1j * np.sin(half), np.cos(half)]],
                dtype=np.complex128,
            )
        if gate == "ry":
            return np.array(
                [[np.cos(half), -np.sin(half)], [np.sin(half), np.cos(half)]],
                dtype=np.complex128,
            )
        return np.array(
            [[np.exp(-1j * half), 0], [0, np.exp(1j * half)]], dtype=np.complex128
        )
    raise ValueError(f"unknown gate {gate!r} in neutral vocabulary")


def apply_gate(
    state: npt.NDArray[np.complex128],
    gate: str,
    qubits: tuple[int, ...],
    params: tuple[float, ...],
    num_qubits: int,
) -> npt.NDArray[np.complex128]:
    """Apply one gate to a big-endian statevector, or to a batch of them.

    ``state`` is either shape ``(2**num_qubits,)`` or
    ``(2**num_qubits, m)`` with each column an independent statevector;
    batching lets ``unitary`` evolve all basis columns in one pass over
    the program instead of one full pass per column.
    """
    matrix = gate_matrix(gate, params)
    k = len(qubits)
    shape = state.shape
    tensor = state.reshape([2] * num_qubits + list(shape[1:]))
    # Move the acted-on qubit axes to the front, apply, move back. Any
    # batch axes stay trailing throughout.
    rest = [ax for ax in range(num_qubits) if ax not in qubits]
    batch_axes = list(range(num_qubits, tensor.ndim))
    perm = list(qubits) + rest + batch_axes
    tensor = tensor.transpose(perm).reshape(2**k, -1)
    tensor = (matrix @ tensor).reshape(
        [2] * num_qubits + list(shape[1:])
    )
    inverse = np.argsort(perm)
    return np.ascontiguousarray(tensor.transpose(inverse)).reshape(shape)


def simulate(
    program: tuple[tuple[str, tuple[int, ...], tuple[float, ...]], ...],
    num_qubits: int,
) -> npt.NDArray[np.complex128]:
    """Final statevector of a neutral gate program from |0...0>."""
    state = np.zeros(2**num_qubits, dtype=np.complex128)
    state[0] = 1.0
    for gate, qubits, params in program:
        state = apply_gate(state, gate, qubits, params, num_qubits)
    return state


def unitary(
    program: tuple[tuple[str, tuple[int, ...], tuple[float, ...]], ...],
    num_qubits: int,
) -> npt.NDArray[np.complex128]:
    """Full big-endian unitary of a neutral gate program.

    Evolves the identity matrix through the program in one pass, all
    basis columns batched, rather than re-simulating per column.
    """
    matrix = np.eye(2**num_qubits, dtype=np.complex128)
    for gate, qubits, params in program:
        matrix = apply_gate(matrix, gate, qubits, params, num_qubits)
    return matrix

"""The four mutation operators.

A mutation operator is a small, deliberate change to a captured circuit
that models a class of quantum bug. Running the circuit's own tests
against each mutant is mutation testing: a test suite that fails on the
mutant *killed* it, one that passes *survived* it, and survivors are the
bugs the suite would not have caught.

The four here follow the bug-pattern catalog Qlens documents (see
USAGE.md). Each maps to a family of defects seen in the wild:

    reverse_control_target  a controlled gate wired control-for-target,
                            the reversed-CNOT class.
    substitute_gate         the wrong gate of the right shape: X for Y,
                            an S where a T belonged, a CZ for a CX.
    inject_phase            a spurious relative phase, the error that
                            breaks interference while leaving each
                            qubit's marginal untouched.
    delete_gate             a missing gate, including the missing half of
                            an uncompute pair that strands an ancilla.

Operators are pure and deterministic: they take an op list and return
mutants in position order. Which mutants to run, and how many, is the
caller's decision (see :mod:`qlens._mutate`).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from qlens._simulate import _CONTROLLED as CONTROLLED
from qlens._simulate import GateOp

# Gates that may substitute for one another: same qubit arity, same
# parameter count, so the swap stays replayable. Grouped by that shape.
_SUBSTITUTION_CLASSES: tuple[tuple[str, ...], ...] = (
    ("x", "y", "z", "h", "s", "sdg", "t", "tdg", "sx"),  # one qubit, no params
    ("rx", "ry", "rz", "p"),  # one qubit, one angle
    ("swap", "iswap"),  # two qubits, no controls
    ("cx", "cy", "cz", "ch"),  # one control, no params
    ("cp", "crx", "cry", "crz"),  # one control, one angle
    ("ccx", "ccz"),  # two controls
)

# The phase this operator injects: a Z is the largest relative phase, a
# sign flip between the |0> and |1> branches. Where the qubit carries no
# superposition it is only a global phase, so that mutant comes out
# equivalent and is discarded rather than counted, the right outcome for
# an injection placed where it has no effect.
_INJECTED_PHASE = "z"


@dataclass(frozen=True)
class Mutation:
    """One mutant: what changed, and the op list to replay."""

    operator: str
    description: str
    ops: tuple[GateOp, ...]


def _sibling_class(gate: str) -> tuple[str, ...]:
    for group in _SUBSTITUTION_CLASSES:
        if gate in group:
            return group
    return ()


def reverse_control_target(ops: Sequence[GateOp]) -> list[Mutation]:
    """Swap a controlled gate's first control with its last target.

    For a plain two-qubit gate this is the reversed-CNOT bug outright. For
    a diagonal control (CZ, controlled-phase) the swap changes nothing and
    the mutant comes back equivalent; that is correct, not a miss.
    """
    mutants: list[Mutation] = []
    for position, op in enumerate(ops):
        if op.gate not in CONTROLLED or len(op.qubits) < 2:
            continue
        swapped = list(op.qubits)
        swapped[0], swapped[-1] = swapped[-1], swapped[0]
        mutated = GateOp(op.gate, tuple(swapped), dict(op.params))
        mutants.append(
            Mutation(
                "reverse_control_target",
                f"{op.gate} on {_qubits(op.qubits)} rewired to "
                f"{_qubits(mutated.qubits)} at position {position}",
                _replace(ops, position, [mutated]),
            )
        )
    return mutants


def substitute_gate(ops: Sequence[GateOp]) -> list[Mutation]:
    """Replace each gate with every same-shape sibling in turn."""
    mutants: list[Mutation] = []
    for position, op in enumerate(ops):
        for sibling in _sibling_class(op.gate):
            if sibling == op.gate:
                continue
            mutated = GateOp(sibling, op.qubits, dict(op.params))
            mutants.append(
                Mutation(
                    "substitute_gate",
                    f"{op.gate} replaced by {sibling} on "
                    f"{_qubits(op.qubits)} at position {position}",
                    _replace(ops, position, [mutated]),
                )
            )
    return mutants


def inject_phase(ops: Sequence[GateOp]) -> list[Mutation]:
    """Insert a spurious Z after each gate, on the gate's last qubit."""
    mutants: list[Mutation] = []
    for position, op in enumerate(ops):
        target = op.qubits[-1]
        phase = GateOp(_INJECTED_PHASE, (target,), {})
        mutants.append(
            Mutation(
                "inject_phase",
                f"spurious {_INJECTED_PHASE} on {_qubits((target,))} after "
                f"{op.gate} at position {position}",
                _replace(ops, position, [op, phase]),
            )
        )
    return mutants


def delete_gate(ops: Sequence[GateOp]) -> list[Mutation]:
    """Remove each gate in turn.

    Deleting the mirror of an earlier gate is how an uncompute goes
    missing, leaving an ancilla entangled with the data it was meant to be
    released from.
    """
    mutants: list[Mutation] = []
    for position, op in enumerate(ops):
        mutants.append(
            Mutation(
                "delete_gate",
                f"{op.gate} on {_qubits(op.qubits)} deleted at position {position}",
                _replace(ops, position, []),
            )
        )
    return mutants


OPERATORS: dict[str, Callable[[Sequence[GateOp]], list[Mutation]]] = {
    "reverse_control_target": reverse_control_target,
    "substitute_gate": substitute_gate,
    "inject_phase": inject_phase,
    "delete_gate": delete_gate,
}


def all_mutations(
    ops: Sequence[GateOp], operators: Sequence[str] | None = None
) -> list[Mutation]:
    """Every mutant from the named operators, in operator then position order.

    ``operators`` defaults to all four. Unknown names raise, so a typo in a
    caller's operator list is caught rather than silently producing fewer
    mutants than asked for.
    """
    chosen = list(OPERATORS) if operators is None else list(operators)
    unknown = [name for name in chosen if name not in OPERATORS]
    if unknown:
        raise ValueError(
            f"unknown mutation operator(s) {unknown}; choose from {list(OPERATORS)}"
        )
    mutants: list[Mutation] = []
    for name in chosen:
        mutants.extend(OPERATORS[name](ops))
    return mutants


def _replace(
    ops: Sequence[GateOp], position: int, replacement: Sequence[GateOp]
) -> tuple[GateOp, ...]:
    """A copy of ``ops`` with the op at ``position`` swapped for ``replacement``.

    An empty ``replacement`` deletes; a two-op replacement inserts.
    """
    return (*ops[:position], *replacement, *ops[position + 1 :])


def _qubits(qubits: tuple[int, ...]) -> str:
    return ",".join(f"q{q}" for q in qubits)

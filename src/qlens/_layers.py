"""Layer grouping: partition a gate sequence into qubit-disjoint layers.

A layer is a maximal run of gates that act on pairwise-disjoint qubit
sets, built greedily in execution order: each gate joins the current
layer unless it shares a qubit with a gate already in it, in which case
it starts a new layer. Greedy left-packing preserves execution order
within and across layers, which is what a trace timeline needs (a
scheduler-style minimal-depth partition could reorder gates and lie
about causality).
"""

from __future__ import annotations

from dataclasses import dataclass

from qlens._execution import Snapshot


@dataclass(frozen=True)
class Layer:
    """One qubit-disjoint group of consecutive gates.

    index: 0-based layer position in execution order.
    snapshots: the member gates' snapshots, in execution order.
    """

    index: int
    snapshots: tuple[Snapshot, ...]

    @property
    def qubits(self) -> tuple[int, ...]:
        """Union of member gates' qubits, ascending."""
        return tuple(sorted({q for s in self.snapshots for q in s.qubits}))

    @property
    def positions(self) -> tuple[int, ...]:
        """Member gate positions, in execution order."""
        return tuple(s.position for s in self.snapshots)


def group_layers(snapshots: list[Snapshot]) -> list[Layer]:
    """Partition gate snapshots into qubit-disjoint layers, greedily.

    Gates with no qubits (the synthetic initial-state snapshot of an
    empty circuit) each occupy their own layer: they cannot overlap
    anything, but merging them into a neighbour would misstate order.
    """
    layers: list[Layer] = []
    current: list[Snapshot] = []
    occupied: set[int] = set()

    def flush() -> None:
        if current:
            layers.append(Layer(index=len(layers), snapshots=tuple(current)))
            current.clear()
            occupied.clear()

    for snapshot in snapshots:
        qubits = set(snapshot.qubits)
        if not qubits or (occupied & qubits):
            flush()
        current.append(snapshot)
        occupied |= qubits
        if not qubits:
            flush()
    flush()
    return layers

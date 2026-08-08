"""Layer grouping: adversarial orderings first."""

from __future__ import annotations

import numpy as np

from qlens._execution import Snapshot
from qlens._layers import group_layers

_STATE = np.array([1.0 + 0j])


def _snap(position: int, qubits: tuple[int, ...], gate: str = "g") -> Snapshot:
    return Snapshot(
        position=position, gate=gate, qubits=qubits, params={}, statevector=_STATE
    )


def test_empty_input() -> None:
    assert group_layers([]) == []


def test_overlapping_gates_never_share_a_layer() -> None:
    snaps = [_snap(0, (0,)), _snap(1, (0,)), _snap(2, (0,))]
    layers = group_layers(snaps)
    assert [layer.positions for layer in layers] == [(0,), (1,), (2,)]


def test_partial_overlap_splits() -> None:
    # cx(0,1) then cx(1,2): share qubit 1, must split.
    layers = group_layers([_snap(0, (0, 1)), _snap(1, (1, 2))])
    assert len(layers) == 2


def test_disjoint_gates_pack_into_one_layer() -> None:
    layers = group_layers([_snap(0, (0,)), _snap(1, (1,)), _snap(2, (2, 3))])
    assert len(layers) == 1
    assert layers[0].qubits == (0, 1, 2, 3)
    assert layers[0].positions == (0, 1, 2)


def test_greedy_does_not_reorder_across_a_barrier_gate() -> None:
    # h(0), cx(0,1), h(2): h(2) is disjoint from cx(0,1) and joins ITS
    # layer, but must never be hoisted back into layer 0 past the cx —
    # greedy left-packing looks at the current layer only.
    layers = group_layers([_snap(0, (0,)), _snap(1, (0, 1)), _snap(2, (2,))])
    assert [layer.positions for layer in layers] == [(0,), (1, 2)]


def test_qubitless_snapshot_isolated() -> None:
    # The synthetic initial-state snapshot ends up alone in a layer.
    layers = group_layers([_snap(0, ()), _snap(1, (0,))])
    assert [layer.positions for layer in layers] == [(0,), (1,)]


def test_layer_indices_are_contiguous() -> None:
    snaps = [_snap(i, (i % 2,)) for i in range(6)]
    layers = group_layers(snaps)
    assert [layer.index for layer in layers] == list(range(len(layers)))


def test_wide_circuit_layer_count() -> None:
    # 1000 single-qubit gates spread over 10 qubits round-robin: each
    # group of 10 consecutive gates is disjoint, so 100 layers.
    snaps = [_snap(i, (i % 10,)) for i in range(1000)]
    layers = group_layers(snaps)
    assert len(layers) == 100
    assert all(len(layer.snapshots) == 10 for layer in layers)

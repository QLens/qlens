"""One gate vocabulary across every backend.

The point of a wrapper over three frameworks is that a caller reading
``snapshot.gate`` gets one answer. These check that the same circuit
reports the same names whichever framework built it, that the framework's
own spelling survives alongside, and that a gate outside the vocabulary is
passed through rather than forced into it.
"""

from __future__ import annotations

import pytest

from qlens._execution import Snapshot
from qlens._gates import CANONICAL, normalize
from qlens.backends import get_backend
from qlens.conformance._builders import BUILDERS

# One of each shape: single-qubit, two-qubit, three-qubit, parameterized,
# and a gate the three frameworks spell three different ways.
MIXED_PROGRAM = (
    ("h", (0,), ()),
    ("s", (0,), ()),
    ("t", (1,), ()),
    ("rx", (0,), (0.3,)),
    ("cx", (0, 1), ()),
    ("cz", (0, 1), ()),
    ("swap", (0, 1), ()),
    ("ccx", (0, 1, 2), ()),
    ("i", (2,), ()),
)

BACKENDS = ["qiskit", "pennylane", "cirq"]


def _snapshots(backend_name: str) -> list[Snapshot]:
    pytest.importorskip("cirq" if backend_name == "cirq" else backend_name)
    circuit = BUILDERS[backend_name](MIXED_PROGRAM, 3)
    return get_backend(backend_name).run(circuit).snapshots


# -- the map itself -------------------------------------------------------


def test_an_unknown_gate_is_not_forced_into_the_vocabulary() -> None:
    """Claiming a canonical name for a gate Qlens does not model would
    report a normalization that never happened."""
    assert normalize("MyCustomGate") == "mycustomgate"
    assert normalize("qft") == "qft"


def test_normalization_ignores_case_and_surrounding_space() -> None:
    assert normalize("  CNOT  ") == "cx"
    assert normalize("Hadamard") == "h"
    assert normalize("PauliX") == "x"


def test_every_alias_resolves_to_a_name_that_is_itself_an_alias() -> None:
    """A canonical name has to survive a second pass, or normalizing an
    already-normalized snapshot would change it."""
    for canonical in set(CANONICAL.values()):
        assert normalize(canonical) == canonical


def test_the_three_frameworks_spellings_all_map_to_one_name() -> None:
    for spelling in ("cx", "cnot", "CNOT"):
        assert normalize(spelling) == "cx"
    for spelling in ("h", "hadamard", "H"):
        assert normalize(spelling) == "h"
    for spelling in ("ccx", "toffoli", "TOFFOLI"):
        assert normalize(spelling) == "ccx"


# -- across the backends --------------------------------------------------


@pytest.mark.parametrize("backend_name", BACKENDS)
def test_each_backend_reports_the_canonical_vocabulary(backend_name: str) -> None:
    names = [s.gate for s in _snapshots(backend_name)]
    assert names == ["h", "s", "t", "rx", "cx", "cz", "swap", "ccx", "i"]


def test_all_three_backends_agree_gate_for_gate() -> None:
    reported = {}
    for backend_name in BACKENDS:
        reported[backend_name] = [s.gate for s in _snapshots(backend_name)]
    assert len(set(map(tuple, reported.values()))) == 1, reported


def test_all_three_backends_agree_on_parameters() -> None:
    """A rotation reports radians everywhere, and a gate whose name fixes
    its rotation reports nothing anywhere."""
    reported = {}
    for backend_name in BACKENDS:
        reported[backend_name] = [
            (s.gate, tuple(sorted(s.params.items()))) for s in _snapshots(backend_name)
        ]
    assert len(set(map(tuple, reported.values()))) == 1, reported


def test_the_frameworks_own_spelling_is_kept_not_discarded() -> None:
    pytest.importorskip("pennylane")
    by_gate = {s.gate: s.native_gate for s in _snapshots("pennylane")}
    assert by_gate["h"] == "hadamard"
    assert by_gate["cx"] == "cnot"
    assert by_gate["ccx"] == "toffoli"


@pytest.mark.parametrize("backend_name", BACKENDS)
def test_the_two_names_on_a_snapshot_agree_with_the_map(backend_name: str) -> None:
    """Whatever the framework called a gate has to be the thing that
    normalizes to the name Qlens reports, or the pair describes two
    different gates."""
    for snapshot in _snapshots(backend_name):
        assert normalize(snapshot.native_gate) == snapshot.gate


# -- the Snapshot default -------------------------------------------------


def test_a_snapshot_built_without_a_native_name_falls_back_to_the_canonical() -> None:
    import numpy as np

    snapshot = Snapshot(
        position=0, gate="h", qubits=(0,), params={}, statevector=np.array([1.0, 0.0])
    )
    assert snapshot.native_gate == "h"


def test_a_native_name_that_was_given_is_not_overwritten() -> None:
    import numpy as np

    snapshot = Snapshot(
        position=0,
        gate="cx",
        qubits=(0, 1),
        params={},
        statevector=np.array([1.0, 0.0, 0.0, 0.0]),
        native_gate="cnot",
    )
    assert snapshot.native_gate == "cnot"

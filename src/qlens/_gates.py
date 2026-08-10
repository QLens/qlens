"""One gate vocabulary across every backend.

Each framework spells the same gate its own way: a controlled-NOT is
``cx`` in Qiskit, ``CNOT`` in PennyLane and Cirq; a Hadamard is ``h``,
``Hadamard``, and ``H``. Absorbing that is the wrapper's job. A test that
reads ``snapshot.gate``, or a reader scanning the viewer's circuit strip,
should see one name for one gate whichever framework produced the run.

The map is data, so supporting a new framework's spellings is an entry
here rather than a branch in the backend. The framework's own spelling is
never discarded: it travels alongside as ``Snapshot.native_gate``, which
is what to read when a gate falls outside this vocabulary.

Names outside the map pass through lowercased rather than being forced
into it. Inventing a canonical name for a gate Qlens does not model would
claim a normalization that has not happened.
"""

from __future__ import annotations

# Native spelling (lowercased) -> canonical name, grouped by canonical
# name so a new framework's spelling is added next to its siblings. Every
# entry is a spelling one of the supported frameworks actually emits;
# nothing here is a guess at what some framework might call a gate. A
# canonical name with no divergent spellings needs no entry, since an
# unmapped name passes through unchanged.
_ALIASES: dict[str, tuple[str, ...]] = {
    "i": ("id", "identity"),
    "x": ("paulix",),
    "y": ("pauliy",),
    "z": ("pauliz",),
    "h": ("hadamard",),
    "sdg": ("s**-1", "adjoint(s)"),
    "tdg": ("t**-1", "adjoint(t)"),
    "sx": ("x**0.5",),
    "cx": ("cnot",),
    "ccx": ("toffoli",),
    "cswap": ("fredkin",),
    "p": ("phaseshift",),
    "u": ("rot",),
}

CANONICAL: dict[str, str] = {
    alias: canonical for canonical, aliases in _ALIASES.items() for alias in aliases
}

# Canonical gates whose name already fixes their rotation. Cirq models
# these as powers of a parent gate and carries the exponent on them, so
# recording it would make an S gate report a parameter its siblings on
# other backends do not.
FIXED_EXPONENT = frozenset({"s", "sdg", "t", "tdg", "sx", "x", "y", "z", "h",
                            "cx", "cy", "cz", "ch", "swap", "iswap",
                            "ccx", "ccz", "cswap", "i"})


def normalize(native: str) -> str:
    """The canonical name for a framework's own spelling.

    Unknown names come back lowercased and otherwise untouched, so a gate
    Qlens has no name for still reads as what the framework called it.
    """
    key = native.strip().lower()
    return CANONICAL.get(key, key)

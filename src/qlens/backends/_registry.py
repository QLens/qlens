"""Backend discovery and dispatch.

Backends are discovered exclusively through the ``qlens.backends``
entry-point group — Qlens's own two register there via pyproject.toml,
exactly as a third-party backend package would. Resolution is lazy:
loading an entry point only happens when that backend is actually
requested or matches a circuit, so installed-but-unused providers cost
nothing.
"""

from __future__ import annotations

from functools import cache
from importlib.metadata import EntryPoint, entry_points

from qlens._errors import BackendNotFoundError, BackendNotInstalledError
from qlens.backends.base import Backend

ENTRY_POINT_GROUP = "qlens.backends"

# Maps first-party backend names to (import package, pip extra) for the
# actionable install-hint error. Third-party backends handle their own
# dependency errors inside load().
_FIRST_PARTY_HINTS = {
    "qiskit": ("qiskit", "qiskit"),
    "pennylane": ("pennylane", "pennylane"),
}


@cache
def _discovered() -> dict[str, EntryPoint]:
    """Entry points by backend name. Cached for the process lifetime;
    installing a new backend package requires a new process, same as
    pytest plugins."""
    return {ep.name: ep for ep in entry_points(group=ENTRY_POINT_GROUP)}


@cache
def _load(name: str) -> Backend:
    """Load and instantiate one backend, translating a missing provider
    package into an actionable error."""
    ep = _discovered().get(name)
    if ep is None:
        available = ", ".join(sorted(_discovered())) or "none"
        raise BackendNotFoundError(
            f"no backend named {name!r} is registered (available: {available})"
        )
    try:
        backend_cls: type[Backend] = ep.load()
    except ImportError as exc:
        if name in _FIRST_PARTY_HINTS:
            package, extra = _FIRST_PARTY_HINTS[name]
            raise BackendNotInstalledError(name, package, extra) from exc
        raise
    return backend_cls()


def available_backends() -> list[str]:
    """Names of all registered backends, installed or not."""
    return sorted(_discovered())


def get_backend(name: str) -> Backend:
    """Resolve a backend by its registered name."""
    return _load(name)


def detect_backend(circuit: object) -> Backend:
    """Resolve the backend whose framework produced the given circuit.

    Polls each registered backend's handles() classmethod. handles() is
    required not to import its provider, so probing every registered
    backend is free; the winning backend is then actually loaded, which
    is the only point a missing provider package can surface.
    """
    for name, ep in sorted(_discovered().items()):
        try:
            backend_cls: type[Backend] = ep.load()
        except ImportError:
            # handles() must be probe-safe without the provider installed,
            # but loading the module can still fail if the backend module
            # itself imports the provider at module level. Skip it: a
            # circuit from an uninstalled framework cannot exist in this
            # process anyway.
            continue
        if backend_cls.handles(circuit):
            return _load(name)
    raise BackendNotFoundError(
        f"no installed backend recognizes {type(circuit).__qualname__!r} "
        f"(registered backends: {', '.join(available_backends()) or 'none'})"
    )

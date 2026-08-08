"""Public error taxonomy.

Every error Qlens raises derives from QlensError, so callers can catch one
type. Assertion failures derive from both QlensError and AssertionError,
so they behave natively under pytest.
"""

from __future__ import annotations


class QlensError(Exception):
    """Base class for all Qlens errors."""


class BackendNotInstalledError(QlensError):
    """A backend was requested whose provider package is not importable.

    Carries the pip install hint so the message is actionable as-is.
    """

    def __init__(self, backend_name: str, package: str, extra: str) -> None:
        self.backend_name = backend_name
        self.package = package
        super().__init__(
            f"{backend_name!r} backend requested but {package} is not installed. "
            f"Install with: pip install qlens[{extra}]"
        )


class BackendNotFoundError(QlensError):
    """No registered backend matches the requested name or circuit object."""


class UnsupportedCircuitError(QlensError):
    """The circuit contains an instruction the operation cannot handle
    (e.g. mid-circuit measurement in a unitarity check)."""


class QlensAssertionError(QlensError, AssertionError):
    """An assert_* check failed. Subclasses AssertionError so pytest
    reports it as a test failure, not an error."""

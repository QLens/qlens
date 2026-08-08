"""Public backend contract and registry.

Third-party backends implement :class:`Backend`, register under the
``qlens.backends`` entry-point group, and certify against
``qlens.conformance``. See CONVENTIONS.md for the semantic requirements
every implementation must satisfy.
"""

from qlens.backends._registry import available_backends, detect_backend, get_backend
from qlens.backends.base import Backend

__all__ = ["Backend", "available_backends", "detect_backend", "get_backend"]

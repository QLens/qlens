"""Bundled pytest plugin.

Installing qlens registers this module under pytest's ``pytest11``
entry-point group, making the fixtures below available in any test run
with no conftest wiring. The ``qlens`` marker documents quantum tests
and allows selecting them with ``-m qlens``.
"""

from __future__ import annotations

from typing import Any

import pytest

import qlens


def pytest_configure(config: Any) -> None:
    config.addinivalue_line(
        "markers", "qlens: marks a test as a qlens quantum circuit test"
    )


@pytest.fixture(autouse=True)
def _qlens_finish_traces() -> Any:
    """Close any trace left open by qlens.run(trace=...) when the test
    ends, so each test's trace record is complete and written before the
    next test starts."""
    yield
    from qlens import tracing

    tracing.finish_traces()


@pytest.fixture
def qlens_run() -> Any:
    """The qlens.run entry point, as a fixture."""
    return qlens.run


@pytest.fixture
def assert_distribution() -> Any:
    """qlens.assert_distribution, as a fixture."""
    return qlens.assert_distribution


@pytest.fixture
def assert_unitary() -> Any:
    """qlens.assert_unitary, as a fixture."""
    return qlens.assert_unitary


@pytest.fixture
def assert_equivalent() -> Any:
    """qlens.assert_equivalent, as a fixture."""
    return qlens.assert_equivalent

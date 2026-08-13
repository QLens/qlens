"""Where an assertion event says it came from.

The frame walk has to skip qlens's own frames to find the test that made
the assertion, and skip the standard library so that machinery sitting
between the two — a worker thread, a runner, an atexit hook — never gets
the blame for a check it only happened to dispatch.
"""

from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor

from qlens.tracing._adapter import assertion_fields

NO_DETAILS: dict[str, float] = {}


def test_reports_the_calling_test_file() -> None:
    here = inspect.currentframe()
    assert here is not None
    line = here.f_lineno + 1
    fields = assertion_fields(None, "assert_unitary", "unitarity", None, None, None)
    assert fields["source"] == f"{__file__}:{line}"


def test_stdlib_frames_never_take_the_blame() -> None:
    """Submitted to a pool, the innermost frame outside qlens belongs to
    concurrent.futures. Naming it would send a reader into the standard
    library instead of to their own test."""
    with ThreadPoolExecutor(max_workers=1) as pool:
        fields = pool.submit(
            assertion_fields, None, "assert_unitary", "unitarity", None, None, None
        ).result()
    assert "source" not in fields


def test_position_absent_when_the_target_is_not_a_run() -> None:
    """assert_unitary takes a circuit, which carries no captured
    positions; the viewer must get no marker rather than a wrong one."""
    fields = assertion_fields(object(), "assert_unitary", "unitarity", None, None, None)
    assert "position" not in fields


def test_expected_distribution_is_normalized() -> None:
    """Callers may pass relative weights rather than probabilities; the
    viewer draws the reference against observed probabilities."""
    fields = assertion_fields(
        None, "assert_distribution", "distribution", None, None, {"00": 3.0, "11": 1.0}
    )
    assert fields["expected"] == {"00": 0.75, "11": 0.25}


def test_expected_distribution_with_no_mass_is_dropped() -> None:
    fields = assertion_fields(
        None, "assert_distribution", "distribution", None, None, {"00": 0.0}
    )
    assert "expected" not in fields


def test_an_oversized_expected_distribution_is_trimmed_and_says_so() -> None:
    """TraceAct deletes any single value over its payload budget, so a
    wide expectation has to be trimmed to fit. Dropping it whole was the
    earlier answer, and it left the viewer with nothing to overlay and no
    way to explain the absence."""
    import json

    from traceact.budget import BUDGET_DEFAULTS

    limit = int(BUDGET_DEFAULTS["max_payload_bytes"])
    large = {format(i, "012b"): 1.0 for i in range(4096)}
    fields = assertion_fields(
        None, "assert_distribution", "distribution", None, None, large
    )
    assert fields["expected"], "something must survive to ghost"
    assert len(json.dumps(fields["expected"]).encode()) <= limit
    assert fields["expected_trimmed"]["of"] == 4096
    assert fields["expected_trimmed"]["kept"] < 4096


def test_failure_carries_type_and_message() -> None:
    error = ValueError("p-value 0.001 below 0.05")
    fields = assertion_fields(None, "assert_distribution", "distribution", error, None, None)
    assert fields["status"] == "failed"
    assert fields["error"] == {
        "type": "ValueError", "message": "p-value 0.001 below 0.05"
    }


def test_non_finite_metrics_become_null() -> None:
    fields = assertion_fields(
        None, "assert_distribution", "distribution", None,
        {"statistic": float("inf"), "p_value": float("nan"), "tolerance": 0.05}, None,
    )
    assert fields["details"] == {"statistic": None, "p_value": None, "tolerance": 0.05}


def test_empty_details_are_omitted_entirely() -> None:
    fields = assertion_fields(None, "assert_unitary", "unitarity", None, NO_DETAILS, None)
    assert "details" not in fields

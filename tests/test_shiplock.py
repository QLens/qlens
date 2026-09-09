"""The shiplock docs-vs-code gate, run inside the test suite.

The same deterministic checks run three ways off one `shiplock.toml`: at a
terminal (`shiplock check`), here in pytest, and in CI. A failure lists the
findings so the drift is named, not just counted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

shiplock = pytest.importorskip("shiplock")

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_docs_match_code() -> None:
    report = shiplock.run_checks(shiplock.load_config(_REPO_ROOT))
    findings = [f"{f.check}  {f.path}:{f.line}  {f.message}" for f in report.findings]
    assert report.ok, "shiplock found docs-vs-code drift:\n" + "\n".join(findings)

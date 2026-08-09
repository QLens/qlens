"""Docs against current behaviour.

USAGE.md documents an HTTP surface and a set of CLI flags. Both drift
silently: an endpoint gets renamed, a flag gets dropped, and the manual
keeps describing the old one until someone tries it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from qlens.viewer.cli import main

ROOT = Path(__file__).parent.parent
USAGE = (ROOT / "USAGE.md").read_text(encoding="utf-8")


def test_every_documented_endpoint_is_routed() -> None:
    documented = set(re.findall(r"`GET (/api/\w+)", USAGE))
    assert documented, "USAGE.md lost its endpoint table"
    routed = set(re.findall(r'route == "(/api/\w+)"', Path(_HANDLER_SOURCE).read_text()))
    assert documented <= routed, documented - routed


def test_every_routed_endpoint_is_documented() -> None:
    documented = set(re.findall(r"`GET (/api/\w+)", USAGE))
    routed = set(re.findall(r'route == "(/api/\w+)"', Path(_HANDLER_SOURCE).read_text()))
    assert routed <= documented, routed - documented


def test_every_documented_view_flag_exists(capsys: pytest.CaptureFixture[str]) -> None:
    documented = set(re.findall(r"^\| `(--[a-z-]+)`", USAGE, flags=re.MULTILINE))
    assert documented, "USAGE.md lost its flag table"
    with pytest.raises(SystemExit):
        main(["view", "--help"])
    help_text = capsys.readouterr().out
    # Anchored at both ends: a plain substring test would accept --demoo
    # as evidence that --demo still exists.
    missing = {
        flag for flag in documented
        if not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", help_text)
    }
    assert not missing, missing


def test_documented_waterfall_defaults_match_the_server() -> None:
    assert 'max_rows` (display rows, default 512)' in USAGE
    source = Path(_HANDLER_SOURCE).read_text()
    assert '(query.get("max_rows") or ["512"])' in source


def test_documented_port_default_matches_the_cli() -> None:
    assert "default 8766" in USAGE
    assert 'default=8766' in (ROOT / "src/qlens/viewer/cli.py").read_text()


def test_documented_expected_cap_matches_the_adapter() -> None:
    assert "above 256 entries" in USAGE
    adapter = (ROOT / "src/qlens/tracing/_adapter.py").read_text()
    assert "_MAX_EXPECTED_ENTRIES = 256" in adapter


_HANDLER_SOURCE = str(ROOT / "src/qlens/viewer/server.py")

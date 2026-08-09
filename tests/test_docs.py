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
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


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


def test_documented_sample_run_count_matches_the_generator() -> None:
    """Prose counts drift the moment a sample run is added. This one has
    already gone stale twice across USAGE, ARCHITECTURE, and CHANGELOG."""
    # Only counting words, so "Generate sample runs" in the flag table
    # is not mistaken for a claim about how many there are.
    counts = "|".join(NUMBER_WORDS)
    claimed = set(re.findall(rf"({counts}) sample runs", USAGE))
    assert claimed, "USAGE.md lost its count of --demo sample runs"
    demo = (ROOT / "src/qlens/viewer/_demo.py").read_text()
    actual = len(re.findall(r"^    _record_\w+\(qlens, tracing\)", demo, flags=re.MULTILINE))
    assert actual > 0
    assert {NUMBER_WORDS[word] for word in claimed} == {actual}


def test_documented_module_count_matches_the_static_dir() -> None:
    architecture = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
    claimed = re.search(r"(\w+) ES modules served", architecture)
    assert claimed, "ARCHITECTURE.md lost its frontend description"
    modules = list((ROOT / "src/qlens/viewer/static").glob("*.js"))
    assert NUMBER_WORDS[claimed.group(1).lower()] == len(modules)


def test_documented_settings_match_the_dataclass() -> None:
    """A settings table drifts the moment a field is renamed, and a
    reader copying a stale key gets a QlensError from their own project."""
    from qlens._config import Settings

    section = USAGE[USAGE.index("## Settings"):]
    section = section[: section.index("\n## ", 3)]
    documented = set(re.findall(r"^\| `(\w+)` \|", section, flags=re.MULTILINE))
    actual = {
        name for name in Settings.__dataclass_fields__ if not name.startswith("_")
    }
    assert documented == actual


def test_documented_test_methods_match_the_accepted_ones() -> None:
    from qlens._config import _TESTS

    documented = set(re.findall(r"^\| `(chi_square\w*|tvd|ks)` \|", USAGE, flags=re.MULTILINE))
    assert documented == set(_TESTS)


def test_documented_policies_match_the_accepted_ones() -> None:
    from qlens._config import _POLICIES

    section = USAGE[USAGE.index("`on_unreliable_statistics` | "):]
    row = section[: section.index("|", len("`on_unreliable_statistics` | ") + 40)]
    for policy in _POLICIES:
        assert f"`{policy}`" in row, policy


def test_every_string_exists_in_both_registers() -> None:
    """A one-register entry silently falls back, so the reader gets the
    wrong voice with no error to notice. Checked structurally because
    the copy lives in JS, where the Python suite cannot import it."""
    copy = (ROOT / "src/qlens/viewer/static/copy.js").read_text(encoding="utf-8")
    # Every topic and tour entry declares both keys.
    simple = copy.count("simple:")
    advanced = copy.count("advanced:")
    assert simple == advanced, f"{simple} simple entries vs {advanced} advanced"
    assert simple >= 20, "copy.js lost entries"


def test_viewer_copy_uses_contractions() -> None:
    """House style. Expanded forms read stiffly next to the rest."""
    banned = (" do not ", " does not ", " cannot ", " will not ", " did not ",
              " is not ", " are not ", " it is ", " that is ", " you are ")
    for name in ("copy.js", "app.js", "guide.js"):
        text = (ROOT / "src/qlens/viewer/static" / name).read_text(encoding="utf-8")
        # Strings only: comments explain code and may phrase things formally.
        quoted = re.findall(r"['\"`]([^'\"`\n]{20,})['\"`]", text)
        for line in quoted:
            lowered = f" {line.lower()} "
            hits = [phrase for phrase in banned if phrase in lowered]
            assert not hits, f"{name}: {hits} in {line[:70]!r}"


def test_transport_defaults_are_the_requested_ones() -> None:
    """Playback opens at the start of the run at 1x, and the speed
    choices are the slow set. All three are deliberate and easy to
    revert by accident while editing nearby code."""
    app = (ROOT / "src/qlens/viewer/static/app.js").read_text(encoding="utf-8")
    assert re.search(r"const SPEEDS = \[0\.25, 0\.5, 1, 2\];", app)
    assert re.search(r"^  speed: 1,$", app, flags=re.MULTILINE)
    assert re.search(r"^  state\.index = 0;$", app, flags=re.MULTILINE)

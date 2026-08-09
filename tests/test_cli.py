"""The ``qlens`` command line, argument handling only.

Nothing here calls serve_forever; the viewer server itself is covered by
test_viewer.py against a live socket.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qlens.viewer.cli import main


def test_no_command_prints_help(capsys: Any) -> None:
    assert main([]) == 2
    assert "view" in capsys.readouterr().out


def test_view_without_source_or_demo_is_an_error(capsys: Any) -> None:
    assert main(["view"]) == 2
    assert "--demo" in capsys.readouterr().err


def test_missing_source_names_the_path(capsys: Any) -> None:
    assert main(["view", "no/such/traces.jsonl"]) == 1
    assert "no/such/traces.jsonl" in capsys.readouterr().err


def test_version_flag(capsys: Any) -> None:
    import qlens

    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert qlens.__version__ in capsys.readouterr().out


def test_demo_generates_and_serves(monkeypatch: Any, capsys: Any) -> None:
    """--demo must reach a bound server without being handed a source."""
    served: dict[str, Any] = {}

    class _Server:
        server_address = ("127.0.0.1", 9999)

        def serve_forever(self) -> None:
            raise KeyboardInterrupt  # stand in for the operator's ctrl-c

        def server_close(self) -> None:
            served["closed"] = True

    def fake_serve(source: str, **kwargs: Any) -> _Server:
        served["source"] = source
        served["state_dir"] = kwargs["state_dir"]
        return _Server()

    monkeypatch.setattr("qlens.viewer.server.serve", fake_serve)
    assert main(["view", "--demo", "--no-browser"]) == 0
    assert Path(served["source"]).is_file()
    assert list(Path(served["state_dir"]).glob("*.npz"))
    assert served["closed"] is True
    assert "9999" in capsys.readouterr().out

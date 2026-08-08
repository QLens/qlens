"""USAGE.md's quickstart code, executed as written.

The snippets are extracted from the document itself, not duplicated
here, so the docs cannot drift from working code without this file
failing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("qiskit")
pytest.importorskip("pennylane")

_USAGE = Path(__file__).parent.parent / "USAGE.md"


def _python_blocks() -> list[str]:
    text = _USAGE.read_text(encoding="utf-8")
    return re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)


def test_usage_has_quickstart_blocks() -> None:
    blocks = _python_blocks()
    assert len(blocks) >= 2, "USAGE.md lost its quickstart code blocks"


def test_quickstart_qiskit_block_runs() -> None:
    block = _python_blocks()[0]
    assert "def test_bell_distribution" in block
    namespace: dict[str, object] = {}
    exec(compile(block, str(_USAGE), "exec"), namespace)
    namespace["test_bell_distribution"]()  # type: ignore[operator]
    namespace["test_bell_state_evolution"]()  # type: ignore[operator]


def test_quickstart_pennylane_block_runs() -> None:
    block = _python_blocks()[1]
    assert "def test_bell_distribution_pennylane" in block
    namespace: dict[str, object] = {}
    exec(compile(block, str(_USAGE), "exec"), namespace)
    namespace["test_bell_distribution_pennylane"]()  # type: ignore[operator]

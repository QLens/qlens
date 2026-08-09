"""Project settings: validation first, then loading, then precedence.

Every value here reaches a user's test suite, so a typo has to fail at
the point it was written rather than silently leaving a different test
method in force.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from qlens import _config as config
from qlens._errors import QlensError


@pytest.fixture(autouse=True)
def _default_settings() -> Any:
    config.reset()
    yield
    config.reset()


# -- validation --------------------------------------------------------


def test_unknown_test_name_names_the_valid_ones() -> None:
    with pytest.raises(QlensError, match="chi_square_exact"):
        config.configure(distribution_test="chisquare")


def test_unknown_policy_rejected() -> None:
    with pytest.raises(QlensError, match="warn"):
        config.configure(on_unreliable_statistics="explode")


def test_negative_min_expected_count_rejected() -> None:
    with pytest.raises(QlensError, match="must not be negative"):
        config.configure(min_expected_count=-1)


def test_too_few_resamples_rejected() -> None:
    """A p-value from 10 resamples has a resolution of 0.1, which cannot
    support a 0.05 significance level."""
    with pytest.raises(QlensError, match="at least 100"):
        config.configure(resamples=10)


def test_a_rejected_value_leaves_settings_untouched() -> None:
    before = config.effective()
    with pytest.raises(QlensError):
        config.configure(distribution_test="nope")
    assert config.effective() == before


def test_only_passed_fields_change() -> None:
    config.configure(distribution_test="tvd")
    assert config.settings.distribution_test == "tvd"
    config.configure(resamples=500)
    assert config.settings.distribution_test == "tvd"
    assert config.settings.resamples == 500


# -- loading from pyproject -------------------------------------------


def write_project(directory: Path, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "pyproject.toml").write_text(body, encoding="utf-8")
    return directory


def test_settings_load_from_the_nearest_pyproject(tmp_path: Path) -> None:
    root = write_project(tmp_path, '[tool.qlens]\ndistribution_test = "tvd"\n')
    assert config.load_project_settings(root) is True
    assert config.settings.distribution_test == "tvd"


def test_settings_load_from_a_parent_directory(tmp_path: Path) -> None:
    write_project(tmp_path, '[tool.qlens]\non_unreliable_statistics = "error"\n')
    nested = tmp_path / "tests" / "unit"
    nested.mkdir(parents=True)
    assert config.load_project_settings(nested) is True
    assert config.settings.on_unreliable_statistics == "error"


def test_the_nearest_pyproject_wins(tmp_path: Path) -> None:
    """A pyproject stops the search whether or not it configures qlens,
    matching how every other Python tool resolves project settings."""
    write_project(tmp_path, '[tool.qlens]\ndistribution_test = "tvd"\n')
    inner = write_project(tmp_path / "sub", '[project]\nname = "sub"\n')
    assert config.load_project_settings(inner) is False
    assert config.settings.distribution_test == "chi_square"


def test_pyproject_without_a_qlens_table_changes_nothing(tmp_path: Path) -> None:
    root = write_project(tmp_path, '[project]\nname = "x"\n')
    assert config.load_project_settings(root) is False
    assert config.settings.distribution_test == "chi_square"


def test_no_pyproject_anywhere_changes_nothing(tmp_path: Path) -> None:
    # tmp_path has no pyproject, but its parents might; point at a
    # directory whose whole chain is under the temporary root.
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    config.load_project_settings(deep)
    assert config.settings.distribution_test == "chi_square"


def test_unknown_key_in_the_table_is_an_error(tmp_path: Path) -> None:
    """Silently ignoring a misspelled setting leaves the user believing
    it took effect."""
    root = write_project(tmp_path, '[tool.qlens]\ndistribution_tests = "tvd"\n')
    with pytest.raises(QlensError, match="distribution_tests"):
        config.load_project_settings(root)


def test_invalid_value_in_the_table_names_the_file(tmp_path: Path) -> None:
    root = write_project(tmp_path, '[tool.qlens]\ndistribution_test = "nope"\n')
    with pytest.raises(QlensError, match="nope"):
        config.load_project_settings(root)


def test_malformed_toml_names_the_file(tmp_path: Path) -> None:
    root = write_project(tmp_path, "[tool.qlens\n")
    with pytest.raises(QlensError, match="could not read settings"):
        config.load_project_settings(root)


# -- what gets recorded ------------------------------------------------


def test_effective_settings_exclude_private_fields() -> None:
    config.load_project_settings(Path(__file__).parent)
    recorded = config.effective()
    assert "_loaded_from" not in recorded
    assert set(recorded) == {
        "distribution_test",
        "on_unreliable_statistics",
        "min_expected_count",
        "resamples",
    }


def test_effective_settings_are_json_safe() -> None:
    import json

    config.configure(distribution_test="tvd")
    assert json.loads(json.dumps(config.effective()))["distribution_test"] == "tvd"

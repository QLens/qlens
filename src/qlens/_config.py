"""Project settings for how assertions test things.

Two levels, both explicit. A project fixes its defaults once:

    [tool.qlens]
    distribution_test = "tvd"
    on_unreliable_statistics = "warn"

and any single call overrides them:

    qlens.assert_distribution(result, expected, test="chi_square_exact")

Nothing here ever changes a test's method on the caller's behalf. When a
chosen method is a poor fit for the data it was handed, the assertion
says so through ``on_unreliable_statistics`` and reports why; picking a
different one stays the caller's decision.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from qlens._errors import QlensError

DistributionTest = Literal["chi_square", "chi_square_exact", "tvd", "ks"]
UnreliablePolicy = Literal["warn", "error", "ignore"]

_TESTS: tuple[str, ...] = ("chi_square", "chi_square_exact", "tvd", "ks")
_POLICIES: tuple[str, ...] = ("warn", "error", "ignore")


@dataclass
class Settings:
    """Defaults for the assert_* API."""

    #: Which test ``assert_distribution`` runs when the call does not name one.
    distribution_test: DistributionTest = "chi_square"
    #: What happens when a test's assumptions do not hold for the data.
    on_unreliable_statistics: UnreliablePolicy = "warn"
    #: Expected count below which a chi-square cell is considered too
    #: sparse for the asymptotic p-value. The conventional value.
    min_expected_count: float = 5.0
    #: Samples drawn to build a null distribution for the exact p-value
    #: and the TVD noise floor. 10k puts the Monte Carlo error on a
    #: p-value near 0.05 at well under half a percent.
    resamples: int = 10_000
    _loaded_from: str | None = field(default=None, repr=False)


settings = Settings()


def configure(
    *,
    distribution_test: str | None = None,
    on_unreliable_statistics: str | None = None,
    min_expected_count: float | None = None,
    resamples: int | None = None,
) -> None:
    """Set assertion defaults for the rest of the session.

    Only the fields passed change. Values are validated here rather than
    at assertion time, so a typo surfaces at the point it was written.
    """
    if distribution_test is not None:
        settings.distribution_test = _checked(distribution_test, _TESTS, "distribution_test")  # type: ignore[assignment]
    if on_unreliable_statistics is not None:
        settings.on_unreliable_statistics = _checked(  # type: ignore[assignment]
            on_unreliable_statistics, _POLICIES, "on_unreliable_statistics"
        )
    if min_expected_count is not None:
        if min_expected_count < 0:
            raise QlensError("min_expected_count must not be negative")
        settings.min_expected_count = float(min_expected_count)
    if resamples is not None:
        if resamples < 100:
            raise QlensError(
                f"resamples must be at least 100 to give a usable p-value, got {resamples}"
            )
        settings.resamples = int(resamples)


def _checked(value: str, allowed: tuple[str, ...], field_name: str) -> str:
    if value not in allowed:
        raise QlensError(
            f"unknown {field_name} {value!r}; choose one of {', '.join(allowed)}"
        )
    return value


def load_project_settings(start: str | Path | None = None) -> bool:
    """Apply ``[tool.qlens]`` from the nearest pyproject.toml.

    Walks up from ``start`` (the working directory by default) to the
    filesystem root and stops at the first pyproject.toml it finds,
    whether or not that file carries a ``[tool.qlens]`` table. Returns
    whether any setting was applied.
    """
    directory = Path(start or Path.cwd()).resolve()
    for candidate in (directory, *directory.parents):
        path = candidate / "pyproject.toml"
        if not path.is_file():
            continue
        try:
            table = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise QlensError(f"could not read settings from {path}: {exc}") from exc
        section = (table.get("tool") or {}).get("qlens")
        if not section:
            return False
        unknown = set(section) - {f.name for f in Settings.__dataclass_fields__.values() if not f.name.startswith("_")}
        if unknown:
            raise QlensError(
                f"unknown setting(s) in {path} [tool.qlens]: {', '.join(sorted(unknown))}"
            )
        configure(**section)
        settings._loaded_from = str(path)
        return True
    return False


def effective() -> dict[str, Any]:
    """The current settings, for recording onto a trace so the viewer can
    report which ones a run used instead of guessing."""
    return {k: v for k, v in asdict(settings).items() if not k.startswith("_")}


def reset() -> None:
    """Restore the built-in defaults. Used by tests."""
    global settings
    settings = Settings()

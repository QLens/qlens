"""Whether a statistical test's assumptions hold for the data it got.

A test can return a confident-looking number that means nothing. The
usual chi-square p-value assumes every outcome is expected a handful of
times; quantum output routinely concentrates on a few states and leaves
the rest expected far less than once, and the p-value then swings by
orders of magnitude on the sampling seed alone, in both directions. It
both flakes and misses real errors.

Qlens never swaps the method out from under the caller when that
happens. It reports the problem, names the alternatives, and leaves the
choice where it belongs. What the report says is one string, built here,
so the warning, the trace event, and the viewer all say the same thing.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

from qlens._errors import QlensError


class QlensStatisticsWarning(UserWarning):
    """A test ran, but its assumptions do not hold for this data."""


@dataclass(frozen=True)
class Reliability:
    """A verdict on one assertion's statistics."""

    reliable: bool
    #: Short machine-readable cause, for the viewer to key off.
    code: str = ""
    #: One sentence naming what is wrong, in the reader's terms.
    summary: str = ""
    #: The numbers behind the verdict.
    detail: dict[str, float] = None  # type: ignore[assignment]
    #: Concrete calls that would settle the question instead.
    remedies: tuple[str, ...] = ()

    def as_event_field(self) -> dict[str, Any]:
        return {
            "reliable": self.reliable,
            "code": self.code,
            "summary": self.summary,
            "detail": dict(self.detail or {}),
            "remedies": list(self.remedies),
        }


RELIABLE = Reliability(reliable=True, detail={})


def sparse_chi_square(
    below: int, live: int, smallest: float, threshold: float
) -> Reliability:
    """Verdict for a chi-square whose cells are too thinly populated."""
    if below == 0:
        return RELIABLE
    return Reliability(
        reliable=False,
        code="sparse_cells",
        summary=(
            f"chi-square assumes about {threshold:g} or more expected counts per "
            f"outcome. {below} of {live} outcomes here expect fewer (smallest: "
            f"{smallest:.3g}), so this p-value can be wrong in either direction."
        ),
        detail={
            "cells_below_threshold": float(below),
            "cells_total": float(live),
            "smallest_expected_count": smallest,
            "threshold": float(threshold),
        },
        remedies=(
            'test="chi_square_exact" for a simulated p-value that holds at any count',
            'test="tvd" to compare by distance instead of significance',
            f"shots at least {int(threshold / max(smallest, 1e-12))} to populate every outcome",
        ),
    )


def tolerance_below_noise(tolerance: float, floor: float, shots: int) -> Reliability:
    """Verdict for a distance test asking for closer agreement than
    sampling at this shot count can produce."""
    if tolerance >= floor:
        return RELIABLE
    return Reliability(
        reliable=False,
        code="tolerance_below_noise",
        summary=(
            f"sampling {shots} shots lands about {floor:.4f} away from the expected "
            f"distribution on its own, so a tolerance of {tolerance:.4f} rejects "
            "correct circuits most of the time."
        ),
        detail={
            "tolerance": float(tolerance),
            "noise_floor": float(floor),
            "shots": float(shots),
        },
        remedies=(
            f"tolerance above {floor:.4f} at this shot count",
            (
                f"shots around {int(shots * (floor / max(tolerance, 1e-12)) ** 2)} "
                "to bring the noise floor under the current tolerance"
            ),
        ),
    )


def report(verdict: Reliability, policy: str, assertion: str) -> None:
    """Act on a verdict according to ``on_unreliable_statistics``.

    ``ignore`` is silent, ``warn`` raises a warning, ``error`` refuses to
    let the result be used. In every case the verdict is still recorded
    on the trace, so the viewer can surface it regardless of policy.
    """
    if verdict.reliable or policy == "ignore":
        return
    message = f"{assertion}: {verdict.summary}"
    if verdict.remedies:
        message += "\nInstead, use " + "; or ".join(verdict.remedies) + "."
    if policy == "error":
        raise QlensError(message)
    warnings.warn(message, QlensStatisticsWarning, stacklevel=3)

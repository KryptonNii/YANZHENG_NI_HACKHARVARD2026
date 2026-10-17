"""Milestone forecast from actuals (ops stub of A3's `update_with_actuals`).

Per-site enrollment rates get a conjugate Gamma update (prior = plan rate with shape k), the remaining
patients arrive as a Poisson process with the summed rate, so the time to last-patient-in is
Gamma(remaining, total_rate). LPLV = LPI + treatment/follow-up; DB lock = max(LPLV + cleaning,
vendor critical-path forecast + its planned lag to DB lock). Monte Carlo, seeded.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .metrics import Feed
from .plan import DAYS_PER_MONTH, OpsPlan

DRAWS = 2000


@dataclass
class MilestoneForecast:
    upto: float
    enrolled: int
    lpi: np.ndarray  # draws (days since epoch)
    lplv: np.ndarray
    dblock: np.ndarray
    dblock_without_vendor: np.ndarray
    vendor_path: float | None  # day of the DB-lock constraint from the vendor's latest forecast
    vendor_milestone: dict | None

    def q(self, name: str) -> tuple[float, float, float]:
        a = getattr(self, name)
        return tuple(float(x) for x in np.quantile(a, [0.1, 0.5, 0.9]))  # type: ignore[return-value]


def forecast_milestones(plan: OpsPlan, feed: Feed, upto: float, seed: int = 0) -> MilestoneForecast:
    cached = feed.__dict__.setdefault("_milestone_cache", {})
    key = (upto, seed)
    if key not in cached:
        if len(cached) > 32:
            cached.clear()
        cached[key] = _forecast_milestones(plan, feed, upto, seed)
    return cached[key]


def _forecast_milestones(plan: OpsPlan, feed: Feed, upto: float, seed: int) -> MilestoneForecast:
    from .forecast_adapter import updated

    forecast = updated(plan, feed, upto, seed)
    lpi = forecast.draws.t_full * DAYS_PER_MONTH
    lplv = forecast.draws.duration * DAYS_PER_MONTH
    # A3 duration includes closeout; retain its paired LPI/follow-up/closeout draws.
    dbl_enr = lplv
    lplv = lpi + forecast.draws.followup_months * DAYS_PER_MONTH
    vendor_path, vm = None, None
    latest: dict[str, dict] = {}
    for r in feed.vendor:
        if r["t"] < upto and r.get("critical_path"):
            latest[r["milestone_id"]] = r
    for r in latest.values():
        if r["status"] == "complete":
            continue
        lag = plan.dblock_target_day - r["planned_day"]  # planned gap from this milestone to DB lock
        path = r["forecast_day"] + lag
        if vendor_path is None or path > vendor_path:
            vendor_path, vm = path, r
    dbl = np.maximum(dbl_enr, vendor_path) if vendor_path is not None else dbl_enr
    return MilestoneForecast(upto, int(feed.per_site("enrolled", upto).sum()), lpi, lplv, dbl, dbl_enr, vendor_path, vm)

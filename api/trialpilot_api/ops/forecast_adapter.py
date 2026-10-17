"""Bridge the operational plan and observed feed to A3's pure forecasting engine."""

from __future__ import annotations

import numpy as np
from trialpilot_engine.forecast import forecast, update_with_actuals

from ._contracts import Levers, Parameter


def prepare(plan, seed=7, supplied=None):
    """Use explicit ops assumptions so the forecast and the simulated plan share a basis."""
    from .plan import DAYS_PER_MONTH, PLAN_RATE_SHAPE

    active = [s for s in plan.sites if not s.backup]
    if not active:
        raise ValueError("At least one site must have positive or unknown expected enrollment")
    ids = {s.id for s in active}
    design = plan.design.model_copy(update={"sites": [s for s in plan.design.sites if s.id in ids]})
    mean_rate = sum(s.planned_rate_month for s in active) / len(active)
    cleaning = (plan.dblock_target_day - plan.lplv_target_day) / DAYS_PER_MONTH
    specs = {
        "site.activation_months": (0, 28 / DAYS_PER_MONTH, 56 / DAYS_PER_MONTH, "months/site"),
        "site.enrollment_rate_shape": (PLAN_RATE_SHAPE, PLAN_RATE_SHAPE, PLAN_RATE_SHAPE, "dimensionless"),
        "site.enrollment_rate_per_month": (mean_rate, mean_rate, mean_rate, "patients/site/month"),
        "patient.dropout_rate": (0, 0, 0, "share"),
        "trial.closeout_months": (cleaning * .7, cleaning, cleaning * 1.3, "months"),
        "lever.decentralised.recruitment_uplift": (0, 0, 0, "share"),
        "lever.decentralised.dropout_reduction": (0, 0, 0, "share"),
    }
    params = {pid: Parameter(id=pid, label=pid, value_low=lo, value_mid=mid, value_high=hi,
                             unit=unit, assumption=True,
                             rationale="Operational simulation plan; target counts randomised patients, "
                             "activation spans 56 days, and no recruitment benefit is assumed.")
              for pid, (lo, mid, hi, unit) in specs.items()}
    prior = supplied or forecast(design, Levers(), params, seed=seed, draws=2000)
    plan.forecast_design, plan.forecast_params, plan.forecast_prior = design, params, prior
    grid = np.array(prior.enrollment_curve)
    if grid.size:
        weeks = np.arange(plan.n_weeks + 1) * 7 / DAYS_PER_MONTH
        plan.study_band = np.stack([np.interp(weeks, grid[:, 0], grid[:, k])
                                    for k in (1, 2, 3)], axis=1)
    plan.notes.append("Study enrollment bands and actuals-based milestone updates use A3 forecast / "
                      "update_with_actuals (2,000 draws). Site bands use the explicit operational "
                      "activation schedule and Poisson-gamma plan rates.")
    plan.notes.extend(prior.warnings)


def updated(plan, feed, upto, seed):
    """Every site reports its observed count; zero is an actual observation here."""
    from .plan import DAYS_PER_MONTH

    counts = feed.per_site("enrolled", upto)
    observed = {}
    t, s = feed.col("enrolled", "t"), feed.col("enrolled", "s").astype(int)
    design = plan.forecast_design
    # Activated backup sites join A3's design only once observed in the feed.
    backups = {site.id for site in plan.sites if site.backup and counts[site.idx] > 0}
    if backups:
        keep = {site.id for site in design.sites} | backups
        design = plan.design.model_copy(update={"sites": [site for site in plan.design.sites
                                                         if site.id in keep]})
    for site in design.sites:
        idx = plan.site_index()[site.id]
        times = t[(s == idx) & (t < upto)]
        points = [(float(times[0]) / DAYS_PER_MONTH, 1)] if len(times) else []
        points.append((upto / DAYS_PER_MONTH, int(counts[idx])))
        observed[site.id] = points
    return update_with_actuals(plan.forecast_prior, design, observed, plan.forecast_params, seed)

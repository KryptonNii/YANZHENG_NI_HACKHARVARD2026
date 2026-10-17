"""Site staff time (ScenarioResult.site_staff_hours).

Components (module in brackets):
- patient visits [patient_assessments]: admin minutes + Σ procedure minutes × mode factor (1 on site);
- on-site monitoring support and remote monitoring review [meetings_travel];
- data query handling [data_collection].
The same hour helpers feed the site-staff cost terms in cost.py.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ._contracts import Procedure
from .levers import Context, monitoring_visits
from .provenance import Inputs, ParamStore, Term, slug
from .uncertainty import FloatArray

HoursFn = Callable[[Context], tuple[FloatArray, Inputs]]


def procedure_minutes(ps: ParamStore, p: Procedure) -> FloatArray:
    """Design value (from the protocol) when given, else `time.site.procedure.<code>` / `.default`."""
    if p.site_minutes is not None:
        ps.note(f"Site minutes for `{p.code}` taken from the design ({p.site_minutes:g} min).")
        return np.full(ps.n, float(p.site_minutes))
    return ps.with_default("time.site.procedure", slug(p.code))


def visit_hours(ctx: Context) -> tuple[FloatArray, Inputs]:
    """Site staff hours for all patient visits."""
    act, ps = ctx.act, ctx.ps
    minutes_per_patient = ctx.zeros()
    for v in act.visits:
        procedures = ctx.zeros()
        for p in v.procedures:
            procedures = procedures + procedure_minutes(ps, p)
        factor = 1.0 if v.mode == "site" else ps.get(f"rate.site.minutes_factor.{v.mode}_visit")
        minutes_per_patient = minutes_per_patient + ps.get("time.site.visit_admin") + factor * procedures
    inputs: Inputs = {
        "patients": act.patients,
        "visits_per_patient": act.visits_per_patient,
        "procedures_per_patient": sum(len(v.procedures) for v in act.visits),
        "home_visits_per_patient": act.visits_in("home"),
        "telehealth_visits_per_patient": act.visits_in("remote"),
    }
    return act.patients * minutes_per_patient / 60.0, inputs


def monitoring_support_hours(ctx: Context) -> tuple[FloatArray, Inputs]:
    onsite, _, inputs = monitoring_visits(ctx)
    hours_per_visit = ctx.ps.get("time.site.monitoring_visit_support")
    return sum((v * hours_per_visit for v in onsite.values()), ctx.zeros()), inputs


def remote_review_hours(ctx: Context) -> tuple[FloatArray, Inputs]:
    _, remote, inputs = monitoring_visits(ctx)
    hours_per_visit = ctx.ps.get("time.site.remote_monitoring_review")
    return sum((v * hours_per_visit for v in remote.values()), ctx.zeros()), inputs


def query_hours(ctx: Context) -> tuple[FloatArray, Inputs]:
    ps = ctx.ps
    hours = ctx.act.patients * ps.get("rate.queries.per_patient") * ps.get("time.site.query_resolution") / 60.0
    return hours, {"patients": ctx.act.patients}


def has_onsite_monitoring(ctx: Context) -> bool:
    return ctx.act.sites > 0 and ctx.act.remote_monitoring_share < 1.0


def has_remote_monitoring(ctx: Context) -> bool:
    return ctx.act.sites > 0 and ctx.act.remote_monitoring_share > 0.0


def terms(ctx: Context) -> list[Term]:
    ps, act = ctx.ps, ctx.act
    out: list[Term] = []
    if act.patients and act.visits:
        with ps.track() as tr:
            hours, inputs = visit_hours(ctx)
        out.append(Term(
            "patient_assessments", "site_staff_hours", "workload.patient_visits.v1",
            "patients × Σ visits (admin minutes + Σ procedure minutes × mode factor) ÷ 60; "
            "mode factor = 1 on site, parameter for home / telehealth",
            hours, inputs, tr,
        ))
    if has_onsite_monitoring(ctx):
        with ps.track() as tr:
            hours, inputs = monitoring_support_hours(ctx)
        out.append(Term(
            "meetings_travel", "site_staff_hours", "workload.monitoring_support.v1",
            "on-site monitoring visits × site staff hours per visit",
            hours, inputs, tr,
        ))
    if has_remote_monitoring(ctx):
        with ps.track() as tr:
            hours, inputs = remote_review_hours(ctx)
        out.append(Term(
            "meetings_travel", "site_staff_hours", "workload.remote_monitoring_review.v1",
            "remote monitoring visits × site staff hours per remote review",
            hours, inputs, tr,
        ))
    if act.patients:
        with ps.track() as tr:
            hours, inputs = query_hours(ctx)
        out.append(Term(
            "data_collection", "site_staff_hours", "workload.query_handling.v1",
            "patients × queries per patient × minutes per query ÷ 60",
            hours, inputs, tr,
        ))
    return out

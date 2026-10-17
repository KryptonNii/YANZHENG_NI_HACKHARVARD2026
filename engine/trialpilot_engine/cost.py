"""Cost (USD) per §6 module: the same activity data as carbon.py, priced with cost parameters.

Site staff time is priced at `cost.site_staff.hour` in the module where the hours arise
(visits → patient_assessments, monitoring → meetings_travel, queries → data_collection).
"""

from __future__ import annotations

import numpy as np

from . import workload
from .levers import MONTHS_PER_YEAR, Context, drug_kits, monitoring_visits, sample_shipments
from .provenance import Inputs, Term, Trace
from .uncertainty import FloatArray

EXTENSION_NOTE = "drug_supply is a TrialPilot extension beyond the published method."


def _staff_cost(ctx: Context, module: str, formula_id: str, what: str,
                hours_fn: workload.HoursFn) -> Term:
    with ctx.ps.track() as tr:
        hours, inputs = hours_fn(ctx)
        usd = hours * ctx.ps.get("cost.site_staff.hour")
    return Term(module, "cost_usd", formula_id, f"site staff hours for {what} × hourly cost", usd, inputs, tr)


def _patient_assessments(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    out: list[Term] = []
    if not act.patients:
        return out
    if act.visits_in("site"):
        with ps.track() as tr:
            usd = act.patients * act.visits_in("site") * ps.get("cost.patient.reimbursement_visit")
        out.append(Term("patient_assessments", "cost_usd", "cost.patient_reimbursement.v1",
                        "patients × on-site visits × reimbursement per visit", usd,
                        {"patients": act.patients, "on_site_visits_per_patient": act.visits_in("site")}, tr))
    if act.visits_in("home"):
        with ps.track() as tr:
            usd = act.patients * act.visits_in("home") * ps.get("cost.home_nurse.visit")
        out.append(Term("patient_assessments", "cost_usd", "cost.home_nursing.v1",
                        "patients × home visits × home-nursing cost per visit", usd,
                        {"patients": act.patients, "home_visits_per_patient": act.visits_in("home")}, tr))
    if act.visits_in("remote"):
        with ps.track() as tr:
            usd = act.patients * act.visits_in("remote") * ps.get("cost.telehealth.visit")
        out.append(Term("patient_assessments", "cost_usd", "cost.telehealth.v1",
                        "patients × telehealth visits × cost per telehealth visit", usd,
                        {"patients": act.patients, "telehealth_visits_per_patient": act.visits_in("remote")}, tr))
    if act.visits:
        out.append(_staff_cost(ctx, "patient_assessments", "cost.site_staff_visits.v1", "patient visits",
                               workload.visit_hours))
    return out


def _meetings_travel(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    out: list[Term] = []
    if not act.sites:
        return out
    if workload.has_onsite_monitoring(ctx):
        with ps.track() as tr:
            onsite, _, inputs = monitoring_visits(ctx)
            per_visit = (ps.get("cost.monitoring.cra_day_rate") * ps.get("time.monitoring.onsite_visit_days")
                         + ps.get("cost.monitoring.travel_expenses_per_trip"))
            usd = sum(onsite.values(), ctx.zeros()) * per_visit
        out.append(Term("meetings_travel", "cost_usd", "cost.monitoring_onsite.v1",
                        "on-site monitoring visits × (CRA day rate × days per visit + travel expenses)",
                        usd, inputs, tr))
        out.append(_staff_cost(ctx, "meetings_travel", "cost.site_staff_monitoring.v1",
                               "supporting on-site monitoring visits", workload.monitoring_support_hours))
    if workload.has_remote_monitoring(ctx):
        with ps.track() as tr:
            _, remote, inputs = monitoring_visits(ctx)
            usd = (sum(remote.values(), ctx.zeros()) * ps.get("cost.monitoring.cra_day_rate")
                   * ps.get("time.monitoring.remote_visit_days"))
        out.append(Term("meetings_travel", "cost_usd", "cost.monitoring_remote.v1",
                        "remote monitoring visits × CRA day rate × days per remote visit", usd, inputs, tr))
        out.append(_staff_cost(ctx, "meetings_travel", "cost.site_staff_remote_review.v1",
                               "remote monitoring reviews", workload.remote_review_hours))
    with ps.track() as tr:
        usd = (act.sites * ps.get("rate.investigator_meeting.attendees_per_site")
               * ps.get("cost.investigator_meeting.per_attendee"))
    out.append(Term("meetings_travel", "cost_usd", "cost.investigator_meeting.v1",
                    "one kickoff meeting: sites × attendees per site × cost per attendee",
                    usd, {"active_sites": act.sites, "meetings": 1}, tr))
    return out


def _per_site(ctx: Context, module: str, formula_id: str, pid: str, what: str) -> list[Term]:
    if not ctx.act.sites:
        return []
    with ctx.ps.track() as tr:
        usd = ctx.act.sites * ctx.ps.get(pid)
    return [Term(module, "cost_usd", formula_id, f"sites × {what} cost per site", usd,
                 {"active_sites": ctx.act.sites}, tr)]


def _trial_management(ctx: Context) -> list[Term]:
    ps = ctx.ps
    with ps.track() as tr:
        usd = (ps.get("rate.trial_management.fte") * ctx.duration_months / MONTHS_PER_YEAR
               * ps.get("cost.trial_management.per_fte_year"))
    return [Term("trial_management", "cost_usd", "cost.trial_management.v1",
                 "coordinating-unit FTE × trial years × cost per FTE-year",
                 usd, {"duration_months_p50": float(np.median(ctx.duration_months))}, tr)]


def _data_collection(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    if not act.patients:
        return []
    with ps.track() as tr:
        usd = act.patients * ps.get("cost.data_collection.per_patient")
    return [
        Term("data_collection", "cost_usd", "cost.data_collection.v1", "patients × EDC + data management per patient",
             usd, {"patients": act.patients}, tr),
        _staff_cost(ctx, "data_collection", "cost.site_staff_queries.v1", "data queries", workload.query_hours),
    ]


def _supplies(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    if not act.patients:
        return []
    with ps.track() as tr:
        usd = act.patients * ps.get("cost.supplies_equipment.per_patient")
    return [Term("supplies_equipment", "cost_usd", "cost.supplies.v1", "patients × supplies cost per patient",
                 usd, {"patients": act.patients}, tr)]


def _samples(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    out: list[Term] = []
    with ps.track() as tr:
        shipments, inputs = sample_shipments(ctx)
        usd = ctx.zeros()
        for (_, temp), count in shipments.items():
            usd = usd + count * ps.get(f"cost.courier.shipment.{temp}")
    if shipments:
        out.append(Term("samples", "cost_usd", "cost.sample_courier.v1",
                        "central-lab shipments × courier cost per shipment (by temperature)", usd, inputs, tr))
    if act.local_lab_share > 0 and act.sites and any(act.samples_per_patient().values()):
        with ps.track() as tr:
            usd = act.local_lab_share * act.sites * ps.get("cost.lab.local_harmonisation_per_site")
        out.append(Term("samples", "cost_usd", "cost.local_lab_harmonisation.v1",
                        "local lab share × sites × harmonisation cost per site", usd,
                        {"local_lab_share": act.local_lab_share, "active_sites": act.sites}, tr))
    return out


def _laboratory(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    samples = sum(act.samples_per_patient().values())
    if not (samples and act.patients):
        return []
    local = act.local_lab_share
    with ps.track() as tr:
        per_sample: FloatArray = ctx.zeros()
        if local < 1.0:
            per_sample = per_sample + (1.0 - local) * ps.get("cost.lab.central_per_sample")
        if local > 0.0:
            per_sample = per_sample + local * ps.get("cost.lab.local_per_sample")
        usd = act.patients * samples * per_sample
    return [Term("laboratory", "cost_usd", "cost.lab_analysis.v1",
                 "patients × samples × ((1 − local share) × central price + local share × local price)",
                 usd, {"patients": act.patients, "samples_per_patient": samples, "local_lab_share": local}, tr)]


def _drug_supply(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    if drug_kits(ctx) is None:
        return []
    with ps.track() as tr_kits:
        flow = drug_kits(ctx)
        assert flow is not None
        kit_type = act.drug_type if act.drug_type in ("biologic", "small_molecule") else "default"
        kits = flow.kits_made * ps.with_default("cost.drug.kit", kit_type)
    with ps.track() as tr_ship:
        flow = drug_kits(ctx)
        assert flow is not None
        shipments = flow.shipments * ps.get("cost.drug.shipment")
    inputs: Inputs = {**flow.inputs, "source": flow.source, "drug_type": act.drug_type}
    return [
        Term("drug_supply", "cost_usd", "cost.drug_kits.v1", "kits made × cost per kit (by drug type)",
             kits, inputs, tr_kits, (EXTENSION_NOTE,)),
        Term("drug_supply", "cost_usd", "cost.drug_shipments.v1", "depot→site shipments × cost per shipment",
             shipments, inputs, tr_ship, (EXTENSION_NOTE,)),
    ]


def _intervention(ctx: Context) -> Term:
    return Term("intervention", "cost_usd", "cost.intervention_excluded.v1",
                "investigational product manufacture: excluded", ctx.zeros(), {}, Trace(),
                ("Drug manufacture excluded (as in the published method); see the drug_supply extension.",))


def terms(ctx: Context) -> list[Term]:
    return [
        *_patient_assessments(ctx),
        *_meetings_travel(ctx),
        *_per_site(ctx, "setup", "cost.setup.v1", "cost.setup.per_site", "site start-up"),
        *_per_site(ctx, "closeout", "cost.closeout.v1", "cost.closeout.per_site", "close-out"),
        *_trial_management(ctx),
        *_data_collection(ctx),
        *_supplies(ctx),
        *_samples(ctx),
        *_laboratory(ctx),
        *_drug_supply(ctx),
        _intervention(ctx),
    ]

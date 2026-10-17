"""Patient burden (ScenarioResult.patient_travel_hours) = travel time + time spent in visits.

Both terms belong to the `patient_assessments` module. Patient travel *km* (used by carbon and the
reimbursement cost) is computed here too, so every metric sees the same distances.
"""

from __future__ import annotations

from .levers import Context, CountryGroup
from .provenance import Inputs, Term
from .uncertainty import FloatArray

MODULE = "patient_assessments"


def patient_km(ctx: Context, g: CountryGroup) -> FloatArray:
    """Round-trip km travelled by one country's patients to on-site visits."""
    return g.patients * ctx.act.visits_in("site") * ctx.ps.regional("dist.patient.roundtrip_km", g.code)


def terms(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    out: list[Term] = []
    n_site, n_home, n_remote = act.visits_in("site"), act.visits_in("home"), act.visits_in("remote")

    if n_site and act.patients:
        with ps.track() as tr:
            hours = ctx.zeros()
            inputs: Inputs = {"on_site_visits_per_patient": n_site}
            for g in act.countries:
                hours = hours + patient_km(ctx, g) / ps.regional("time.patient.travel_speed_kmh", g.code)
                inputs[f"patients.{g.code}"] = g.patients
        out.append(Term(
            MODULE, "patient_travel_hours", "burden.patient_travel_time.v1",
            "patients × on-site visits × round-trip km ÷ door-to-door speed, per country",
            hours, inputs, tr,
        ))

    if act.patients and (n_site or n_home or n_remote):
        with ps.track() as tr:
            per_patient = ctx.zeros()
            if n_site:
                per_patient = per_patient + n_site * ps.get("time.patient.visit_at_site")
            if n_home:
                per_patient = per_patient + n_home * ps.get("time.patient.home_visit")
            if n_remote:
                per_patient = per_patient + n_remote * ps.get("time.patient.remote_visit")
        out.append(Term(
            MODULE, "patient_travel_hours", "burden.patient_visit_time.v1",
            "patients × (on-site visits × hours at site + home visits × hours + telehealth visits × hours)",
            act.patients * per_patient,
            {"patients": act.patients, "on_site_visits_per_patient": n_site,
             "home_visits_per_patient": n_home, "telehealth_visits_per_patient": n_remote},
            tr,
        ))
    return out

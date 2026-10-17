"""Carbon (kg CO2e) per §6 module: activity data × emission factor (Low Carbon Clinical Trials method,
Griffiths, Fox, Williamson, BMJ Open 2024). Only trial-specific activity beyond routine care.
The method adds well-to-tank (WTT) to every travel and freight factor, so each travel / freight term
`carbon.<name>.v1` has a twin `carbon.<name>_wtt.v1`: the same activity × the `ef.wtt.*` factors.
`drug_supply` is a TrialPilot extension beyond the published method; `intervention` is excluded.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from .burden import patient_km
from .levers import (
    DAYS_PER_MONTH,
    MONTHS_PER_YEAR,
    Context,
    drug_kits,
    monitoring_visits,
    sample_shipments,
)
from .provenance import Inputs, ParamStore, Term, Trace, slug
from .uncertainty import FloatArray

KG_PER_TONNE = 1000.0
EXTENSION_NOTE = "drug_supply is a TrialPilot extension beyond the published method."
WTT_NOTE = (
    "Well-to-tank (upstream fuel production and distribution, DESNZ 'WTT-' factors) is a separate term: "
    "the published method adds WTT to every travel and freight factor."
)

Factor = Callable[[str], FloatArray]
"""Lookup of a direct travel / freight factor id: `ps.get` (direct) or `wtt(ps)` (its well-to-tank twin)."""

# Well-to-tank twin of every direct travel and freight factor the engine reads. `ef.freight.air.tonne_km`
# is DESNZ's international air-freight row, which DESNZ sets equal to long-haul; the international WTT
# row equals the long-haul one (D96 = D95), which is the id the library carries.
WTT_FACTOR: dict[str, str] = {
    "ef.travel.car.average_km": "ef.wtt.travel.car.average_km",
    "ef.travel.bus.passenger_km": "ef.wtt.travel.bus.passenger_km",
    "ef.travel.rail.passenger_km": "ef.wtt.travel.rail.passenger_km",
    "ef.travel.flight.domestic.passenger_km": "ef.wtt.travel.flight.domestic.passenger_km",
    "ef.travel.flight.short_haul.passenger_km": "ef.wtt.travel.flight.short_haul.passenger_km",
    "ef.travel.flight.long_haul.passenger_km": "ef.wtt.travel.flight.long_haul.passenger_km",
    "ef.freight.van.tonne_km": "ef.wtt.freight.van.tonne_km",
    "ef.freight.air.tonne_km": "ef.wtt.freight.air.long_haul.tonne_km",
}


def wtt(ps: ParamStore) -> Factor:
    """Factor lookup that returns the well-to-tank twin of a direct factor (NaN draws if it is missing)."""
    return lambda pid: ps.get(WTT_FACTOR[pid])


def _unknown_where(values: FloatArray, *inputs: FloatArray) -> FloatArray:
    """NaN wherever any input is NaN (comparisons with NaN would otherwise pick a branch silently)."""
    bad = np.zeros(values.shape, dtype=bool)
    for x in inputs:
        bad |= np.isnan(x)
    return np.where(bad, np.nan, values)


def _with_wtt(
    ctx: Context,
    module: str,
    formula: str,
    description: str,
    kg_with: Callable[[Context, Factor], FloatArray],
    inputs: Inputs,
    assumptions: tuple[str, ...] = (),
) -> list[Term]:
    """`carbon.<formula>.v1` = kg_with(direct factors) and its twin `carbon.<formula>_wtt.v1` =
    kg_with(`ef.wtt.*` factors). A missing `ef.wtt.*` makes only the twin unknown (named in warnings and
    provenance, excluded from totals, never zero); the direct term is unaffected."""
    ps = ctx.ps
    with ps.track() as tr:
        kg = kg_with(ctx, ps.get)
    with ps.track() as tr_wtt:
        kg_wtt = kg_with(ctx, wtt(ps))
    return [
        Term(module, "co2e_kg", f"carbon.{formula}.v1", description, kg, inputs, tr, assumptions),
        Term(module, "co2e_kg", f"carbon.{formula}_wtt.v1",
             f"well-to-tank of the same activity: {description}, each factor replaced by its `ef.wtt.*` twin",
             kg_wtt, inputs, tr_wtt, (*assumptions, WTT_NOTE)),
    ]


def trip_kg(ps: ParamStore, country: str, ef: Factor) -> FloatArray:
    """One CRA round trip base → site within a country: by car, or a domestic flight when the one-way
    distance exceeds the flight threshold."""
    roundtrip = ps.regional("dist.monitoring.roundtrip_km", country)
    threshold = ps.get("dist.monitoring.flight_threshold_km")
    flown = roundtrip / 2.0 > threshold
    car = ef("ef.travel.car.average_km")
    per_km = np.where(flown, ef("ef.travel.flight.domestic.passenger_km"), car) if flown.any() else car
    return _unknown_where(roundtrip * per_km, roundtrip, threshold)


def _traveller_kg_per_km(ps: ParamStore, one_way: FloatArray, ef: Factor) -> FloatArray:
    """Per-traveller factor for a trip of `one_way` km: car up to the flight threshold, then a
    short-haul flight up to `dist.flight.short_haul_max_km`, then long-haul."""
    threshold = ps.get("dist.monitoring.flight_threshold_km")
    car = ef("ef.travel.car.average_km")
    flown = one_way > threshold
    if not flown.any():
        return _unknown_where(car, one_way, threshold)
    short_max = ps.get("dist.flight.short_haul_max_km")
    flight = np.where(
        one_way <= short_max,
        ef("ef.travel.flight.short_haul.passenger_km"),
        ef("ef.travel.flight.long_haul.passenger_km"),
    )
    return _unknown_where(np.where(flown, flight, car), one_way, threshold, short_max)


def _trips_to_every_site_kg(ctx: Context, ef: Factor) -> FloatArray:
    """Σ over countries: sites × one CRA round trip (site initiation or close-out visit)."""
    return sum((g.sites * trip_kg(ctx.ps, g.code, ef) for g in ctx.act.countries), ctx.zeros())


# ---------------------------------------------------------------- travel and freight activity × factor

def _patient_travel_kg(ctx: Context, ef: Factor) -> FloatArray:
    ps = ctx.ps
    kg = ctx.zeros()
    for g in ctx.act.countries:
        car = ps.regional("rate.patient.mode_share.car", g.code)
        rail = ps.regional("rate.patient.mode_share.rail", g.code)
        public = rail * ef("ef.travel.rail.passenger_km") + (1.0 - rail) * ef("ef.travel.bus.passenger_km")
        per_km = car * ef("ef.travel.car.average_km") + (1.0 - car) * public
        kg = kg + patient_km(ctx, g) * per_km
    return kg


def _home_nurse_kg(ctx: Context, ef: Factor) -> FloatArray:
    act = ctx.act
    return (act.patients * act.visits_in("home") * ctx.ps.get("dist.home_nurse.roundtrip_km")
            * ef("ef.travel.car.average_km"))


def _monitoring_trips_kg(ctx: Context, ef: Factor) -> FloatArray:
    onsite, _, _ = monitoring_visits(ctx)
    return sum((onsite[c] * trip_kg(ctx.ps, c, ef) for c in onsite), ctx.zeros())


def _investigator_meeting_kg(ctx: Context, ef: Factor) -> FloatArray:
    ps = ctx.ps
    attendees = ctx.act.sites * ps.get("rate.investigator_meeting.attendees_per_site")
    roundtrip = ps.get("dist.investigator_meeting.roundtrip_km")
    return attendees * roundtrip * _traveller_kg_per_km(ps, roundtrip / 2.0, ef)


def _sample_freight_kg(ctx: Context, ef: Factor) -> FloatArray:
    ps = ctx.ps
    shipments, _ = sample_shipments(ctx)
    freight = ctx.zeros()
    for (country, temp), count in shipments.items():
        tonnes = count * ps.get(f"supply.sample.shipment_weight_kg.{temp}") / KG_PER_TONNE
        km = ps.regional("dist.sample.to_central_lab_km", country)
        factor = ef("ef.freight.air.tonne_km" if temp == "frozen" else "ef.freight.van.tonne_km")
        freight = freight + tonnes * km * factor
    return freight


def _drug_shipping_kg(ctx: Context, ef: Factor) -> FloatArray:
    ps = ctx.ps
    flow = drug_kits(ctx)
    assert flow is not None
    return (flow.kits_made * ps.get("supply.kit_shipping_weight_kg") / KG_PER_TONNE
            * ps.get("dist.drug.depot_to_site_km") * ef("ef.freight.van.tonne_km"))


# ---------------------------------------------------------------- modules

def _patient_assessments(ctx: Context) -> list[Term]:
    act = ctx.act
    out: list[Term] = []
    if act.visits_in("site") and act.patients:
        inputs: Inputs = {"on_site_visits_per_patient": act.visits_in("site")}
        inputs.update({f"patients.{g.code}": g.patients for g in act.countries})
        out.extend(_with_wtt(
            ctx, "patient_assessments", "patient_travel",
            "patients × on-site visits × round-trip km × (car share × car factor + rest × "
            "(rail share × rail factor + bus share × bus factor)), per country",
            _patient_travel_kg, inputs,
            ("One patient per car trip (vehicle-km factor); companions add no car km.",),
        ))
    if act.visits_in("home") and act.patients:
        out.extend(_with_wtt(
            ctx, "patient_assessments", "home_nurse_travel",
            "patients × home visits × nurse round-trip km × car factor",
            _home_nurse_kg, {"patients": act.patients, "home_visits_per_patient": act.visits_in("home")},
        ))
    out.extend(_procedures(ctx))
    return out


def _procedures(ctx: Context) -> list[Term]:
    """Optional per-procedure factors `ef.procedure.<code>` (e.g. imaging energy). Procedures whose code
    has no factor in the library are named as not modelled; there is no `.default` for this one."""
    act, ps = ctx.act, ctx.ps
    if not act.patients:
        return []
    counted: dict[str, int] = {}
    unmodelled: set[str] = set()
    with ps.track() as tr:
        per_patient = ctx.zeros()
        for v in act.visits:
            for p in v.procedures:
                code = slug(p.code)
                if ps.has(f"ef.procedure.{code}"):
                    per_patient = per_patient + ps.get(f"ef.procedure.{code}")
                    counted[code] = counted.get(code, 0) + 1
                else:
                    unmodelled.add(code)
    if not counted:
        return []
    note = (f"No `ef.procedure.<code>` factor for: {', '.join(sorted(unmodelled))}; their procedure "
            "emissions are not modelled.",) if unmodelled else ()
    inputs: Inputs = {"patients": act.patients, **{f"per_patient.{c}": float(n) for c, n in counted.items()}}
    return [Term("patient_assessments", "co2e_kg", "carbon.procedures.v1",
                 "patients × Σ procedures that have a per-procedure factor `ef.procedure.<code>`",
                 act.patients * per_patient, inputs, tr, note)]


def _meetings_travel(ctx: Context) -> list[Term]:
    act = ctx.act
    out: list[Term] = []
    if act.sites and act.remote_monitoring_share < 1.0:
        _, _, inputs = monitoring_visits(ctx)
        out.extend(_with_wtt(
            ctx, "meetings_travel", "monitoring_trips",
            "on-site monitoring visits (sites × visits/site/month × months × (1 − remote share)) × "
            "round-trip km × (car factor, or domestic flight factor above the flight threshold)",
            _monitoring_trips_kg, inputs,
            ("Remote monitoring visits have no travel emissions.",),
        ))
    if act.sites:
        out.extend(_with_wtt(
            ctx, "meetings_travel", "investigator_meeting",
            "one kickoff meeting: sites × attendees per site × round-trip km × (car, short-haul or "
            "long-haul flight factor by one-way distance)",
            _investigator_meeting_kg, {"active_sites": act.sites, "meetings": 1},
        ))
    return out


def _setup(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    if not act.sites:
        return []
    trips = _with_wtt(ctx, "setup", "site_initiation_trips",
                      "sites × one site-initiation round trip (car or domestic flight)",
                      _trips_to_every_site_kg, {"active_sites": act.sites})
    with ps.track() as tr_sites:
        per_site = act.sites * ps.get("ef.setup.per_site")
    return [
        *trips,
        Term("setup", "co2e_kg", "carbon.setup_per_site.v1", "sites × set-up factor per site",
             per_site, {"active_sites": act.sites}, tr_sites),
    ]


def _closeout(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    if not act.sites:
        return []
    trips = _with_wtt(ctx, "closeout", "closeout_trips",
                      "sites × one close-out round trip (car or domestic flight)",
                      _trips_to_every_site_kg, {"active_sites": act.sites})
    with ps.track() as tr_archive:
        archive = (act.sites * ps.get("rate.closeout.archive_boxes_per_site")
                   * ps.get("time.closeout.archive_years") * ps.get("ef.closeout.archiving_per_box_year"))
    return [
        *trips,
        Term("closeout", "co2e_kg", "carbon.archiving.v1",
             "sites × archive boxes per site × retention years × factor per box-year",
             archive, {"active_sites": act.sites}, tr_archive),
    ]


def _trial_management(ctx: Context) -> list[Term]:
    ps = ctx.ps
    with ps.track() as tr:
        kg = (ps.get("rate.trial_management.fte") * ctx.duration_months / MONTHS_PER_YEAR
              * ps.get("ef.trial_management.per_fte_year"))
    return [Term("trial_management", "co2e_kg", "carbon.trial_management.v1",
                 "coordinating-unit FTE × trial years × factor per FTE-year",
                 kg, {"duration_months_p50": ctx.duration_p50}, tr)]


def _data_collection(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    if not act.patients:
        return []
    with ps.track() as tr:
        kg = act.patients * act.follow_up_years * ps.get("ef.data_collection.per_patient_year")
    return [Term("data_collection", "co2e_kg", "carbon.data_collection.v1",
                 "patients × years from first to last scheduled visit × factor per patient-year",
                 kg, {"patients": act.patients, "follow_up_years": act.follow_up_years}, tr)]


def _supplies(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    if not act.patients:
        return []
    with ps.track() as tr:
        kg = act.patients * ps.get("ef.supplies_equipment.per_patient")
    return [Term("supplies_equipment", "co2e_kg", "carbon.supplies.v1",
                 "patients × supplies factor per patient", kg, {"patients": act.patients}, tr)]


def _samples(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    out: list[Term] = []
    shipments, inputs = sample_shipments(ctx)
    if shipments:
        out.extend(_with_wtt(
            ctx, "samples", "sample_freight",
            "central-lab shipments (patients × samples × (1 − local lab share) ÷ samples per shipment) × "
            "kg ÷ 1000 × km × freight factor (frozen → air, ambient/refrigerated → van)",
            _sample_freight_kg, inputs,
        ))
    with ps.track() as tr:
        shipments, inputs = sample_shipments(ctx)
        frozen = [count for (_, temp), count in shipments.items() if temp == "frozen"]
        dry_ice = (sum(frozen, ctx.zeros()) * ps.get("supply.sample.dry_ice_kg_per_shipment")
                   * ps.get("ef.dry_ice.kg")) if frozen else ctx.zeros()
    if frozen:
        out.append(Term("samples", "co2e_kg", "carbon.dry_ice.v1",
                        "frozen shipments × kg dry ice per shipment × dry-ice factor", dry_ice, inputs, tr))
    if act.stores_minus80 and act.sites:
        with ps.track() as tr:
            kwh_per_site = (ps.get("energy.freezer.minus80.trial_share")
                            * ps.get("energy.freezer.minus80.kwh_per_day")
                            * ctx.duration_months * DAYS_PER_MONTH)
            storage = sum((g.sites * kwh_per_site * ps.regional("ef.electricity.grid", g.code)
                           for g in act.countries), ctx.zeros())
        out.append(Term(
            "samples", "co2e_kg", "carbon.freezer_storage.v1",
            "sites × trial share of one −80 °C freezer × kWh/day × trial days × grid factor (site country)",
            storage, {"active_sites": act.sites}, tr,
            ("−80 °C storage modelled at sites for the whole trial duration.",),
        ))
    return out


def _laboratory(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    samples = sum(act.samples_per_patient().values())
    if not (samples and act.patients):
        return []
    with ps.track() as tr:
        kg = act.patients * samples * ps.get("ef.laboratory.per_sample")
    return [Term("laboratory", "co2e_kg", "carbon.lab_analysis.v1",
                 "patients × samples per patient × factor per sample analysed (central or local)",
                 kg, {"patients": act.patients, "samples_per_patient": samples}, tr)]


def _drug_supply(ctx: Context) -> list[Term]:
    ps = ctx.ps
    flow = drug_kits(ctx)
    if flow is None:
        return []
    inputs: Inputs = {**flow.inputs, "source": flow.source}
    with ps.track() as tr_kits:
        flow = drug_kits(ctx)  # re-run inside the trace so its parameters are recorded
        assert flow is not None
        kits = flow.kits_made * ps.get("ef.drug_kit.unit")
    return [
        Term("drug_supply", "co2e_kg", "carbon.drug_kits.v1",
             "kits made (kits needed ÷ (1 − waste share)) × factor per kit",
             kits, inputs, tr_kits, (EXTENSION_NOTE,)),
        *_with_wtt(ctx, "drug_supply", "drug_shipping",
                   "kits made × kg per kit ÷ 1000 × depot→site km × van factor",
                   _drug_shipping_kg, inputs, (EXTENSION_NOTE,)),
    ]


def _intervention(ctx: Context) -> Term:
    return Term("intervention", "co2e_kg", "carbon.intervention_excluded.v1",
                "investigational product manufacture: excluded", ctx.zeros(), {}, Trace(),
                ("Drug manufacture excluded (as in the published method); see the drug_supply extension.",))


def terms(ctx: Context) -> list[Term]:
    return [
        *_patient_assessments(ctx),
        *_meetings_travel(ctx),
        *_setup(ctx),
        *_closeout(ctx),
        *_trial_management(ctx),
        *_data_collection(ctx),
        *_supplies(ctx),
        *_samples(ctx),
        *_laboratory(ctx),
        *_drug_supply(ctx),
        _intervention(ctx),
    ]

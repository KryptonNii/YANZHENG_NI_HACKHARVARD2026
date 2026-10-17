"""Carbon (kg CO2e) per §6 module: activity data × emission factor (Low Carbon Clinical Trials method,
Griffiths, Fox, Williamson, BMJ Open 2024). Only trial-specific activity beyond routine care.
`drug_supply` is a TrialPilot extension beyond the published method; `intervention` is excluded.
"""

from __future__ import annotations

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
from .provenance import Inputs, ParamStore, Term, Trace
from .uncertainty import FloatArray

KG_PER_TONNE = 1000.0
EXTENSION_NOTE = "drug_supply is a TrialPilot extension beyond the published method."


def _unknown_where(values: FloatArray, *inputs: FloatArray) -> FloatArray:
    """NaN wherever any input is NaN (comparisons with NaN would otherwise pick a branch silently)."""
    bad = np.zeros(values.shape, dtype=bool)
    for x in inputs:
        bad |= np.isnan(x)
    return np.where(bad, np.nan, values)


def trip_kg(ps: ParamStore, country: str) -> FloatArray:
    """One CRA round trip base → site within a country: by car, or a domestic flight when the one-way
    distance exceeds the flight threshold."""
    roundtrip = ps.regional("dist.monitoring.roundtrip_km", country)
    threshold = ps.get("dist.monitoring.flight_threshold_km")
    flown = roundtrip / 2.0 > threshold
    car = ps.get("ef.travel.car.average_km")
    per_km = np.where(flown, ps.get("ef.travel.flight.domestic.passenger_km"), car) if flown.any() else car
    return _unknown_where(roundtrip * per_km, roundtrip, threshold)


def _traveller_kg_per_km(ps: ParamStore, one_way: FloatArray) -> FloatArray:
    """Per-traveller factor for a trip of `one_way` km: car up to the flight threshold, then a
    short-haul flight up to `dist.flight.short_haul_max_km`, then long-haul."""
    threshold = ps.get("dist.monitoring.flight_threshold_km")
    car = ps.get("ef.travel.car.average_km")
    flown = one_way > threshold
    if not flown.any():
        return _unknown_where(car, one_way, threshold)
    short_max = ps.get("dist.flight.short_haul_max_km")
    flight = np.where(
        one_way <= short_max,
        ps.get("ef.travel.flight.short_haul.passenger_km"),
        ps.get("ef.travel.flight.long_haul.passenger_km"),
    )
    return _unknown_where(np.where(flown, flight, car), one_way, threshold, short_max)


def _trips_to_every_site_kg(ctx: Context) -> FloatArray:
    """Σ over countries: sites × one CRA round trip (site initiation or close-out visit)."""
    return sum((g.sites * trip_kg(ctx.ps, g.code) for g in ctx.act.countries), ctx.zeros())


# ---------------------------------------------------------------- modules

def _patient_assessments(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    out: list[Term] = []
    if act.visits_in("site") and act.patients:
        with ps.track() as tr:
            kg = ctx.zeros()
            inputs: Inputs = {"on_site_visits_per_patient": act.visits_in("site")}
            for g in act.countries:
                car = ps.regional("rate.patient.mode_share.car", g.code)
                rail = ps.regional("rate.patient.mode_share.rail", g.code)
                public = (rail * ps.get("ef.travel.rail.passenger_km")
                          + (1.0 - rail) * ps.get("ef.travel.bus.passenger_km"))
                per_km = car * ps.get("ef.travel.car.average_km") + (1.0 - car) * public
                kg = kg + patient_km(ctx, g) * per_km
                inputs[f"patients.{g.code}"] = g.patients
        out.append(Term(
            "patient_assessments", "co2e_kg", "carbon.patient_travel.v1",
            "patients × on-site visits × round-trip km × (car share × car factor + rest × "
            "(rail share × rail factor + bus share × bus factor)), per country",
            kg, inputs, tr,
            ("One patient per car trip (vehicle-km factor); companions add no car km.",),
        ))
    if act.visits_in("home") and act.patients:
        with ps.track() as tr:
            kg = (act.patients * act.visits_in("home") * ps.get("dist.home_nurse.roundtrip_km")
                  * ps.get("ef.travel.car.average_km"))
        out.append(Term(
            "patient_assessments", "co2e_kg", "carbon.home_nurse_travel.v1",
            "patients × home visits × nurse round-trip km × car factor",
            kg, {"patients": act.patients, "home_visits_per_patient": act.visits_in("home")}, tr,
        ))
    return out


def _meetings_travel(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    out: list[Term] = []
    if act.sites and act.remote_monitoring_share < 1.0:
        with ps.track() as tr:
            onsite, _, inputs = monitoring_visits(ctx)
            kg = sum((onsite[c] * trip_kg(ps, c) for c in onsite), ctx.zeros())
        out.append(Term(
            "meetings_travel", "co2e_kg", "carbon.monitoring_trips.v1",
            "on-site monitoring visits (sites × visits/site/month × months × (1 − remote share)) × "
            "round-trip km × (car factor, or domestic flight factor above the flight threshold)",
            kg, inputs, tr,
            ("Remote monitoring visits have no travel emissions.",),
        ))
    if act.sites:
        with ps.track() as tr:
            attendees = act.sites * ps.get("rate.investigator_meeting.attendees_per_site")
            roundtrip = ps.get("dist.investigator_meeting.roundtrip_km")
            kg = attendees * roundtrip * _traveller_kg_per_km(ps, roundtrip / 2.0)
        out.append(Term(
            "meetings_travel", "co2e_kg", "carbon.investigator_meeting.v1",
            "one kickoff meeting: sites × attendees per site × round-trip km × (car, short-haul or "
            "long-haul flight factor by one-way distance)",
            kg, {"active_sites": act.sites, "meetings": 1}, tr,
        ))
    return out


def _setup(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    if not act.sites:
        return []
    with ps.track() as tr_trips:
        trips = _trips_to_every_site_kg(ctx)
    with ps.track() as tr_sites:
        per_site = act.sites * ps.get("ef.setup.per_site")
    return [
        Term("setup", "co2e_kg", "carbon.site_initiation_trips.v1",
             "sites × one site-initiation round trip (car or domestic flight)",
             trips, {"active_sites": act.sites}, tr_trips),
        Term("setup", "co2e_kg", "carbon.setup_per_site.v1", "sites × set-up factor per site",
             per_site, {"active_sites": act.sites}, tr_sites),
    ]


def _closeout(ctx: Context) -> list[Term]:
    act, ps = ctx.act, ctx.ps
    if not act.sites:
        return []
    with ps.track() as tr_trips:
        trips = _trips_to_every_site_kg(ctx)
    with ps.track() as tr_archive:
        archive = (act.sites * ps.get("rate.closeout.archive_boxes_per_site")
                   * ps.get("time.closeout.archive_years") * ps.get("ef.closeout.archiving_per_box_year"))
    return [
        Term("closeout", "co2e_kg", "carbon.closeout_trips.v1",
             "sites × one close-out round trip (car or domestic flight)",
             trips, {"active_sites": act.sites}, tr_trips),
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
                 kg, {"duration_months_p50": float(np.median(ctx.duration_months))}, tr)]


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
    with ps.track() as tr:
        shipments, inputs = sample_shipments(ctx)
        freight = ctx.zeros()
        for (country, temp), count in shipments.items():
            tonnes = count * ps.get(f"supply.sample.shipment_weight_kg.{temp}") / KG_PER_TONNE
            km = ps.regional("dist.sample.to_central_lab_km", country)
            factor = ps.get("ef.freight.air.tonne_km" if temp == "frozen" else "ef.freight.van.tonne_km")
            freight = freight + tonnes * km * factor
    if shipments:
        out.append(Term(
            "samples", "co2e_kg", "carbon.sample_freight.v1",
            "central-lab shipments (patients × samples × (1 − local lab share) ÷ samples per shipment) × "
            "kg ÷ 1000 × km × freight factor (frozen → air, ambient/refrigerated → van)",
            freight, inputs, tr,
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
    if drug_kits(ctx) is None:
        return []
    with ps.track() as tr_kits:
        flow = drug_kits(ctx)
        assert flow is not None
        kits = flow.kits_made * ps.get("ef.drug_kit.unit")
    with ps.track() as tr_ship:
        flow = drug_kits(ctx)
        assert flow is not None
        shipping = (flow.kits_made * ps.get("supply.kit_shipping_weight_kg") / KG_PER_TONNE
                    * ps.get("dist.drug.depot_to_site_km") * ps.get("ef.freight.van.tonne_km"))
    inputs: Inputs = {**flow.inputs, "source": flow.source}
    return [
        Term("drug_supply", "co2e_kg", "carbon.drug_kits.v1",
             "kits made (kits needed ÷ (1 − waste share)) × factor per kit",
             kits, inputs, tr_kits, (EXTENSION_NOTE,)),
        Term("drug_supply", "co2e_kg", "carbon.drug_shipping.v1",
             "kits made × kg per kit ÷ 1000 × depot→site km × van factor",
             shipping, inputs, tr_ship, (EXTENSION_NOTE,)),
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

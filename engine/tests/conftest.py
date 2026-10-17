"""Shared fixtures for A2 engine tests.

`unit_params`: every catalog parameter as a point value (low = mid = high), with round TEST numbers
chosen so expected values can be computed by hand. They are NOT real-world values.
`ranged_params`: the same ids with triangular ranges, for uncertainty / determinism / performance tests.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from trialpilot_contracts import Levers, Parameter, Procedure, Site, TrialDesign, Visit

# id → test value (units as in PARAMETER_CATALOG). TEST VALUES ONLY.
UNIT_VALUES: dict[str, float] = {
    # patient
    "dist.patient.roundtrip_km.global": 20, "dist.patient.roundtrip_km.gb": 30,
    "rate.patient.mode_share.car.global": 0.5, "rate.patient.mode_share.rail.global": 0.5,
    "time.patient.travel_speed_kmh.global": 30, "time.patient.visit_at_site": 2,
    "time.patient.home_visit": 1, "time.patient.remote_visit": 0.5,
    "ef.travel.car.average_km": 0.2, "ef.travel.bus.passenger_km": 0.1, "ef.travel.rail.passenger_km": 0.05,
    "cost.patient.reimbursement_visit": 50, "cost.home_nurse.visit": 300,
    "dist.home_nurse.roundtrip_km": 40, "cost.telehealth.visit": 100,
    # site staff
    "time.site.visit_admin": 30, "time.site.procedure.default": 10, "time.site.procedure.blood_draw": 15,
    "rate.site.minutes_factor.home_visit": 0.5, "rate.site.minutes_factor.remote_visit": 0.8,
    "time.site.monitoring_visit_support": 4, "time.site.remote_monitoring_review": 2,
    "rate.queries.per_patient": 6, "time.site.query_resolution": 10, "cost.site_staff.hour": 60,
    # monitoring + meetings
    "rate.monitoring.onsite_visits_per_site_month": 0.5,
    "dist.monitoring.roundtrip_km.global": 200, "dist.monitoring.roundtrip_km.gb": 1000,
    "dist.monitoring.flight_threshold_km": 300,
    "ef.travel.flight.domestic.passenger_km": 0.25, "ef.travel.flight.short_haul.passenger_km": 0.15,
    "ef.travel.flight.long_haul.passenger_km": 0.2, "dist.flight.short_haul_max_km": 3700,
    "cost.monitoring.cra_day_rate": 1000, "time.monitoring.onsite_visit_days": 1.5,
    "time.monitoring.remote_visit_days": 0.5, "cost.monitoring.travel_expenses_per_trip": 400,
    "rate.investigator_meeting.attendees_per_site": 2, "dist.investigator_meeting.roundtrip_km": 1000,
    "cost.investigator_meeting.per_attendee": 1500,
    # setup, closeout, management, data, supplies
    "ef.setup.per_site": 100, "cost.setup.per_site": 20000, "cost.closeout.per_site": 5000,
    "rate.closeout.archive_boxes_per_site": 2, "time.closeout.archive_years": 25,
    "ef.closeout.archiving_per_box_year": 0.5,
    "rate.trial_management.fte": 2, "ef.trial_management.per_fte_year": 1000,
    "cost.trial_management.per_fte_year": 120000,
    "ef.data_collection.per_patient_year": 10, "cost.data_collection.per_patient": 500,
    "ef.supplies_equipment.per_patient": 5, "cost.supplies_equipment.per_patient": 100,
    # samples + lab
    "supply.sample.samples_per_shipment": 1,
    "supply.sample.shipment_weight_kg.ambient": 2, "supply.sample.shipment_weight_kg.refrigerated": 3,
    "supply.sample.shipment_weight_kg.frozen": 5, "dist.sample.to_central_lab_km.global": 500,
    "ef.freight.van.tonne_km": 0.6, "ef.freight.air.tonne_km": 2.0,
    "supply.sample.dry_ice_kg_per_shipment": 4, "ef.dry_ice.kg": 0.5,
    "cost.courier.shipment.ambient": 50, "cost.courier.shipment.refrigerated": 80,
    "cost.courier.shipment.frozen": 200,
    "energy.freezer.minus80.kwh_per_day": 10, "energy.freezer.minus80.trial_share": 0.1,
    "ef.electricity.grid.global": 0.2, "cost.lab.local_harmonisation_per_site": 3000,
    "ef.laboratory.per_sample": 1, "cost.lab.central_per_sample": 40, "cost.lab.local_per_sample": 30,
    # drug supply
    "supply.kits_per_dispensing_visit": 1, "supply.waste_share.upfront": 0.5,
    "supply.waste_share.on_demand": 0.2, "supply.shipments_per_site.upfront": 2,
    "supply.shipments_per_site.on_demand": 6, "cost.drug.kit.biologic": 1000, "cost.drug.kit.default": 200,
    "ef.drug_kit.unit": 10, "supply.kit_shipping_weight_kg": 2, "dist.drug.depot_to_site_km": 500,
    "cost.drug.shipment": 150,
    # design fall-backs
    "assume.design.visits_per_patient": 4, "assume.design.patients_per_site": 10,
}


def make_param(pid: str, low: float, mid: float, high: float) -> Parameter:
    return Parameter(
        id=pid, label=f"TEST {pid}", value_low=low, value_mid=mid, value_high=high, unit="test",
        assumption=True, rationale="unit-test fixture, not a real value",
    )


def point_params(values: dict[str, float]) -> dict[str, Parameter]:
    return {pid: make_param(pid, v, v, v) for pid, v in values.items()}


def spread_params(values: dict[str, float]) -> dict[str, Parameter]:
    """±20 % triangular ranges; shares stay below 1."""
    out: dict[str, Parameter] = {}
    for pid, v in values.items():
        low, high = v * 0.8, v * 1.2
        if pid.startswith(("rate.patient.mode_share", "supply.waste_share", "rate.site.minutes_factor",
                           "energy.freezer.minus80.trial_share")):
            high = min(high, 0.95)
        out[pid] = make_param(pid, low, v, high)
    return out


@pytest.fixture
def unit_params() -> dict[str, Parameter]:
    return point_params(UNIT_VALUES)


@pytest.fixture
def ranged_params() -> dict[str, Parameter]:
    return spread_params(UNIT_VALUES)


def tiny_design(country: str = "Spain", **overrides: object) -> TrialDesign:
    """1 site, 10 patients, 12 months, 3 visits (weeks 0, 26, 52)."""
    visits = [
        Visit(number=1, label="Screening", week=0, procedures=[
            Procedure(code="blood_draw", label="Blood draw", ships_sample=True, sample_temp="frozen_-80"),
            Procedure(code="ecg", label="ECG"),
            Procedure(code="drug_dispensing", label="Dispense IP"),
        ]),
        Visit(number=2, label="Week 26", week=26, can_be_remote=True, procedures=[
            Procedure(code="blood_draw", label="Blood draw", ships_sample=True, sample_temp="ambient"),
            Procedure(code="drug_dispensing", label="Dispense IP"),
        ]),
        Visit(number=3, label="Week 52", week=52, can_be_remote=True, procedures=[
            Procedure(code="questionnaire", label="QoL questionnaire", site_minutes=20),
        ]),
    ]
    data: dict[str, object] = dict(
        id="tiny", source="fixture", title="Tiny test trial", enrollment_target=10, duration_months=12,
        sites=[Site(id="s1", name="Site 1", country=country)], visits=visits, drug_type="biologic",
    )
    data.update(overrides)
    return TrialDesign.model_validate(data)


def large_design(n_sites: int = 120, patients: int = 900, n_visits: int = 12) -> TrialDesign:
    """Performance-size design: sites spread over 8 countries, 12 visits with 6 procedures each."""
    countries = ["United States", "United Kingdom", "Spain", "Germany", "France", "Poland", "Japan", "Brazil"]
    sites = [Site(id=f"s{i}", name=f"Site {i}", country=countries[i % len(countries)],
                  expected_enrollment=float(5 + i % 7)) for i in range(n_sites)]
    visits = []
    for k in range(n_visits):
        procs = [
            Procedure(code="vital_signs", label="Vitals"),
            Procedure(code="physical_exam", label="Exam"),
            Procedure(code="blood_draw", label="Safety labs", ships_sample=True, sample_temp="ambient"),
            Procedure(code="pk_sample", label="PK", ships_sample=True, sample_temp="frozen_-80"),
            Procedure(code="ecg", label="ECG"),
            Procedure(code="drug_dispensing", label="Dispense IP"),
        ]
        visits.append(Visit(number=k + 1, label=f"V{k + 1}", week=4.0 * k, procedures=procs,
                            can_be_remote=k % 3 == 2))
    return TrialDesign(id="large", source="fixture", title="Performance trial", enrollment_target=patients,
                       duration_months=36, sites=sites, visits=visits, drug_type="biologic")


@pytest.fixture
def tiny() -> Callable[..., TrialDesign]:
    return tiny_design


@pytest.fixture
def large() -> Callable[..., TrialDesign]:
    return large_design


@pytest.fixture
def base_levers() -> Levers:
    return Levers()

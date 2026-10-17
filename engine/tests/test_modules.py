"""Hand-computed values per module for the tiny design with point (TEST) parameters.

Tiny design (conftest.tiny_design): 1 site in Spain (no `.es` params → `.global`), P = 10 patients,
D = 12 months, biologic, all visits on site (default levers):
  V1 week 0:  blood_draw (sample, frozen −80; 15 min param), ecg (default 10 min), drug_dispensing (10 min)
  V2 week 26: blood_draw (sample, ambient; 15 min), drug_dispensing (10 min)
  V3 week 52: questionnaire (20 min given in the design)
Parameter values: tests/conftest.py UNIT_VALUES.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from trialpilot_contracts import Levers, Parameter, ScenarioResult, TrialDesign

from trialpilot_engine import compute_scenario

WEEKS_PER_YEAR = 365.25 / 7
DAYS_PER_MONTH = 365.25 / 12


def module(r: ScenarioResult, name: str) -> tuple[float, float]:
    m = next(m for m in r.modules if m.module == name)
    return m.cost_usd.p50, m.co2e_kg.p50


@pytest.fixture
def baseline(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> ScenarioResult:
    return compute_scenario(tiny(), Levers(), unit_params, draws=20)


def test_point_parameters_give_point_ranges(baseline: ScenarioResult) -> None:
    for r in (baseline.cost_usd, baseline.co2e_kg, baseline.site_staff_hours, baseline.patient_travel_hours):
        assert r.p10 == pytest.approx(r.p50) == pytest.approx(r.p90)


def test_no_missing_parameter_warnings(baseline: ScenarioResult) -> None:
    assert not [w for w in baseline.warnings if "missing parameter" in w]


def test_patient_burden(baseline: ScenarioResult) -> None:
    # travel: P × on-site visits × km ÷ speed = 10 × 3 × 20 ÷ 30 = 20 h
    # visits: P × 3 × 2 h at site = 60 h
    assert baseline.patient_travel_hours.p50 == pytest.approx(80.0)


def test_site_staff_hours(baseline: ScenarioResult) -> None:
    # visits, minutes per patient: V1 30 + (15 + 10 + 10) = 65; V2 30 + (15 + 10) = 55; V3 30 + 20 = 50
    #   → 170 min × 10 patients ÷ 60 = 28.333 h
    # monitoring: 1 site × 0.5 visits/month × 12 months = 6 on-site visits × 4 h = 24 h
    # queries: 10 × 6 queries × 10 min ÷ 60 = 10 h
    assert baseline.site_staff_hours.p50 == pytest.approx(1700 / 60 + 24 + 10)


def test_patient_assessments(baseline: ScenarioResult) -> None:
    # carbon: km = 10 × 3 × 20 = 600; per km = 0.5 × 0.2 + 0.5 × (0.5 × 0.05 + 0.5 × 0.1) = 0.1375
    # cost: reimbursement 10 × 3 × 50 = 1500 + site staff 28.333 h × 60 = 1700
    assert module(baseline, "patient_assessments") == pytest.approx((3200.0, 82.5))


def test_meetings_travel(baseline: ScenarioResult) -> None:
    # 6 on-site trips; global round trip 200 km, one way 100 < 300 threshold → car: 200 × 0.2 = 40 kg/trip
    # kickoff: 1 site × 2 attendees × 1000 km; one way 500 > 300 → flown, ≤ 3700 → short haul 0.15 → 300 kg
    # cost: 6 × (1000 × 1.5 + 400) = 11400; site staff 24 h × 60 = 1440; kickoff 2 × 1500 = 3000
    assert module(baseline, "meetings_travel") == pytest.approx((15840.0, 6 * 40 + 300))


def test_setup_and_closeout(baseline: ScenarioResult) -> None:
    # setup: initiation trip 40 kg + 100 kg per site; cost 20000 per site
    # closeout: close-out trip 40 kg + archive 1 × 2 boxes × 25 years × 0.5 = 25 kg; cost 5000 per site
    assert module(baseline, "setup") == pytest.approx((20000.0, 140.0))
    assert module(baseline, "closeout") == pytest.approx((5000.0, 65.0))


def test_trial_management(baseline: ScenarioResult) -> None:
    # 2 FTE × 12/12 years × 1000 kg and × 120000 usd
    assert module(baseline, "trial_management") == pytest.approx((240000.0, 2000.0))


def test_data_collection(baseline: ScenarioResult) -> None:
    # carbon: 10 patients × (52 − 0) weeks ÷ 52.18 weeks/year × 10 kg per patient-year
    # cost: 10 × 500 + queries 10 h × 60
    assert module(baseline, "data_collection") == pytest.approx((5600.0, 10 * 52 / WEEKS_PER_YEAR * 10))


def test_supplies_equipment(baseline: ScenarioResult) -> None:
    assert module(baseline, "supplies_equipment") == pytest.approx((10 * 100.0, 10 * 5.0))


def test_samples(baseline: ScenarioResult) -> None:
    # shipments (1 sample each): frozen 10, ambient 10
    # freight: frozen 10 × 5 kg ÷ 1000 × 500 km × 2.0 (air) = 50; ambient 10 × 2 ÷ 1000 × 500 × 0.6 (van) = 6
    # dry ice: 10 frozen × 4 kg × 0.5 = 20
    # −80 freezer: 1 site × 0.1 share × 10 kWh/day × 12 × 30.4375 days × 0.2 = 73.05
    # cost: courier 10 × 200 + 10 × 50 = 2500
    freezer = 1 * 0.1 * 10 * 12 * DAYS_PER_MONTH * 0.2
    assert module(baseline, "samples") == pytest.approx((2500.0, 50 + 6 + 20 + freezer))


def test_laboratory(baseline: ScenarioResult) -> None:
    # 10 patients × 2 samples: carbon × 1 kg; cost × 40 usd central
    assert module(baseline, "laboratory") == pytest.approx((800.0, 20.0))


def test_drug_supply(baseline: ScenarioResult) -> None:
    # dispensing visits V1, V2 → kits needed 10 × 2 × 1 = 20; upfront waste 0.5 → made 40
    # carbon: 40 × 10 + shipping 40 × 2 kg ÷ 1000 × 500 km × 0.6 = 24
    # cost: 40 × 1000 (biologic) + 1 site × 2 shipments × 150
    assert module(baseline, "drug_supply") == pytest.approx((40300.0, 424.0))
    assert baseline.drug_waste_share.p50 == pytest.approx(50.0)


def test_intervention_is_zero_and_explained(baseline: ScenarioResult) -> None:
    assert module(baseline, "intervention") == (0.0, 0.0)
    assert any("Drug manufacture excluded" in w or "drug manufacture is excluded" in w for w in baseline.warnings)


def test_totals_are_sums_of_modules(baseline: ScenarioResult) -> None:
    assert baseline.cost_usd.p50 == pytest.approx(334240.0)
    assert baseline.co2e_kg.p50 == pytest.approx(sum(m.co2e_kg.p50 for m in baseline.modules))
    assert baseline.duration_months.p50 == 12.0


def test_country_specific_parameters_and_domestic_flights(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    r = compute_scenario(tiny(country="United Kingdom"), Levers(), unit_params, draws=10)
    # GB patient round trip 30 km: travel 10 × 3 × 30 ÷ 30 = 30 h + 60 h at site
    assert r.patient_travel_hours.p50 == pytest.approx(90.0)
    # GB CRA round trip 1000 km, one way 500 > 300 → domestic flight 1000 × 0.25 = 250 kg/trip × 6 + kickoff 300
    assert module(r, "meetings_travel")[1] == pytest.approx(6 * 250 + 300)
    prov = next(m for m in r.modules if m.module == "meetings_travel").provenance
    trips = next(p for p in prov if p.formula_id == "carbon.monitoring_trips.v1")
    assert "dist.monitoring.roundtrip_km.gb" in trips.parameter_ids


def test_provenance_lists_formula_parameters_and_fallbacks(baseline: ScenarioResult) -> None:
    prov = next(m for m in baseline.modules if m.module == "patient_assessments").provenance
    travel = next(p for p in prov if p.formula_id == "carbon.patient_travel.v1")
    assert "dist.patient.roundtrip_km.global" in travel.parameter_ids
    assert travel.inputs["result_p50"] == pytest.approx(82.5)
    assert any("`dist.patient.roundtrip_km.es`" in a for a in travel.assumptions)  # fallback is explained
    # every module item carries a formula id, a description and its parameters
    for m in baseline.modules:
        for p in m.provenance:
            assert p.formula_id and p.description
            assert p.formula_id.split(".")[0] in {"cost", "carbon", "workload", "burden"}

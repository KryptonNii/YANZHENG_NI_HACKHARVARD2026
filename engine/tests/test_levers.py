"""Each lever changes what it should (hand-computed, point TEST parameters) and nothing else
(per-draw equality with ranged parameters and common random numbers)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from pydantic import ValidationError
from trialpilot_contracts import Levers, Parameter, ScenarioResult, Site, TrialDesign

from trialpilot_engine import EngineInputError, compute_scenario, scenario_draws
from trialpilot_engine.levers import _sites, build_activity
from trialpilot_engine.model import ScenarioDraws

ALL_MODULES = ("setup", "trial_management", "meetings_travel", "intervention", "data_collection",
               "supplies_equipment", "patient_assessments", "samples", "laboratory", "closeout", "drug_supply")


def module(r: ScenarioResult, name: str) -> tuple[float, float]:
    m = next(m for m in r.modules if m.module == name)
    return m.cost_usd.p50, m.co2e_kg.p50


def draws_of(r: ScenarioResult) -> ScenarioDraws:
    d = scenario_draws(r)
    assert d is not None
    return d


def changed_keys(a: ScenarioResult, b: ScenarioResult) -> set[str]:
    da, db = draws_of(a), draws_of(b)
    return {k for k in da.metrics if not np.array_equal(da.metrics[k], db.metrics[k])}


def module_keys(*modules: str) -> set[str]:
    return {f"{metric}.{m}" for m in modules for metric in ("cost_usd", "co2e_kg")}


# ---------------------------------------------------------------- hand-computed effects

@pytest.mark.parametrize(("field", "value"), [
    ("enrollment_rate_multiplier", 0.49), ("enrollment_rate_multiplier", 1.51),
    ("enrollment_rate_multiplier", float("nan")),
    ("added_country_count", -1), ("added_country_count", 6), ("added_country_count", 1.5),
])
def test_design_lever_bounds(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        Levers.model_validate({field: value})


@pytest.mark.parametrize(("rate", "countries"), [(0.5, 0), (1.0, 2), (1.5, 5)])
def test_design_lever_bounds_are_inclusive(rate: float, countries: int) -> None:
    levers = Levers(enrollment_rate_multiplier=rate, added_country_count=countries)
    assert levers.enrollment_rate_multiplier == rate
    assert levers.added_country_count == countries


def test_zero_added_countries_preserves_sites(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter],
) -> None:
    d = tiny(sites=[Site(id=f"s{i}", name=f"Site {i}", country="US") for i in range(3)])
    sites, notes = _sites(d, Levers(added_country_count=0), unit_params, warnings := [])
    assert sites == d.sites
    assert all(a is b for a, b in zip(sites, d.sites, strict=True))
    assert notes == warnings == []
    included, _ = _sites(d, Levers(excluded_site_ids=["s1"], added_country_count=0), unit_params, [])
    assert included == [d.sites[0], d.sites[2]]
    implicit = compute_scenario(d, Levers(), unit_params, draws=20)
    explicit = compute_scenario(d, Levers(added_country_count=0), unit_params, draws=20)
    assert implicit.model_dump(exclude={"computed_at"}) == explicit.model_dump(exclude={"computed_at"})


def test_added_countries_use_median_and_participate_in_activity(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter],
) -> None:
    d = tiny(sites=[Site(id=f"s{i}", name=f"Site {i}", country="US", expected_enrollment=e)
                    for i, e in enumerate([10, 20, 30])])
    original = d.model_dump()
    levers = Levers(added_country_count=2)
    sites, notes = _sites(d, levers, unit_params, warnings := [])
    # A median of 20 patients is an enrollment weight, never 20 sites per country.
    assert len(sites) == 5
    assert [s.id for s in sites[3:]] == [f"assumed-country-{n}-site-1" for n in (1, 2)]
    assert all(s.country == "assumed" and s.expected_enrollment == 20 for s in sites[3:])
    assert all(s.lat is None and s.lon is None for s in sites[3:])
    assert "Added countries are assumptions, not registry sites." in warnings
    assert any("one site" in note and "median" in note and "(20)" in note for note in notes)
    assert all(note in warnings for note in notes)
    act = build_activity(d, levers, unit_params)
    assert act.sites == 5
    assert sum(c.patients for c in act.countries) == pytest.approx(d.enrollment_target)
    assert next(c for c in act.countries if c.code == "assumed").patients == pytest.approx(4)
    base = compute_scenario(d, Levers(), unit_params, draws=20)
    added = compute_scenario(d, levers, unit_params, draws=20)
    assert module(added, "meetings_travel")[0] > module(base, "meetings_travel")[0]
    monitoring = next(m for m in added.modules if m.module == "meetings_travel")
    assert any(p.inputs.get("active_sites") == 5 for p in monitoring.provenance)
    assert "Added countries are assumptions, not registry sites." in added.warnings
    assert d.model_dump() == original


@pytest.mark.parametrize("expected", [None, 0.0, -10.0, float("nan"), float("inf")])
def test_added_countries_without_median_assume_one_site(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter], expected: float | None,
) -> None:
    d = tiny(sites=[Site(id="s1", name="Site 1", country="US", expected_enrollment=expected)])
    sites, notes = _sites(d, Levers(added_country_count=2), unit_params, warnings := [])
    assert len(sites) == 3
    assert [s.id for s in sites[1:]] == ["assumed-country-1-site-1", "assumed-country-2-site-1"]
    assert all(s.expected_enrollment == unit_params["assume.design.patients_per_site"].value_mid
               for s in sites[1:])
    assert any("assume.design.patients_per_site" in note for note in notes)
    assert all(note in warnings for note in notes)
    assert "Added countries are assumptions, not registry sites." in warnings


def test_added_country_weight_uses_only_active_positive_finite_sites(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter],
) -> None:
    d = tiny(sites=[Site(id=f"s{i}", name=f"Site {i}", country="US", expected_enrollment=e)
                    for i, e in enumerate([10, 20, 30, 1000, 0, -10, float("nan"), float("inf")])])
    sites, _ = _sites(d, Levers(added_country_count=1, excluded_site_ids=["s3"]), unit_params, [])
    assert len(sites) == 8  # seven retained sites and one assumed site
    assert sites[-1].id == "assumed-country-1-site-1"
    assert sites[-1].expected_enrollment == 20


def test_infinite_expected_enrollment_is_unknown_in_allocation(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter],
) -> None:
    d = tiny(sites=[Site(id="a", name="A", country="US", expected_enrollment=10),
                    Site(id="b", name="B", country="GB", expected_enrollment=float("inf"))])
    act = build_activity(d, Levers(), unit_params)
    assert {g.code: g.patients for g in act.countries} == {"gb": 5.0, "us": 5.0}
    assert "1 sites have no expected enrollment: given the mean of the others." in act.notes
    r = compute_scenario(d, Levers(), unit_params, draws=10)
    assert r.patient_travel_hours.p50 is not None
    assert not any("unknown input" in w for w in r.warnings)


def test_remote_monitoring_half(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    r = compute_scenario(tiny(), Levers(remote_monitoring_share=0.5), unit_params, draws=10)
    # 6 monitoring visits → 3 on site (40 kg + 10 kg WTT each) + 3 remote; kickoff 300 + 60 kg WTT unchanged
    # cost: 3 × 1900 + 3 × 1000 × 0.5 + staff (3 × 4 h + 3 × 2 h) × 60 + kickoff 3000
    assert module(r, "meetings_travel") == pytest.approx((5700 + 1500 + 18 * 60 + 3000, 3 * (40 + 10) + 360))
    # staff: visits 28.333 + support 12 + remote review 6 + queries 10
    assert r.site_staff_hours.p50 == pytest.approx(1700 / 60 + 12 + 6 + 10)


def test_full_remote_monitoring_has_no_onsite_trips(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    r = compute_scenario(tiny(), Levers(remote_monitoring_share=1.0), unit_params, draws=10)
    prov = next(m for m in r.modules if m.module == "meetings_travel").provenance
    ids = {p.formula_id for p in prov}
    assert "carbon.monitoring_trips.v1" not in ids and "cost.monitoring_onsite.v1" not in ids
    assert module(r, "meetings_travel")[1] == pytest.approx(300.0 + 60.0)  # only the kickoff meeting (+ WTT)


def test_home_visit(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    r = compute_scenario(tiny(), Levers(home_visit_numbers=[2]), unit_params, draws=10)
    # patient: travel 10 × 2 × 20 ÷ 30 = 13.333 h; visits 10 × (2 × 2 h + 1 × 1 h) = 50 h
    assert r.patient_travel_hours.p50 == pytest.approx(10 * 2 * 20 / 30 + 50)
    # carbon: patient km 10 × 2 × 20 × 0.1375 = 55; nurse 10 × 1 × 40 km × 0.2 = 80
    #   WTT: patient 400 km × 0.0325 = 13; nurse 400 km × 0.05 = 20
    # staff minutes V2: 30 + 0.5 × 25 = 42.5 → (65 + 42.5 + 50) × 10 ÷ 60 = 26.25 h
    # cost: reimbursement 10 × 2 × 50 + nursing 10 × 300 + staff 26.25 × 60
    assert module(r, "patient_assessments") == pytest.approx((1000 + 3000 + 26.25 * 60, 55 + 13 + 80 + 20))
    # an honest trade-off: this lever costs more than it saves
    base = compute_scenario(tiny(), Levers(), unit_params, draws=10)
    assert r.cost_usd.p50 > base.cost_usd.p50
    assert r.co2e_kg.p50 > base.co2e_kg.p50  # nurse drives 40 km vs patient 20 km in this test set


def test_telehealth_visit(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    r = compute_scenario(tiny(), Levers(remote_visit_numbers=[3]), unit_params, draws=10)
    # patient: travel 10 × 2 × 20 ÷ 30; visits 10 × (2 × 2 + 1 × 0.5)
    assert r.patient_travel_hours.p50 == pytest.approx(10 * 2 * 20 / 30 + 45)
    # staff V3: 30 + 0.8 × 20 = 46 min → (65 + 55 + 46) × 10 ÷ 60
    # cost: 10 × 2 × 50 + 10 × 1 × 100 + staff
    staff_visits = (65 + 55 + 46) * 10 / 60
    assert module(r, "patient_assessments") == pytest.approx((1000 + 1000 + staff_visits * 60, 55.0 + 13.0))


def test_telehealth_visit_with_samples_warns(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    r = compute_scenario(tiny(), Levers(remote_visit_numbers=[2]), unit_params, draws=10)
    assert any("Telehealth visit 2" in w and "samples are still counted" in w for w in r.warnings)


def test_not_remote_capable_visit_warns(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    r = compute_scenario(tiny(), Levers(home_visit_numbers=[1]), unit_params, draws=10)
    assert any("Visit 1" in w and "not marked remote-capable" in w for w in r.warnings)


def test_local_labs(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    r = compute_scenario(tiny(), Levers(local_lab_share=1.0), unit_params, draws=10)
    freezer = 1 * 0.1 * 10 * 12 * (365.25 / 12) * 0.2
    # no shipments → only freezer storage; harmonisation 1.0 × 1 site × 3000
    assert module(r, "samples") == pytest.approx((3000.0, freezer))
    # lab: 10 × 2 samples × 30 local
    assert module(r, "laboratory") == pytest.approx((600.0, 20.0))


def test_on_demand_supply(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    r = compute_scenario(tiny(), Levers(drug_supply_strategy="on_demand"), unit_params, draws=10)
    # waste 0.2 → made 20 ÷ 0.8 = 25: carbon 250 + 25 × 2 ÷ 1000 × 500 × 0.6 = 15
    #   + WTT 25 tonne-km × 0.15 = 3.75; cost 25000 + 6 × 150
    assert module(r, "drug_supply") == pytest.approx((25900.0, 268.75))
    assert r.drug_waste_share.p50 == pytest.approx(20.0)


def test_removed_procedure(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    r = compute_scenario(tiny(), Levers(removed_procedures=["blood_draw"]), unit_params, draws=10)
    # minutes per patient: V1 30 + 20, V2 30 + 10, V3 30 + 20 = 140 → 23.333 h + 24 + 10
    assert r.site_staff_hours.p50 == pytest.approx(1400 / 60 + 24 + 10)
    # no samples left: no shipments, no −80 storage, no lab analyses
    assert module(r, "samples") == (0.0, 0.0)
    assert module(r, "laboratory") == (0.0, 0.0)


def test_excluded_sites(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    two_sites = tiny(sites=[Site(id="s1", name="A", country="Spain"), Site(id="s2", name="B", country="Spain")])
    both = compute_scenario(two_sites, Levers(), unit_params, draws=10)
    one = compute_scenario(two_sites, Levers(excluded_site_ids=["s2"]), unit_params, draws=10)
    # monitoring trips halve (12 → 6), patients stay 10 (redistributed); + WTT: car 10 kg/trip, flight 0.03/km
    assert module(both, "meetings_travel")[1] == pytest.approx(12 * (40 + 10) + 2 * 2 * 1000 * (0.15 + 0.03))
    assert module(one, "meetings_travel")[1] == pytest.approx(6 * (40 + 10) + 2 * 1000 * (0.15 + 0.03))
    assert one.patient_travel_hours.p50 == pytest.approx(both.patient_travel_hours.p50)
    assert module(one, "setup")[0] == pytest.approx(module(both, "setup")[0] / 2)


def test_all_sites_excluded_is_an_input_error(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    with pytest.raises(EngineInputError) as exc:
        compute_scenario(tiny(), Levers(excluded_site_ids=["s1"]), unit_params, draws=10)
    assert exc.value.code == "invalid_levers"


@pytest.mark.parametrize("levers", [Levers(remote_monitoring_share=1.5), Levers(local_lab_share=-0.1)])
def test_out_of_range_shares_are_input_errors(
    levers: Levers, tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    with pytest.raises(EngineInputError):
        compute_scenario(tiny(), levers, unit_params, draws=10)


def test_unknown_lever_targets_warn(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    r = compute_scenario(tiny(), Levers(home_visit_numbers=[9], removed_procedures=["mri"],
                                        excluded_site_ids=["nope"]), unit_params, draws=10)
    text = " ".join(r.warnings)
    assert "[9]" in text and "mri" in text and "nope" in text


# ---------------------------------------------------------------- isolation (per draw, ranged)

def test_remote_monitoring_never_changes_patient_travel(
    large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]
) -> None:
    d = large(n_sites=20, patients=100, n_visits=6)
    a = compute_scenario(d, Levers(), ranged_params, draws=300)
    b = compute_scenario(d, Levers(remote_monitoring_share=0.6), ranged_params, draws=300)
    assert changed_keys(a, b) == {"cost_usd", "co2e_kg", "site_staff_hours", *module_keys("meetings_travel")}


def test_home_visits_never_change_monitoring(
    large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]
) -> None:
    d = large(n_sites=20, patients=100, n_visits=6)
    a = compute_scenario(d, Levers(), ranged_params, draws=300)
    b = compute_scenario(d, Levers(home_visit_numbers=[3, 6]), ranged_params, draws=300)
    changed = changed_keys(a, b)
    assert not changed & module_keys("meetings_travel")
    assert changed == {"cost_usd", "co2e_kg", "site_staff_hours", "patient_travel_hours",
                       *module_keys("patient_assessments")}


def test_local_labs_change_only_samples_and_laboratory(
    large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]
) -> None:
    d = large(n_sites=20, patients=100, n_visits=6)
    a = compute_scenario(d, Levers(), ranged_params, draws=300)
    b = compute_scenario(d, Levers(local_lab_share=0.5), ranged_params, draws=300)
    # analysis carbon per sample is the same locally or centrally: only the lab *price* changes
    assert changed_keys(a, b) == {"cost_usd", "co2e_kg", *module_keys("samples"), "cost_usd.laboratory"}


def test_on_demand_changes_only_drug_supply(
    large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]
) -> None:
    d = large(n_sites=20, patients=100, n_visits=6)
    a = compute_scenario(d, Levers(), ranged_params, draws=300)
    b = compute_scenario(d, Levers(drug_supply_strategy="on_demand"), ranged_params, draws=300)
    assert changed_keys(a, b) == {"cost_usd", "co2e_kg", "drug_waste_share", *module_keys("drug_supply")}


def test_every_module_is_reported_in_contract_order(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    r = compute_scenario(tiny(), Levers(), unit_params, draws=5)
    assert tuple(m.module for m in r.modules) == ALL_MODULES


def test_a4_vocabulary_dispensing_and_temperature(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    from trialpilot_contracts import Procedure, Visit

    visits = [
        Visit(number=1, label="Day 1", week=0, procedures=[Procedure(code="imp_administration", label="Infusion")]),
        Visit(number=2, label="Week 4", week=4, procedures=[
            Procedure(code="imp_administration", label="Infusion"),
            Procedure(code="pk_sample", label="PK", ships_sample=True),  # temperature not stated
        ]),
    ]
    r = compute_scenario(tiny(visits=visits), Levers(), unit_params, draws=5)
    # 2 administration visits × 10 patients × 1 kit = 20 needed; upfront waste 0.5 → 40 made × $1000 + 2 × $150
    assert module(r, "drug_supply")[0] == pytest.approx(40300.0)
    assert any("no storage temperature" in w for w in r.warnings)

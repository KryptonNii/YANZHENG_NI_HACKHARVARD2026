"""Public API behaviour: determinism, ordering, monotonicity, compare, drivers, missing inputs, A3 inputs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from trialpilot_contracts import Levers, MetricRange, Parameter, ScenarioResult, TrialDesign

from trialpilot_engine import (
    PARAMETER_CATALOG,
    DrawsUnavailableError,
    EngineInputError,
    compare,
    compare_levers,
    compute_scenario,
    drivers,
    missing_parameters,
)
from trialpilot_engine.provenance import catalog_patterns

HEADLINE = ("cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg", "duration_months", "drug_waste_share")
DOCS = Path(__file__).resolve().parents[2] / "docs" / "model.md"


def ranges(r: ScenarioResult) -> list[MetricRange]:
    return [getattr(r, k) for k in HEADLINE] + [x for m in r.modules for x in (m.cost_usd, m.co2e_kg)]


def test_deterministic_for_a_seed(large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]) -> None:
    d, lv = large(n_sites=30, patients=200), Levers(remote_monitoring_share=0.3)
    a = compute_scenario(d, lv, ranged_params, seed=11, draws=500)
    b = compute_scenario(d, lv, ranged_params, seed=11, draws=500)
    c = compute_scenario(d, lv, ranged_params, seed=12, draws=500)
    assert a.model_dump(exclude={"computed_at"}) == b.model_dump(exclude={"computed_at"})
    assert a.cost_usd != c.cost_usd


def test_percentiles_are_ordered(large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]) -> None:
    r = compute_scenario(large(n_sites=30, patients=200), Levers(home_visit_numbers=[2]), ranged_params, draws=500)
    for x in ranges(r):
        assert x.p10 <= x.p50 <= x.p90
    assert r.cost_usd.p10 < r.cost_usd.p90  # ranged parameters give a real band


def test_more_patients_means_more_of_every_metric(
    large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]
) -> None:
    small = compute_scenario(large(n_sites=30, patients=200), Levers(), ranged_params, draws=500)
    big = compute_scenario(large(n_sites=30, patients=400), Levers(), ranged_params, draws=500)
    for k in ("cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg"):
        assert getattr(big, k).p50 > getattr(small, k).p50, k


def test_compare_is_per_draw(large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]) -> None:
    d = large(n_sites=30, patients=200)
    a, b, delta = compare_levers(d, Levers(), Levers(remote_monitoring_share=0.5), ranged_params, draws=1000)
    assert set(HEADLINE) <= set(delta)
    # same scenario → exactly zero deltas
    same = compare(a, a)
    assert all(v.p10 == v.p50 == v.p90 == 0.0 for v in same.values())
    # per-draw delta is much tighter than the difference of independent bands
    d_cost = delta["cost_usd"]
    assert d_cost.p90 < 0  # remote monitoring saves money in every reasonable draw (test parameters)
    assert d_cost.p90 - d_cost.p10 < 0.5 * (b.cost_usd.p90 - b.cost_usd.p10)
    assert delta["patient_travel_hours"].p50 == 0.0
    assert delta["cost_usd.meetings_travel"].p50 < 0


def test_compare_refuses_results_without_draws(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    a = compute_scenario(tiny(), Levers(), unit_params, draws=10)
    reloaded = ScenarioResult.model_validate_json(a.model_dump_json())
    with pytest.raises(DrawsUnavailableError):
        compare(a, reloaded)
    other_seed = compute_scenario(tiny(), Levers(), unit_params, seed=99, draws=10)
    with pytest.raises(DrawsUnavailableError):
        compare(a, other_seed)


def test_drivers(large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]) -> None:
    d = large(n_sites=30, patients=200)
    top = drivers(d, Levers(), ranged_params, "cost_usd", top=5, draws=1000)
    assert len(top) == 5
    shares = [s for _, s in top]
    assert shares == sorted(shares, reverse=True) and all(0 <= s <= 1 for s in shares)
    assert all(pid in ranged_params for pid, _ in top)
    module_top = drivers(d, Levers(), ranged_params, "co2e_kg.samples", top=3, draws=1000)
    assert {pid for pid, _ in module_top} <= {p for p in ranged_params if "sample" in p or "freight" in p
                                              or "freezer" in p or "grid" in p or "dry_ice" in p}
    with pytest.raises(EngineInputError):
        drivers(d, Levers(), ranged_params, "happiness")


def test_missing_parameter_is_unknown_not_zero(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    params = {k: v for k, v in unit_params.items() if k != "ef.dry_ice.kg"}
    r = compute_scenario(tiny(), Levers(), params, draws=10)
    full = compute_scenario(tiny(), Levers(), unit_params, draws=10)
    # the dry-ice term (20 kg) is excluded, not zeroed silently: it is named in warnings and provenance
    assert r.co2e_kg.p50 == pytest.approx(full.co2e_kg.p50 - 20.0)
    assert any("`ef.dry_ice.kg`" in w and "carbon.dry_ice.v1" in w for w in r.warnings)
    samples = next(m for m in r.modules if m.module == "samples")
    dry = next(p for p in samples.provenance if p.formula_id == "carbon.dry_ice.v1")
    assert str(dry.inputs["result"]).startswith("unknown")
    assert any("MISSING" in a for a in dry.assumptions)
    assert missing_parameters(tiny(), Levers(), params) == ["ef.dry_ice.kg"]


def test_empty_library_gives_unknown_totals(tiny: Callable[..., TrialDesign]) -> None:
    r = compute_scenario(tiny(), Levers(), {}, draws=10)
    for unknown in (r.cost_usd, r.co2e_kg):  # contract v2: unknown = all three percentiles None
        assert (unknown.p10, unknown.p50, unknown.p90) == (None, None, None)
    assert json.loads(r.model_dump_json())["cost_usd"]["p50"] is None
    assert len([w for w in r.warnings if "missing parameter" in w]) > 20


def test_missing_visit_schedule_uses_labelled_assumption(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    r = compute_scenario(tiny(visits=[]), Levers(), unit_params, draws=10)
    assert any("Visit schedule missing → 4 visits assumed" in w for w in r.warnings)
    # 4 visits on site: travel 10 × 4 × 20 ÷ 30 + 10 × 4 × 2 h
    assert r.patient_travel_hours.p50 == pytest.approx(10 * 4 * 20 / 30 + 80)
    without = {k: v for k, v in unit_params.items() if k != "assume.design.visits_per_patient"}
    with pytest.raises(EngineInputError) as exc:
        compute_scenario(tiny(visits=[]), Levers(), without, draws=10)
    assert exc.value.code == "design_incomplete"


def test_missing_sites_use_labelled_assumption(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    r = compute_scenario(tiny(sites=[], enrollment_target=25), Levers(), unit_params, draws=10)
    assert any("3 sites assumed" in w for w in r.warnings)  # ceil(25 ÷ 10)


@dataclass
class FakeForecast:
    duration_months: MetricRange


@dataclass
class FakeSupply:
    kits_needed: MetricRange
    kits_produced: MetricRange
    kits_wasted: MetricRange
    waste_share: MetricRange
    shipments: MetricRange
    stockout_probability: float


def test_uses_a3_forecast_and_supply(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    forecast = FakeForecast(MetricRange(p10=14, p50=16, p90=20, unit="months"))
    supply = FakeSupply(
        kits_needed=MetricRange(p10=20, p50=20, p90=20, unit="kits"),
        kits_produced=MetricRange(p10=24, p50=25, p90=27, unit="kits"),
        kits_wasted=MetricRange(p10=4, p50=5, p90=7, unit="kits"),
        waste_share=MetricRange(p10=17, p50=20, p90=26, unit="percent"),
        shipments=MetricRange(p10=5, p50=6, p90=8, unit="kits"),
        stockout_probability=0.02,
    )
    r = compute_scenario(tiny(), Levers(drug_supply_strategy="on_demand"), unit_params, draws=4000,
                         forecast=forecast, supply=supply)
    assert (r.duration_months.p10, r.duration_months.p50, r.duration_months.p90) == pytest.approx((14, 16, 20), rel=0.02)
    assert r.drug_waste_share.p50 == pytest.approx(20.0, rel=0.02)
    drug = next(m for m in r.modules if m.module == "drug_supply")
    assert drug.cost_usd.p50 == pytest.approx(25 * 1000 + 6 * 150, rel=0.02)
    assert drug.provenance[0].inputs["source"] == "A3 drug supply simulation"
    # longer forecast duration → more trial management than the 12-month plan
    tm = next(m for m in r.modules if m.module == "trial_management")
    assert tm.cost_usd.p50 == pytest.approx(2 * 16 / 12 * 120000, rel=0.02)
    assert not any("planned duration" in w for w in r.warnings)


def test_unknown_a3_ranges_give_unknown_terms_not_errors(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    def unknown(unit: str) -> MetricRange:
        return MetricRange.model_validate({"p10": None, "p50": None, "p90": None, "unit": unit})

    supply = FakeSupply(kits_needed=unknown("kits"), kits_produced=unknown("kits"), kits_wasted=unknown("kits"),
                        waste_share=unknown("percent"), shipments=unknown("kits"), stockout_probability=0.0)
    r = compute_scenario(tiny(), Levers(), unit_params, draws=10,
                         forecast=FakeForecast(unknown("months")), supply=supply)
    assert r.duration_months.p50 is None and r.drug_waste_share.p50 is None
    for name in ("drug_supply", "trial_management"):  # kit flow / duration unknown → module unknown
        m = next(m for m in r.modules if m.module == name)
        assert m.cost_usd.p50 is None and m.co2e_kg.p50 is None, name
    drug = next(m for m in r.modules if m.module == "drug_supply")
    assert drug.provenance[0].inputs["kits_produced_p50"] == "unknown"
    assert any("forecast's duration is unknown" in w for w in r.warnings)
    assert any("unknown kits_produced, waste_share, shipments" in w for w in r.warnings)
    # terms that need neither stay known: totals are understated (warned), not zero and not all unknown
    assert r.patient_travel_hours.p50 == pytest.approx(80.0)
    assert r.cost_usd.p50 is not None and r.co2e_kg.p50 is not None
    body = json.loads(r.model_dump_json())  # provenance inputs stay JSON numbers or strings
    assert body["duration_months"]["p50"] is None


def test_every_requested_parameter_is_in_the_catalog(tiny: Callable[..., TrialDesign]) -> None:
    design = tiny(country="United Kingdom")
    levers = Levers(remote_monitoring_share=0.5, home_visit_numbers=[2], remote_visit_numbers=[3],
                    local_lab_share=0.5)
    patterns = catalog_patterns()
    asked = missing_parameters(design, levers, {})
    assert asked
    stray = [pid for pid in asked if not any(p.match(pid) for p in patterns)]
    assert not stray, f"ids used in code but missing from PARAMETER_CATALOG: {stray}"


def test_catalog_ids_are_valid_slugs_and_documented() -> None:
    slug = re.compile(r"^[a-z0-9_]+(\.([a-z0-9_]+|<[a-z_]+>))+$")
    assert all(slug.match(pid) for pid in PARAMETER_CATALOG)
    if not DOCS.exists():
        pytest.skip("docs/model.md not written yet")
    text = DOCS.read_text(encoding="utf-8")
    undocumented = [pid for pid in PARAMETER_CATALOG if f"`{pid}`" not in text]
    assert not undocumented, f"parameters missing from docs/model.md: {undocumented}"


def test_rejects_zero_draws(tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]) -> None:
    with pytest.raises(EngineInputError):
        compute_scenario(tiny(), Levers(), unit_params, draws=0)

"""A3 — drug supply simulation tests (upfront vs on-demand, conservation, expiry, stockouts, speed).

Parameter values below are TEST values unless a test says it checks the built-in calibration.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import pytest
from trialpilot_contracts import Levers, Parameter, Procedure, Site, TrialDesign, Visit

from trialpilot_engine.forecast import forecast, update_with_actuals
from trialpilot_engine.supply import SupplyDraws, compare_strategies, simulate_supply

UPFRONT = Levers(drug_supply_strategy="upfront")
ON_DEMAND = Levers(drug_supply_strategy="on_demand")


def p(pid: str, low: float, mid: float | None = None, high: float | None = None) -> Parameter:
    mid = low if mid is None else mid
    high = mid if high is None else high
    return Parameter(
        id=pid, label=pid, value_low=low, value_mid=mid, value_high=high, unit="test",
        assumption=True, rationale="TEST value",
    )


def with_params(**overrides: float) -> dict[str, Parameter]:
    return {k.replace("__", "."): p(k.replace("__", "."), v) for k, v in overrides.items()}


def design(
    n_sites: int = 40, target: int = 400, duration: float = 30.0, n_disp: int = 13,
    code: str = "drug_dispensing", drug_type: str = "biologic",
) -> TrialDesign:
    sites = [Site(id=f"site-{i:03d}", name=f"Site {i}", country="US") for i in range(n_sites)]
    visits = [Visit(number=1, label="Screening", week=-2)] + [
        Visit(number=i + 2, label=f"Week {4 * i}", week=4 * i, procedures=[Procedure(code=code, label="IP")])
        for i in range(n_disp)
    ] + [Visit(number=99, label="Follow-up", week=4 * n_disp + 4)]
    return TrialDesign(
        id="test-design", source="fixture", title="TEST", enrollment_target=target,
        duration_months=duration, sites=sites, visits=visits, drug_type=drug_type,  # type: ignore[arg-type]
    )


@pytest.fixture(scope="module")
def base() -> tuple[TrialDesign, object]:
    d = design()
    return d, forecast(d, Levers(), {}, draws=1000)


def per(r: object) -> SupplyDraws:
    pd = r.per_draw  # type: ignore[attr-defined]
    assert pd is not None
    return pd  # type: ignore[no-any-return]


# ---------------------------------------------------------------- accounting


@pytest.mark.parametrize("levers", [UPFRONT, ON_DEMAND], ids=["upfront", "on_demand"])
def test_conservation_per_draw(base: tuple[TrialDesign, object], levers: Levers) -> None:
    d, fc = base
    pd = per(simulate_supply(d, levers, {}, fc, draws=200))  # type: ignore[arg-type]
    assert np.array_equal(pd.kits_produced, pd.kits_needed + pd.kits_expired + pd.kits_destroyed_at_close)
    assert np.all(pd.kits_needed > 0) and np.all(pd.kits_wasted >= 0)


def test_dispensed_kits_match_the_schedule() -> None:
    # No dropout, 1 kit per visit: every patient gets all 13 dispensings → needed = patients × 13.
    d = design(n_sites=5, target=50)
    prm = with_params(patient__dropout_rate=0.0, supply__kits_per_dispensing_visit=1.0)
    fc = forecast(d, Levers(), prm, draws=50)
    pd = per(simulate_supply(d, ON_DEMAND, prm, fc, draws=50))
    assert np.all(pd.kits_needed == 50 * 13)


def test_kits_per_visit_scales_demand(base: tuple[TrialDesign, object]) -> None:
    d, fc = base
    one = per(simulate_supply(d, ON_DEMAND, {}, fc, draws=100))  # type: ignore[arg-type]
    two = per(simulate_supply(d, ON_DEMAND, with_params(supply__kits_per_dispensing_visit=2.0), fc, draws=100))  # type: ignore[arg-type]
    assert np.array_equal(two.kits_needed, 2 * one.kits_needed)


# ---------------------------------------------------------------- strategies


def test_on_demand_wastes_less_than_upfront_on_the_same_draws(base: tuple[TrialDesign, object]) -> None:
    d, fc = base
    res = compare_strategies(d, Levers(), {}, fc, draws=300)  # type: ignore[arg-type]
    up, od = per(res["upfront"]), per(res["on_demand"])
    assert np.array_equal(up.kits_needed, od.kits_needed)  # same patients (common random numbers)
    share_up = up.kits_wasted / up.kits_produced
    share_od = od.kits_wasted / od.kits_produced
    assert np.all(share_od <= share_up)
    assert res["on_demand"].waste_share.p50 < res["upfront"].waste_share.p50
    # the honest trade-off: on-demand ships more often
    assert res["on_demand"].shipments.p50 > res["upfront"].shipments.p50


def test_upfront_waste_lands_in_the_industry_range(base: tuple[TrialDesign, object]) -> None:
    """Calibration check of the BUILT-IN defaults: IQVIA (2024) reports a median IMP kit waste of 50%;
    ZS (2025) reports 60% of manufactured clinical supplies lost. Upfront P50 must land in 40–65%."""
    d, fc = base
    r = simulate_supply(d, UPFRONT, {}, fc)  # type: ignore[arg-type]
    assert 40.0 <= r.waste_share.p50 <= 65.0


# ---------------------------------------------------------------- expiry and stockouts


def test_shelf_life_expiry_is_counted_as_waste(base: tuple[TrialDesign, object]) -> None:
    d, fc = base
    short = per(simulate_supply(d, UPFRONT, with_params(supply__shelf_life_months=6.0), fc, draws=100))  # type: ignore[arg-type]
    long = per(simulate_supply(d, UPFRONT, with_params(supply__shelf_life_months=240.0), fc, draws=100))  # type: ignore[arg-type]
    assert np.all(short.kits_expired > 0)
    assert np.all(long.kits_expired == 0)
    assert np.all(short.kits_wasted >= short.kits_expired)
    assert np.array_equal(short.kits_produced, short.kits_needed + short.kits_wasted)


def test_product_specific_shelf_life_takes_precedence(base: tuple[TrialDesign, object]) -> None:
    d, fc = base
    prm = with_params(supply__shelf_life_months=240.0)
    prm["supply.shelf_life_months.biologic"] = p("supply.shelf_life_months.biologic", 6.0)
    r = simulate_supply(d, UPFRONT, prm, fc, draws=50)  # type: ignore[arg-type]
    assert np.all(per(r).kits_expired > 0)
    assert "supply.shelf_life_months.biologic" in r.provenance[0].parameter_ids


def test_stockout_probability_reported_with_warning_above_threshold(base: tuple[TrialDesign, object]) -> None:
    d, fc = base
    lean = with_params(
        supply__resupply_lead_time_weeks=6.0, supply__on_demand__cover_weeks=1.0,
        supply__site_safety_stock_kits=0.0, supply__stockout_warning_threshold=0.05,
    )
    r = simulate_supply(d, ON_DEMAND, lean, fc, draws=100)  # type: ignore[arg-type]
    assert r.stockout_probability > 0.05
    assert any("stockout" in w for w in r.warnings)
    assert r.emergency_shipments is not None and r.emergency_shipments.p50 > 0
    ok = simulate_supply(d, ON_DEMAND, {}, fc, draws=100)  # type: ignore[arg-type]
    assert 0.0 <= ok.stockout_probability <= 1.0
    assert ok.stockout_probability <= r.stockout_probability


# ---------------------------------------------------------------- inputs and honesty


def test_dispensing_codes_follow_a2_and_a4_vocabulary() -> None:
    a = design(n_sites=5, target=40, code="imp_administration")
    fc = forecast(a, Levers(), {}, draws=50)
    r = simulate_supply(a, ON_DEMAND, {}, fc, draws=50)
    assert r.provenance[0].inputs["dispensing_visits_per_patient"] == 13.0
    b = design(n_sites=5, target=40, code="vital_signs")  # no dispensing code → stated assumption
    r2 = simulate_supply(b, ON_DEMAND, {}, forecast(b, Levers(), {}, draws=50), draws=50)
    assert r2.provenance[0].inputs["dispensing_visits_per_patient"] == 13.0  # all but the last visit
    assert any("No dispensing procedure" in a for a in r2.provenance[0].assumptions)


def test_designs_without_drug_report_zero_kits_with_warning() -> None:
    d = design(n_sites=5, target=40, drug_type="device")
    r = simulate_supply(d, ON_DEMAND, {}, forecast(d, Levers(), {}, draws=50))
    assert r.kits_produced.p90 == 0 and r.waste_share.p50 == 0
    assert "no investigational drug" in r.warnings[0]


def test_missing_parameters_are_named(base: tuple[TrialDesign, object]) -> None:
    d, fc = base
    r = simulate_supply(d, ON_DEMAND, {}, fc, draws=50)  # type: ignore[arg-type]
    assert any("supply.overage_share.upfront" in w for w in r.warnings)
    assert r.shipments.unit == "count"  # see handoffs/A3_CONTRACT_CHANGES.md


def test_determinism_and_quantile_order(base: tuple[TrialDesign, object]) -> None:
    d, fc = base
    a = simulate_supply(d, ON_DEMAND, {}, fc, seed=3, draws=100)  # type: ignore[arg-type]
    b = simulate_supply(d, ON_DEMAND, {}, fc, seed=3, draws=100)  # type: ignore[arg-type]
    assert a.to_dict() == b.to_dict()
    json.dumps(a.to_dict())
    for m in (a.kits_needed, a.kits_produced, a.kits_wasted, a.waste_share, a.shipments):
        assert m.p10 <= m.p50 <= m.p90


def test_supply_runs_on_an_updated_forecast() -> None:
    d = design(n_sites=10, target=100)
    prior = forecast(d, Levers(), {}, draws=200)
    upd = update_with_actuals(prior, d, {s.id: [(6.0, 3)] for s in d.sites}, {})
    pd = per(simulate_supply(d, ON_DEMAND, {}, upd, draws=100))
    assert np.array_equal(pd.kits_produced, pd.kits_needed + pd.kits_wasted)


def test_a2_engine_reads_the_supply_result(ranged_params: dict[str, Parameter]) -> None:
    from trialpilot_engine import compute_scenario

    d = design(n_sites=10, target=100)
    fc = forecast(d, ON_DEMAND, ranged_params, draws=2000)
    sup = simulate_supply(d, ON_DEMAND, ranged_params, fc)
    result = compute_scenario(d, ON_DEMAND, ranged_params, seed=7, draws=2000, forecast=fc, supply=sup)
    assert result.drug_waste_share.p50 == pytest.approx(sup.waste_share.p50, rel=0.05)


# ---------------------------------------------------------------- performance


@pytest.mark.skipif(os.environ.get("TP_SKIP_PERF") == "1", reason="TP_SKIP_PERF=1")
def test_forecast_plus_supply_120_sites_2000_draws_under_one_second() -> None:
    d = design(n_sites=120, target=1200, duration=36.0)
    forecast(d, ON_DEMAND, {}, draws=200)  # warm-up
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        fc = forecast(d, ON_DEMAND, {}, draws=2000)
        r = simulate_supply(d, ON_DEMAND, {}, fc)
        timings.append(time.perf_counter() - start)
    assert r.draws_used >= 100
    assert min(timings) < 1.0, f"forecast + supply took {min(timings):.2f} s (draws used {r.draws_used})"

from __future__ import annotations

import inspect
import json
from dataclasses import asdict
from uuid import UUID

import numpy as np
import pytest
from trialpilot_engine.forecast import forecast, update_with_actuals

from trialpilot_api.ops.detect import Detector
from trialpilot_api.ops.evaluate import evaluate_state
from trialpilot_api.ops.fixtures import build_demo_design, load_demo_design
from trialpilot_api.ops.metrics import Feed
from trialpilot_api.ops.params import load_ops_params, ops_data_dir
from trialpilot_api.ops.simulator import event_uuid, simulate
from trialpilot_api.ops.store import TrialState

pytestmark = pytest.mark.req("URS-011")


def test_fixture_matches_generator():
    assert load_demo_design() == build_demo_design()
    assert len(load_demo_design().sites) == 40


def test_same_seed_same_feed_and_truth(ops_plan, simulated):
    again = simulate(ops_plan, load_ops_params(42), 42, "demo")
    assert [asdict(e) for e in simulated.events] == [asdict(e) for e in again.events]
    assert simulated.ground_truth == again.ground_truth


def test_different_seed_changes_feed(ops_plan, simulated):
    other = simulate(ops_plan, load_ops_params(43), 43, "demo")
    assert simulated.events != other.events


def test_sources_ids_and_labels(demo_state):
    events = [demo_state.to_ops_event(e) for e in demo_state.events]
    assert {e.source_system for e in events} == {"EDC", "CTMS", "IRT", "TRAVEL", "COURIER", "FINANCE", "VENDOR"}
    assert len({e.id for e in events}) == len(events)
    assert all(e.simulated and UUID(e.id).version == 4 for e in events)
    assert event_uuid("a", 42, "demo", "x") != event_uuid("b", 42, "demo", "x")


def test_ctms_site_activation_matches_ground_truth(simulated):
    activations = [e for e in simulated.events if e.key.endswith(":ctms:activation")]
    truth = simulated.ground_truth["activations"]
    assert truth and len(activations) == len(truth)
    by_site = {e.site_id: e for e in activations}
    assert set(by_site) == {row["site_id"] for row in truth}
    for row in truth:
        event = by_site[row["site_id"]]
        assert event.type == row["event_type"] == "site_activated"
        assert event.source == row["source_system"] == "CTMS"
        assert event.t == pytest.approx(row["activation_day"] + 0.1)
        assert event.payload == {
            "activation_date": row["activation_date"], "country": row["country"],
            "region": row["region"], "status": "open_to_enrollment",
        }
    assert not any(e.type == "vendor_milestone" and e.source == "CTMS" for e in simulated.events)
    assert any(e.type == "vendor_milestone" and e.source == "VENDOR" for e in simulated.events)
    published = json.loads((ops_data_dir() / "ground_truth.json").read_text(encoding="utf-8"))
    assert published["activations"] == truth
    assert {row["site_id"] for row in truth if row["backup"]} == {"S39", "S40"}
    # Contract v4: site_activated is a real EventType and the emitted payload validates.
    from trialpilot_api.ops._contracts import OpsEvent
    sample = activations[0]
    event = OpsEvent.model_validate({
        "id": "00000000-0000-4000-8000-000000000001", "trial_id": "demo-40", "site_id": sample.site_id,
        "type": sample.type, "occurred_at": "2026-01-01T00:00:00Z", "payload": sample.payload,
        "source_system": sample.source, "simulated": True,
    })
    assert event.type == "site_activated"
    assert OpsEvent.model_validate_json(event.model_dump_json()).payload == sample.payload


def test_a3_forecast_interface_still_matches_ops_adapter():
    """A3's current forecast / update_with_actuals signatures are what the ops adapter calls."""
    forecast_params = list(inspect.signature(forecast).parameters)
    update_params = list(inspect.signature(update_with_actuals).parameters)
    assert forecast_params[:5] == ["design", "levers", "params", "seed", "draws"]
    assert update_params == ["prior", "design", "actual_enrolment_by_site", "params", "seed"]


def test_all_planted_problems_detected_within_declared_windows(demo_state):
    report = evaluate_state(demo_state)
    assert len(report["detection"]) == 14
    assert all(row["detected_in_time"] for row in report["detection"]), report
    assert {a.kind for a in demo_state.alerts.values()} == {
        "enrollment_lag", "query_backlog", "drug_overstock", "drug_shortfall",
        "costly_shipping_mode", "monitoring_inefficiency", "vendor_delay", "milestone_at_risk"}


def test_healthy_fixture_has_no_alert_storm():
    st = TrialState("healthy", load_demo_design(), None, 42, 0, "healthy", 599, 600,
                    audit_sink=lambda **kwargs: None)
    assert len(st.alerts) <= 3, [(a.kind, a.site_id) for a in st.alerts.values()]
    assert not any(a.kind in {"query_backlog", "costly_shipping_mode", "monitoring_inefficiency",
                             "vendor_delay"} for a in st.alerts.values())


def test_rules_do_not_read_future_events(ops_plan, simulated):
    params = load_ops_params(42)
    past = [e for e in simulated.events if e.t < 210]
    full = Detector(ops_plan, Feed(ops_plan, simulated.events, params), 42).run(210)
    cut = Detector(ops_plan, Feed(ops_plan, past, params), 42).run(210)
    assert [asdict(f) for f in full] == [asdict(f) for f in cut]


def test_health_agrees_with_visible_feed_and_a3(demo_state):
    h = demo_state.health()
    assert h["simulated"] and h["data_label"] == "Simulated feed"
    assert len(h["kpis"]) == 14 and len(h["sites"]) == 40
    assert h["study"]["enrollment"]["value"] == sum(e.t < 599 and e.type == "patient_enrolled"
                                                      for e in demo_state.events)
    assert sum(s["enrolled"] for s in h["sites"]) == h["study"]["enrollment"]["value"]
    assert h["countries"][0]["planned_to_date"]["unit"] == "patients"
    prior = demo_state.plan.forecast_prior
    assert prior.draws is not None and prior.draws.n_draws == 2000
    assert prior.draws.t_full.shape == prior.draws.duration.shape == prior.draws.followup_months.shape
    assert h["study"]["milestones"]["db_lock"]["p50"]
    assert any("A3" in note for note in h["plan_notes"])
    assert all(s["drug_need_kits"]["p10"] <= s["drug_need_kits"]["p50"] <= s["drug_need_kits"]["p90"]
               for s in h["sites"])
    _assert_weekly_enrollment_matches_feed(demo_state, h)


def test_impact_ranges_have_provenance(demo_state):
    for aid, alert in demo_state.alerts.items():
        detail = demo_state.alert_detail(aid)
        for name, metric in alert.est_impact.items():
            assert metric.p10 <= metric.p50 <= metric.p90
            assert name in detail["provenance"], (alert.kind, name)


def test_missing_values_remain_unknown_at_clock_zero():
    st = TrialState("zero", load_demo_design(), None, 42, 0, "healthy", 0, 600,
                    audit_sink=lambda **kwargs: None)
    h = st.health()
    assert h["study"]["milestones"]["first_patient_in"] is None
    assert all(s["drug_need_kits"] is None for s in h["sites"])
    assert all(s["median_query_age_days"] is None for s in h["sites"])
    empty = {"unit": "patients", "actual_per_week": [], "actual_cumulative": [], "plan": []}
    assert all(s["weekly_enrollment"] == empty for s in h["sites"])
    assert all(c["weekly_enrollment"] == empty for c in h["countries"])


def test_feed_counts_only_complete_weeks(ops_plan, simulated):
    feed = Feed(ops_plan, simulated.events, load_ops_params(42))
    assert feed.weekly("enrolled", 14.9).shape == (40, 2)
    assert np.array_equal(feed.weekly("enrolled", 14), feed.weekly("enrolled", 14.9))


def _assert_weekly_enrollment_matches_feed(state, health) -> None:
    """Site and country sparklines are the feed's complete weeks plus the existing plan bands."""
    upto = state.clock_day
    weeks = int(upto // 7)
    weekly = state.feed.weekly("enrolled", upto)
    enrolled_t = state.feed.col("enrolled", "t")
    enrolled_s = state.feed.col("enrolled", "s").astype(int)
    for site in health["sites"]:
        series = site["weekly_enrollment"]
        idx = state.plan.site(site["site_id"]).idx
        _assert_series(series, [int(x) for x in weekly[idx, :weeks]], weeks)
        if weeks:
            assert series["plan"][-1] == {k: site["planned_to_date"][k] for k in ("p10", "p50", "p90")}
            band = state.plan.site_band[idx, 1: weeks + 1]
            assert [(p["p10"], p["p50"], p["p90"]) for p in series["plan"]] == [
                (float(row[0]), float(row[1]), float(row[2])) for row in band]
        complete, partial = _split_enrollment(enrolled_t, enrolled_s == idx, weeks, upto)
        assert sum(series["actual_per_week"]) == complete
        assert site["enrolled"] == complete + partial
    backups = [s for s in health["sites"] if s["backup"]]
    assert {s["site_id"] for s in backups} == {"S39", "S40"}
    for site in backups:
        assert all(p == {"p10": 0.0, "p50": 0.0, "p90": 0.0} for p in site["weekly_enrollment"]["plan"])
    for country in health["countries"]:
        members = [s for s in health["sites"] if s["country"] == country["country"]]
        summed = [sum(s["weekly_enrollment"]["actual_per_week"][w] for s in members) for w in range(weeks)]
        series = country["weekly_enrollment"]
        _assert_series(series, summed, weeks)
        idx = np.array([state.plan.site(s["site_id"]).idx for s in members])
        if weeks:
            assert series["plan"][-1] == {k: country["planned_to_date"][k] for k in ("p10", "p50", "p90")}
            band = state.plan.site_band[idx, 1: weeks + 1].sum(axis=0)
            assert [(p["p10"], p["p50"], p["p90"]) for p in series["plan"]] == [
                (float(row[0]), float(row[1]), float(row[2])) for row in band]
            for w, point in enumerate(series["plan"]):
                for key in ("p10", "p50", "p90"):
                    assert point[key] == pytest.approx(
                        sum(s["weekly_enrollment"]["plan"][w][key] for s in members))
        complete, partial = _split_enrollment(enrolled_t, np.isin(enrolled_s, idx), weeks, upto)
        assert sum(series["actual_per_week"]) == complete
        if weeks:
            assert series["actual_cumulative"][-1] == complete
        assert country["enrolled"] == complete + partial


def _assert_series(series, counts, weeks) -> None:
    assert series["unit"] == "patients"
    assert series["actual_per_week"] == counts
    assert series["actual_cumulative"] == list(np.cumsum(counts, dtype=int))
    assert len(series["plan"]) == weeks
    assert all(p["p10"] <= p["p50"] <= p["p90"] for p in series["plan"])


def _split_enrollment(enrolled_t, selected, weeks, upto) -> tuple[int, int]:
    cut = weeks * 7
    complete = int((selected & (enrolled_t < cut)).sum())
    partial = int((selected & (enrolled_t >= cut) & (enrolled_t < upto)).sum())
    return complete, partial

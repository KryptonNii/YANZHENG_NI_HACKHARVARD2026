from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

import numpy as np
import pytest

from trialpilot_api.ops.detect import Detector
from trialpilot_api.ops.evaluate import evaluate_state
from trialpilot_api.ops.fixtures import build_demo_design, load_demo_design
from trialpilot_api.ops.metrics import Feed
from trialpilot_api.ops.params import load_ops_params
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
    assert demo_state.plan.forecast_prior.draws.n_draws == 2000
    assert any("A3" in note for note in h["plan_notes"])
    assert all(s["drug_need_kits"]["p10"] <= s["drug_need_kits"]["p50"] <= s["drug_need_kits"]["p90"]
               for s in h["sites"])


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


def test_feed_counts_only_complete_weeks(ops_plan, simulated):
    feed = Feed(ops_plan, simulated.events, load_ops_params(42))
    assert feed.weekly("enrolled", 14.9).shape == (40, 2)
    assert np.array_equal(feed.weekly("enrolled", 14), feed.weekly("enrolled", 14.9))

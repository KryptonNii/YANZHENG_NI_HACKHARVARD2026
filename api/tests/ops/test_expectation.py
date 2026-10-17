"""Saved predictions for recommended actions, and their comparison with the observed effect (simulated feed)."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from trialpilot_api.ops import expectation
from trialpilot_api.ops._contracts import Alert, EffectEstimate, Intervention, MetricRange
from trialpilot_api.ops.effects import EffectDetails
from trialpilot_api.ops.fixtures import load_demo_design
from trialpilot_api.ops.params import load_ops_params
from trialpilot_api.ops.store import DEFAULT_START_DAY, TrialState

pytestmark = pytest.mark.req("URS-012")
AUTHOR = {"X-User": "alex.author", "X-Role": "author"}
MODULE = Path(expectation.__file__)


class Sink:
    """An audit sink that remembers what was recorded."""

    def __init__(self):
        self.actions: list[str] = []
        self.entries: list[dict] = []

    def __call__(self, **entry):
        self.actions.append(entry["action"])
        self.entries.append(entry)


def make_state(start_day: float = DEFAULT_START_DAY, sink: Sink | None = None) -> TrialState:
    return TrialState("demo-40", load_demo_design(), None, 42, 0, "demo", start_day, 600,
                      audit_sink=sink or (lambda **kwargs: None))


def open_alert(st: TrialState, kind: str, site: str, status: str = "open"):
    return next(a for a in st.alert_list(status) if a.kind == kind and a.site_id == site)


def action_text(alert, fragment: str) -> str:
    return next(t for t in alert.recommended_actions if fragment in t.lower())


@pytest.fixture(scope="module")
def state() -> TrialState:
    return make_state()


# ---------------------------------------------------------------------------------- prediction
@pytest.mark.parametrize(("kind", "site"), [("enrollment_lag", "S06"), ("enrollment_lag", "S14"),
                                            ("drug_overstock", "S14")])
def test_do_nothing_baseline_equals_the_alerts_own_impact(state, kind, site):
    alert = open_alert(state, kind, site)
    payload = state._option_set(alert).payload
    assert payload["baseline"]["cost_usd"]["p50"] == pytest.approx(alert.est_impact["cost_usd"].p50, abs=1.0)
    if kind == "enrollment_lag":
        months = alert.est_impact["delay_days"].p50  # the alert stores this in months
        assert payload["baseline"]["delay_days"]["p50"] == pytest.approx(months * 365.25 / 12, abs=0.2)  # the alert rounds months to 2 places


def test_options_are_ranked_by_net_value_and_every_assumption_is_labelled(state):
    payload = state._option_set(open_alert(state, "drug_overstock", "S14")).payload
    ranked = [i for i in payload["items"] if i["quantified"]]
    assert [i["rank"] for i in ranked] == [1, 2]
    assert ranked[0]["net_usd"]["p50"] >= ranked[1]["net_usd"]["p50"]
    for item in ranked:
        assert item["net_usd"]["p50"] == pytest.approx(
            item["cost_avoided_usd"]["p50"] - item["action_cost_usd"]["p50"], rel=0.5)
        assert item["model_label"].startswith("Planning model with assumed parameters")
        assert item["assumptions"] and all("ASSUMPTION" in a or "Gamma" in a or "constant" in a
                                           for a in item["assumptions"])
        assert item["delay_saved_days"] is None  # drug supply has no time effect in this model
        assert item["effect"]["p50"] < 0 and item["better"] == "down"


def test_actions_without_a_model_are_listed_but_not_ranked(state):
    payload = state._option_set(open_alert(state, "enrollment_lag", "S06")).payload
    by_code = {i["code"]: i for i in payload["items"]}
    assert by_code["enrollment_retraining"]["rank"] == 1
    assert by_code["feasibility_call"]["quantified"] is False
    assert "not ranked" in by_code["feasibility_call"]["reason"]
    assert "rank" not in by_code["feasibility_call"]
    assert by_code["activate_backup"]["quantified"] is False  # both backup sites are already in use at day 406
    assert "no unactivated backup" in by_code["activate_backup"]["reason"].lower()


def test_prediction_is_reproducible_and_warns_when_the_check_cannot_resolve_it(state):
    alert = open_alert(state, "enrollment_lag", "S06")
    one, two = state._option_set(alert).payload, state._option_set(alert).payload
    assert one == two
    retrain = next(i for i in one["items"] if i["code"] == "enrollment_retraining")
    assert any("smallest change" in w for w in retrain["warnings"])


def test_backup_site_is_offered_with_its_own_metric_when_one_is_free():
    st = make_state(180)
    alert = open_alert(st, "enrollment_lag", "S14")
    options = st._option_set(alert).payload["items"]
    backup = next(i for i in options if i["code"] == "activate_backup")
    assert backup["quantified"] and backup["metric"] == "regional_enrollment_rate_per_month"
    assert backup["target_site_ids"][0] in {"S39", "S40"}
    assert backup["label"].startswith("Activate backup site")
    assert "nearest available" in " ".join(backup["reasoning"])
    iv = st.create_intervention({"alert_id": alert.id, "action": backup["action"]}, "tester", "author")
    assert iv.target_site_ids == backup["target_site_ids"] and iv.metric == backup["metric"]
    assert st.expectation_of(iv.id)["code"] == "activate_backup"


# ---------------------------------------------------------------------------------- saved at planning time
def test_prediction_is_saved_once_when_the_action_is_planned():
    sink = Sink()
    st = make_state(sink=sink)
    alert = open_alert(st, "drug_overstock", "S14")
    text = action_text(alert, "on-demand")
    iv = st.create_intervention({"alert_id": alert.id, "action": text}, "tester", "author")
    saved = st.expectation_of(iv.id)
    assert saved["frozen"] is True and saved["alert_id"] == alert.id and saved["computed_at"] == "2026-10-12"
    assert saved["rank_when_planned"] == 1
    assert "ops.intervention.expectation" in sink.actions
    st.advance(28, "tester", "author")
    assert st.expectation_of(iv.id) == saved
    assert st._option_set(open_alert(st, "enrollment_lag", "S06")).payload["computed_at_day"] > saved["computed_at_day"]


def test_unmodelled_and_scripted_actions_get_no_prediction(state):
    st = make_state()
    alert = open_alert(st, "enrollment_lag", "S06")
    iv = st.create_intervention({"alert_id": alert.id, "action": action_text(alert, "feasibility")},
                                "tester", "author")
    assert st.expectation_of(iv.id) is None and st.reconciliation(iv.id) is None
    scripted = next(i for i in st.interventions.values() if st.iv_meta[i.id].system)
    assert st.expectation_of(scripted.id) is None


def test_changing_a_planned_action_replaces_its_prediction():
    st = make_state()
    alert = open_alert(st, "drug_overstock", "S14")
    iv = st.create_intervention({"alert_id": alert.id, "action": action_text(alert, "on-demand")}, "t", "author")
    first = st.expectation_of(iv.id)
    st.update_intervention(iv.id, {"action": action_text(alert, "transfer")}, "t", "author")
    second = st.expectation_of(iv.id)
    assert second["code"] == "transfer_excess" and second["net_usd"] != first["net_usd"]


# ---------------------------------------------------------------------------------- comparison
def details(weeks: tuple[int, int], p50: float | None, ci: tuple[float, float] | None, metric: str) -> EffectDetails:
    rng = MetricRange(p10=None, p50=None, p90=None, unit="patients") if p50 is None else MetricRange(
        p10=p50 - 1, p50=p50, p90=p50 + 1, unit="patients")
    est = EffectEstimate(intervention_id="x", method="diff_in_diff", effect=rng, treated_change=0.0,
                         control_change=0.0, verdict="inconclusive", explanation="Too early: 1 complete week(s).")
    return EffectDetails(est, metric, "patients", "site", "up", post_weeks=weeks, ci95=ci)


def reconcile_case(ops_plan, ci, *, weeks=(11, 17), metric="enrollment_rate_per_month", effect=(0.8, 1.2),
                   p50=0.0):
    start = ops_plan.date(7 * 10)  # post-start weeks begin at week 11, so a zero lag means a full effect
    iv = Intervention(id="x", trial_id="t", alert_id=None, action="a", owner="o", due_date=start,
                      target_site_ids=["S06"], metric=metric, started_at=start, status="in_progress")
    exp = {"metric": metric, "alert_id": "alert-1"}
    draws = {"effect": np.linspace(*effect, 2000), "lag": np.zeros(2000)}
    return expectation.reconcile(ops_plan, iv, exp, draws, details(weeks, p50, ci, metric))


@pytest.mark.parametrize(("ci", "verdict"), [
    ((1.5, 3.0), "exceeded"),
    ((0.5, 1.5), "met"),
    ((0.1, 0.5), "partial"),
    ((-0.6, 0.4), "not_met"),
    ((-0.5, 2.0), "inconclusive"),
])
def test_follow_up_compares_the_observed_interval_with_the_predicted_range(ops_plan, ci, verdict):
    rec = reconcile_case(ops_plan, ci, p50=sum(ci) / 2)
    assert rec["verdict"] == verdict
    assert rec["predicted"]["p10"] == pytest.approx(0.84, abs=0.01)
    assert rec["predicted"]["p90"] == pytest.approx(1.16, abs=0.01)
    assert rec["observed"]["ci95"] == list(ci) and rec["post_weeks"] == 6
    assert rec["needs_replan"] is (verdict in {"partial", "not_met"})


def test_a_shortfall_asks_for_a_replan_only_after_enough_weeks(ops_plan):
    assert reconcile_case(ops_plan, (0.1, 0.5), weeks=(11, 16), p50=0.3)["needs_replan"] is False
    assert reconcile_case(ops_plan, (0.1, 0.5), weeks=(11, 17), p50=0.3)["needs_replan"] is True


def test_start_up_lag_dilutes_the_prediction_over_the_observed_window(ops_plan):
    start = ops_plan.date(7 * 10)
    iv = Intervention(id="x", trial_id="t", alert_id=None, action="a", owner="o", due_date=start,
                      target_site_ids=["S06"], metric="enrollment_rate_per_month", started_at=start,
                      status="in_progress")
    draws = {"effect": np.full(2000, 1.0), "lag": np.full(2000, 21.0)}
    rec = expectation.reconcile(ops_plan, iv, {"metric": "enrollment_rate_per_month", "alert_id": "a"}, draws,
                                details((11, 15), 0.2, (0.0 + 0.01, 0.4), "enrollment_rate_per_month"))
    assert 0 < rec["share_of_effect_in_window"] < 1
    assert rec["predicted"]["p50"] == pytest.approx(rec["share_of_effect_in_window"], abs=0.001)


def test_metrics_that_should_fall_are_compared_in_their_own_direction(ops_plan):
    kwargs = {"metric": "kits_on_hand", "effect": (-50.0, -30.0)}
    assert reconcile_case(ops_plan, (-90.0, -60.0), p50=-75.0, **kwargs)["verdict"] == "exceeded"
    assert reconcile_case(ops_plan, (-45.0, -35.0), p50=-40.0, **kwargs)["verdict"] == "met"
    assert reconcile_case(ops_plan, (-10.0, -4.0), p50=-7.0, **kwargs)["verdict"] == "partial"
    assert reconcile_case(ops_plan, (-2.0, 3.0), p50=0.5, **kwargs)["verdict"] == "not_met"


def test_too_early_is_insufficient_data_not_a_verdict(ops_plan):
    rec = reconcile_case(ops_plan, None, weeks=(11, 12), p50=None)
    assert rec["verdict"] == "insufficient_data" and rec["predicted"] is None and rec["needs_replan"] is False
    assert "Too early" in rec["explanation"]


def test_follow_up_runs_on_the_real_feed_and_names_its_basis():
    st = make_state()
    alert = open_alert(st, "drug_overstock", "S14")
    iv = st.create_intervention({"alert_id": alert.id, "action": action_text(alert, "on-demand"),
                                 "status": "in_progress"}, "tester", "author")
    assert st.reconciliation(iv.id)["verdict"] == "insufficient_data"
    st.advance(63, "tester", "author")
    rec = st.reconciliation(iv.id)
    assert rec["verdict"] in expectation.VERDICTS and rec["verdict"] != "insufficient_data"
    assert rec["predicted"]["unit"] == "kits" and rec["observed"]["ci95"][0] < 0
    assert "not observed separately" in rec["basis"] and rec["metric"] == "kits_on_hand"


# ---------------------------------------------------------------------------------- re-plan reminder
def test_action_below_its_prediction_reopens_the_alert_once():
    sink = Sink()
    st = make_state(sink=sink)
    alert = open_alert(st, "enrollment_lag", "S14")
    iv = st.create_intervention({"alert_id": alert.id, "action": action_text(alert, "retrain"),
                                 "status": "in_progress"}, "tester", "author")
    assert st.alerts[alert.id].status == "action_planned"
    st.iv_meta[iv.id].exp_draws["effect"] = st.iv_meta[iv.id].exp_draws["effect"] * 0 + 40.0  # an absurd forecast
    st.advance(63, "tester", "author")
    rec = st.reconciliation(iv.id)
    assert rec["verdict"] in {"partial", "not_met"} and rec["needs_replan"] is True
    assert st.alerts[alert.id].status == "open"
    assert "below its predicted effect" in st.alert_meta[alert.id]["history"][-1]["reason"]
    assert sink.actions.count("ops.intervention.replan") == 1
    st.advance(14, "tester", "author")
    assert sink.actions.count("ops.intervention.replan") == 1  # asked once, not every week


def test_action_that_meets_its_prediction_does_not_reopen_the_alert():
    sink = Sink()
    st = make_state(sink=sink)
    alert = open_alert(st, "drug_overstock", "S14")
    st.create_intervention({"alert_id": alert.id, "action": action_text(alert, "on-demand"),
                            "status": "in_progress"}, "tester", "author")
    st.advance(63, "tester", "author")
    assert "ops.intervention.replan" not in sink.actions


# ---------------------------------------------------------------------------------- honesty guards
def test_prediction_never_reads_the_simulator_or_its_ground_truth():
    source = MODULE.read_text(encoding="utf-8")
    for token in ("ground_truth", "sim_effect", "BACKUP_RATE", "BACKUP_START_LAG", "SimIntervention"):
        assert token not in source, token
    imported = {n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"simulator", "fixtures", "evaluate", "store"}
    names = {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}
    assert not {n for n in names if "sim" in n.lower() and n != "simulated"}


def test_every_parameter_the_prediction_adds_is_a_labelled_assumption():
    params = load_ops_params(42, use_library=False).params
    added = [p for pid, p in params.items() if pid.startswith(("ops.effect.", "ops.cost.action."))]
    assert len(added) == 10
    for p in added:
        assert p.assumption and (p.rationale or "").strip() and p.value_low <= p.value_mid <= p.value_high
        assert p.source_url is None  # no invented source


def test_audit_entry_for_the_prediction_carries_the_numbers():
    sink = Sink()
    st = make_state(sink=sink)
    alert = open_alert(st, "drug_overstock", "S14")
    st.create_intervention({"alert_id": alert.id, "action": action_text(alert, "transfer")}, "tester", "author")
    entry = next(e for e in sink.entries if e["action"] == "ops.intervention.expectation")
    assert entry["after"]["net_usd"]["p50"] > 0 and entry["after"]["frozen"] is True
    assert "assumed parameters" in entry["reason"]


# ---------------------------------------------------------------------------------- HTTP
def test_http_alert_detail_lists_options_and_effects_carry_the_comparison(client):
    base = "/api/ops/demo-40"
    client.post(base + "/simulate", json={"seed": 42, "speed": 0}, headers=AUTHOR).raise_for_status()
    alerts = client.get(base + "/alerts").json()["items"]
    alert = next(a for a in alerts if a["kind"] == "drug_overstock" and a["status"] == "open")
    detail = client.get(base + "/alerts/" + alert["id"]).json()
    first = detail["options"]["items"][0]
    assert first["rank"] == 1 and detail["options"]["ranked_by"].startswith("net_usd")
    r = client.post(base + "/interventions", headers=AUTHOR,
                    json={"alert_id": alert["id"], "action": first["action"], "owner": "alex.author"})
    assert r.status_code == 201, r.text
    iv = r.json()
    effect = client.get(base + "/effects/" + iv["id"]).json()
    assert effect["expectation"]["code"] == first["code"] and effect["expectation"]["frozen"] is True
    assert effect["reconciliation"]["verdict"] == "insufficient_data"
    assert client.get(base + "/effects").json()["items"]  # the list endpoint keeps its contract shape
    assert datetime.fromisoformat(effect["expectation"]["computed_at"] + "T00:00:00+00:00").tzinfo == UTC


def test_alert_without_a_model_has_no_options_payload_for_closed_alerts():
    st = make_state()
    resolved = next(a for a in st.alert_list("resolved"))
    assert st.alert_detail(resolved.id)["options"] is None
    assert isinstance(resolved, Alert)

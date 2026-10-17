"""Export I1/I4 observations for the command-center replay, without reading the answer key.

From the repository root:
    uv run --project api python data/fixtures/ops/export_lock_evidence.py
    uv run --project api python data/fixtures/ops/export_lock_evidence.py --check

Only the evidence file is generated here. Lock dates in lock_recovery_story.json are
authored scenario assumptions, not outputs of the operational milestone forecaster.
"""

import argparse
import json
from pathlib import Path

from trialpilot_api.ops._contracts import Intervention
from trialpilot_api.ops.actions import ACTIONS
from trialpilot_api.ops.effects import estimate_effect
from trialpilot_api.ops.fixtures import load_demo_design
from trialpilot_api.ops.metrics import Feed
from trialpilot_api.ops.params import load_ops_params
from trialpilot_api.ops.plan import build_plan
from trialpilot_api.ops.simulator import event_uuid, simulate


def export():
    seed, day = 42, 406
    params = load_ops_params(seed)
    plan = build_plan(load_demo_design(), params, None, 600)
    sim = simulate(plan, params, seed, "demo", [])
    feed = Feed(plan, sim.events, params)
    metrics = {
        "I1": "query_rate_percent",
        "I2": "regional_enrollment_rate_per_month",
        "I3": "query_rate_percent",
        "I4": "missed_visit_rate_percent",
    }
    # Use the scenario's interventions, never its ground-truth verdicts.
    interventions = {
        iv.id: Intervention(
            id=event_uuid("demo-40", seed, "demo", f"iv:{iv.id}"),
            trial_id="demo-40", alert_id=None, action=ACTIONS[iv.code].text,
            owner="Simulated study team (scripted intervention)",
            due_date=plan.date(iv.start_day + 28), target_site_ids=iv.site_ids,
            metric=metrics[iv.id], started_at=plan.date(iv.start_day), status="done",
        )
        for iv in sim.scenario.planted
    }
    cases = []
    for key in ("I1", "I4"):
        iv = interventions[key]
        kwargs = {"others": list(interventions.values()), "seed": seed}
        early = estimate_effect(plan, feed, iv, plan.day_of(iv.started_at) + 14, **kwargs)
        follow_up = estimate_effect(plan, feed, iv, day, **kwargs)
        cases.append({
            "truth_id": key, "intervention": iv.model_dump(mode="json"),
            "early": early.to_dict(plan), "follow_up": follow_up.to_dict(plan),
        })
    return {
        "simulated": True, "data_label": "Simulated feed", "trial_id": "demo-40",
        "site_count": len(plan.sites), "seed": seed, "evaluation_day": day,
        "source": "trialpilot_api.ops.effects.estimate_effect; original scripted start dates",
        "cases": cases,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = Path(__file__).with_name("lock_recovery_evidence.json")
    result = json.loads(json.dumps(export()))
    if args.check:
        assert json.loads(output.read_text(encoding="utf-8")) == result, "Evidence is stale; regenerate it"
        print("Lock replay evidence matches the existing effect estimator.")
    else:
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(output)

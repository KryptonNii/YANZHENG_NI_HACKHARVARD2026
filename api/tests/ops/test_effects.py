from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from trialpilot_api.ops._contracts import Intervention
from trialpilot_api.ops.effects import estimate_effect
from trialpilot_api.ops.evaluate import evaluate_state
from trialpilot_api.ops.metrics import WEEKS_PER_MONTH

pytestmark = pytest.mark.req("URS-013")


def intervention(plan, **kwargs):
    return Intervention(id="synthetic-iv", trial_id="synthetic", alert_id=None,
                         action="Synthetic known-effect experiment", owner="tester",
                         target_site_ids=[s.id for s in plan.sites[:6]],
                         due_date=plan.date(180), started_at=plan.date(140),
                         metric="enrollment_rate_per_month", status="done", **kwargs)


class SyntheticFeed:
    def __init__(self, plan, treatment_delta, shared_delta):
        self.plan = plan
        self.num = np.ones((len(plan.sites), 40)) * 10
        self.den = np.ones_like(self.num)
        self.num[:, 21:] += shared_delta
        self.num[:6, 21:] += treatment_delta

    def series(self, metric, upto):
        weeks = int(upto // 7)
        return self.num[:, :weeks], self.den[:, :weeks], [s.id for s in self.plan.sites]


@pytest.mark.parametrize("treatment,shared,expected", [
    (4, 2, "likely_worked"), (0, 3, "likely_coincidence"),
    (0, 0, "no_effect"), (-4, 0, "no_effect"),
])
def test_known_effect_and_shared_trend(ops_plan, treatment, shared, expected):
    iv = intervention(ops_plan)
    result = estimate_effect(ops_plan, SyntheticFeed(ops_plan, treatment, shared), iv, 280)
    assert result.estimate.verdict == expected
    assert result.estimate.effect.p50 == pytest.approx(treatment * WEEKS_PER_MONTH, abs=.001)


def test_insufficient_data_is_unknown_not_zero(ops_plan):
    result = estimate_effect(ops_plan, SyntheticFeed(ops_plan, 4, 0), intervention(ops_plan), 145)
    assert result.estimate.verdict == "inconclusive"
    assert result.estimate.effect.p50 is None
    assert "Too early" in result.estimate.explanation


def test_control_group_not_contaminated(ops_plan):
    iv = intervention(ops_plan)
    other = iv.model_copy(update={"id": "other", "target_site_ids": ["S07", "S08", "S09"]})
    result = estimate_effect(ops_plan, SyntheticFeed(ops_plan, 4, 0), iv, 280, others=[iv, other])
    assert not set(result.control_units) & set(iv.target_site_ids + other.target_site_ids)


def test_no_controls_is_inconclusive(ops_plan):
    iv = intervention(ops_plan).model_copy(update={"target_site_ids": [s.id for s in ops_plan.sites]})
    result = estimate_effect(ops_plan, SyntheticFeed(ops_plan, 4, 0), iv, 280)
    assert result.estimate.effect.p50 is None
    assert result.estimate.verdict == "inconclusive"


def test_unsupported_metric(ops_plan):
    iv = intervention(ops_plan).model_copy(update={"metric": "milestone_slip_days"})
    result = estimate_effect(ops_plan, SimpleNamespace(), iv, 280)
    assert result.estimate.verdict == "inconclusive"
    assert result.estimate.effect.p50 is None


def test_default_demo_verdicts_match_withheld_truth(demo_state):
    assert all(r["correct"] for r in evaluate_state(demo_state)["effects"])

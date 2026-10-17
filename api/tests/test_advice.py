"""Constrained advice, current-selection patches, evidence gates and real-engine deltas."""

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from a5_support import AUTHOR, FakeEngine, make_design

from trialpilot_api._contracts import (
    ForecastView,
    Levers,
    MetricRange,
    Parameter,
    SupplyView,
    TrialDesign,
)
from trialpilot_api.advice.candidates import build_candidates, slower_enrollment
from trialpilot_api.advice.ranking import RANKED_BELOW, advice_policy
from trialpilot_api.advice.schemas import ProcedureRef
from trialpilot_api.engine_adapter import EngineFns, load_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
METRICS = ("cost_usd", "site_staff_hours", "duration_months")
TOP_THREE = ["on_demand_supply", "remove_procedure:ecg", "local_labs"]


def advice_design():
    design = make_design()
    design["missing_fields"] = []
    for site, enrollment in zip(design["sites"], [30, 5, 20], strict=True):
        site["expected_enrollment"] = enrollment
    design["visits"][0]["procedures"][0]["endpoint_role"] = "supports_primary"
    design["visits"][1]["procedures"] = [
        {"code": "ecg", "label": "ECG", "endpoint_role": "not_linked"},
        {"code": "mri", "label": "MRI", "endpoint_role": "supports_secondary"},
        {"code": "unknown_test", "label": "Unreviewed test"},
    ]
    return design


def save_design(client, design=None, **headers):
    response = client.post("/api/designs", json=design or advice_design(),
                           headers={**AUTHOR, **headers})
    assert response.status_code == 201, response.text
    return response


def advice(client, version=1, current=None):
    params = {"design_id": "design-test-1", "design_version": version}
    if current is not None:
        params["current_levers"] = json.dumps(current)
    response = client.get("/api/scenarios/advice", params=params)
    assert response.status_code == 200, response.text
    assert response.headers["x-design-version"] == str(version)
    assert response.headers["x-parameter-set-version"] == response.json()["parameter_set_version"]
    return response.json()


def metric(value, unit):
    return MetricRange(p10=None if value is None else value - 2, p50=value,
                       p90=None if value is None else value + 3, unit=unit)


def ids(items):
    return [item["id"] for item in items]


def removed_codes(data):
    return {code for key in ("recommendations", "rejected")
            for item in data[key] for code in item["levers"].get("removed_procedures", [])}


class RankingEngine(FakeEngine):
    """Explicit test numbers exercise ranking independently of production model formulas."""

    VALUES = {
        "drug_supply_strategy": (-2000, 0, 0),
        "excluded_site_ids": (-1000, -50, 3),
        "added_country_count": (200, 10, -2),
        "remote_monitoring_share": (-100, -5, 0),
        "local_lab_share": (-100, -8, 0),
        "home_visit_numbers": (-100, -5, 0),
        "removed_procedures": (-300, -20, 0),
        # Cheaper and within every gate: only the stress path keeps it out of recommendations.
        "enrollment_rate_multiplier": (-800, -30, 0),
    }

    def __init__(self):
        super().__init__()
        self.comparisons = []
        self.compute_settings = []
        self.cost_overrides = {}
        self.duration_overrides = {}
        self.staff_overrides = {}
        self.all_cost = None
        self.risk = 0.01
        self.no_forecast = lambda levers: False

    def compute_scenario(self, design, levers, params, seed=7, draws=2000):
        self.compute_settings.append((seed, draws, params, levers))
        result = super().compute_scenario(design, levers, params, seed, draws)
        if not self.no_forecast(levers):
            result.forecast = ForecastView(
                months_to_full_enrollment=metric(12, "months"),
                milestone_dates={"database_lock": metric(24, "months")},
            )
        if self.risk is not None:
            result.supply = SupplyView(
                kits_needed=metric(100, "kits"), kits_produced=metric(120, "kits"),
                kits_wasted=metric(20, "kits"), waste_share=metric(15, "percent"),
                shipments=metric(10, "count"), stockout_probability=self.risk,
            )
        return result

    def compare_levers(self, design, levers_a, levers_b, params, seed=7, draws=2000):
        self.comparisons.append((design.model_copy(deep=True), levers_a, levers_b, seed, draws, params))
        a = self.compute_scenario(design, levers_a, params, seed, draws)
        b = self.compute_scenario(design, levers_b, params, seed, draws)
        changed = [key for key, value in levers_b.model_dump().items()
                   if value != getattr(levers_a, key)]
        assert len(changed) == 1, changed
        key = changed[0]
        cost, staff, duration = self.VALUES[key]
        cost = self.cost_overrides.get(key, cost)
        if self.all_cost is not None:
            cost = self.all_cost
        staff = self.staff_overrides.get(key, staff)
        duration = self.duration_overrides.get(key, duration)
        delta = dict(zip(METRICS, [metric(cost, "usd"), metric(staff, "hours"),
                                  metric(duration, "months")], strict=True))
        return a, b, delta

    def assert_advice_sampling(self, current=None):
        """Every advice compute and comparison: seed 7, 200 draws, current selection as side A."""
        current = Levers(**(current or {}))
        assert self.comparisons
        assert all(call[1] == current and call[3:5] == (7, 200) for call in self.comparisons)
        assert all(setting[:2] == (7, 200) for setting in self.compute_settings)


@pytest.fixture
def ranking_client(make_client):
    engine = RankingEngine()
    client = make_client(engine_fns=engine.fns(), mount_optional_routers=False)
    save_design(client)
    return client, engine


def test_single_stage_ranking_is_relative_to_current_and_rejects_delay_and_cost(ranking_client):
    client, engine = ranking_client
    data = advice(client)
    assert ids(data["recommendations"]) == TOP_THREE
    assert data["recommendations"][0]["delta"]["cost_usd"] == {
        "p10": -2002, "p50": -2000, "p90": -1997, "unit": "usd",
    }
    assert [item["kind"] for item in data["recommendations"]] == [
        "lever", "procedure_removal", "lever",
    ]
    rejected = {item["id"]: item for item in data["rejected"]}
    assert "duration P50 increases" in rejected["exclude_site:s2"]["reason"]
    assert "does not improve" in rejected["added_countries"]["reason"]
    # Ties on cost break by staff hours, then id; nothing feasible is dropped silently.
    assert [item["id"] for item in data["rejected"] if item["reason"] == RANKED_BELOW] == [
        "home_visits", "remote_monitoring",
    ]
    assert rejected["home_visits"]["delta"]["cost_usd"]["p50"] == -100
    assert len(data["recommendations"]) + len(data["rejected"]) == 7
    assert all(item["stockout_probability"] == 0.01 for item in data["recommendations"])
    assert len(engine.comparisons) == 8  # seven candidates and one stress scenario
    engine.assert_advice_sampling()
    assert (data["seed"], data["draws"], data["scenario_draws"]) == (7, 200, 2000)
    assert "screening_draws" not in data
    note = data["sampling_note"]
    assert "seed 7" in note and "200 draws" in note
    assert "own draw count (2,000 draws)" in note and "can differ" in note
    method = data["delta_method"]
    assert "current selection" in method and "common random numbers" in method
    policy = data["policy"]
    assert (policy["max_duration_increase_months"], policy["max_stockout_probability"],
            policy["max_recommendations"]) == (0, 0.05, 3)
    for phrase in ("not a clinical guarantee", "not clinical approval", "not registry sites",
                   "stress scenario", "never recommended for removal"):
        assert phrase in policy["note"]


def test_top_three_cap_moves_remaining_feasible_candidates_to_rejected(ranking_client):
    client, engine = ranking_client
    engine.all_cost = -100
    data = advice(client)
    assert ids(data["recommendations"]) == ["remove_procedure:ecg", "local_labs", "home_visits"]
    below = [item for item in data["rejected"] if item["reason"] == RANKED_BELOW]
    assert ids(below) == ["remote_monitoring", "on_demand_supply", "added_countries"]
    assert all(item["delta"]["cost_usd"]["p50"] == -100 for item in below)
    assert ids(data["rejected"]) == ["exclude_site:s2", *ids(below)]
    assert RANKED_BELOW == ("Met the model constraints but ranked below the top 3 by cost P50 "
                            "change relative to the current selection.")


def test_only_not_linked_procedures_become_single_removal_candidates(ranking_client):
    client, engine = ranking_client
    data = advice(client)
    [removal] = [item for item in data["recommendations"] + data["rejected"]
                 if item["kind"] == "procedure_removal"]
    assert removal["id"] == "remove_procedure:ecg"
    assert removal["label"] == "Remove ECG"
    assert removal["levers"] == {"removed_procedures": ["ecg"]}
    assert removal["procedure"] == {"code": "ecg", "label": "ECG", "endpoint_roles": ["not_linked"]}
    assert "not clinical approval" in removal["reason"]
    assert "manual protocol review" in removal["reason"]
    assert "safety, eligibility or treatment" in removal["reason"]
    assert all(item["procedure"] is None and "removed_procedures" not in item["levers"]
               for item in data["recommendations"] + data["rejected"] if item["kind"] == "lever")
    blocked = {item["code"]: item for item in data["blocked"]}
    assert set(blocked) == {"blood_draw", "mri", "unknown_test"}
    assert blocked["blood_draw"]["endpoint_roles"] == ["supports_primary"]
    assert "primary endpoint" in blocked["blood_draw"]["reason"]
    assert "secondary endpoint" in blocked["mri"]["reason"]
    assert blocked["unknown_test"]["endpoint_roles"] == ["unknown"]
    assert "unknown" in blocked["unknown_test"]["reason"]
    assert all("manual protocol review" in item["reason"] for item in blocked.values())
    assert removed_codes(data) == {"ecg"}
    assert [call[2].removed_procedures for call in engine.comparisons
            if call[2].removed_procedures] == [["ecg"]]


def test_each_not_linked_code_is_its_own_removal_candidate():
    raw = advice_design()
    raw["visits"][2]["procedures"] = [
        {"code": "vitals", "label": "Vital signs", "endpoint_role": "not_linked"},
        {"code": "ecg", "label": "Repeat ECG", "endpoint_role": "not_linked"},
    ]
    design = TrialDesign.model_validate(raw)

    def removals(current):
        candidates, _, _ = build_candidates(design, current)
        return {c.id: c for c in candidates if c.kind == "procedure_removal"}

    fresh = removals(Levers())
    assert list(fresh) == ["remove_procedure:ecg", "remove_procedure:vitals"]
    assert fresh["remove_procedure:ecg"].label == "Remove ECG"
    assert fresh["remove_procedure:ecg"].procedure == ProcedureRef(code="ecg", label="ECG")
    assert fresh["remove_procedure:vitals"].patch == {"removed_procedures": ["vitals"]}
    assert all("not clinical approval" in c.reason for c in fresh.values())
    kept = removals(Levers(removed_procedures=["vitals"]))
    assert list(kept) == ["remove_procedure:ecg"]
    assert kept["remove_procedure:ecg"].patch == {"removed_procedures": ["vitals", "ecg"]}
    assert kept["remove_procedure:ecg"].levers.removed_procedures == ["vitals", "ecg"]
    assert removals(Levers(removed_procedures=["ecg", "vitals"])) == {}


@pytest.mark.parametrize("role", ["supports_primary", "supports_secondary", "unknown"])
def test_mixed_roles_are_blocked_and_never_removal_candidates(make_client, role):
    raw = advice_design()
    raw["visits"][0]["procedures"].append({"code": "ecg", "label": "ECG", "endpoint_role": role})
    candidates, blocked, _ = build_candidates(TrialDesign.model_validate(raw))
    assert not any(candidate.levers.removed_procedures for candidate in candidates)
    ecg = next(item for item in blocked if item.code == "ecg")
    assert ecg.endpoint_roles == sorted(["not_linked", role])
    assert "do not override" in ecg.reason and "manual protocol review" in ecg.reason
    engine = RankingEngine()
    client = make_client(engine_fns=engine.fns(), mount_optional_routers=False)
    save_design(client, raw)
    data = advice(client)
    assert removed_codes(data) == set()
    assert {item["code"] for item in data["blocked"]} == {
        "blood_draw", "ecg", "mri", "unknown_test",
    }
    assert all(not call[2].removed_procedures for call in engine.comparisons)


def test_current_removal_of_blocked_codes_is_kept_only_as_baseline(ranking_client):
    client, engine = ranking_client
    current = {"removed_procedures": ["mri", "ecg"]}
    data = advice(client, current=current)
    warning = next(text for text in data["warnings"] if "already removes" in text)
    assert "mri" in warning and "ecg" not in warning
    assert "comparison baseline" in warning and "not approval" in warning
    assert any("Existing procedure removals" in text for text in data["warnings"])
    assert not any(item["kind"] == "procedure_removal"
                   for item in data["recommendations"] + data["rejected"])
    assert all(call[2].removed_procedures == ["mri", "ecg"] for call in engine.comparisons)
    engine.assert_advice_sampling(current)


def test_current_selection_is_baseline_and_preserved_with_minimal_patches(ranking_client):
    client, engine = ranking_client
    current = {"remote_monitoring_share": 0.8, "local_lab_share": 0.7,
               "removed_procedures": ["ecg"], "excluded_site_ids": ["s2"],
               "home_visit_numbers": [1], "enrollment_rate_multiplier": 1.2}
    data = advice(client, current=current)
    assert data["current_levers"] == Levers(**current).model_dump()
    assert data["baseline"]["cost_usd"]["p50"] == pytest.approx((2000 + 20000) * 0.92)
    engine.assert_advice_sampling(current)
    for call in engine.comparisons:
        assert call[2].remote_monitoring_share == 0.8
        assert call[2].local_lab_share == 0.7
        assert call[2].removed_procedures == ["ecg"]
        assert "s2" in call[2].excluded_site_ids
    assert sorted(call[2].enrollment_rate_multiplier for call in engine.comparisons) == [
        0.84, *[1.2] * (len(engine.comparisons) - 1),
    ]
    home = next(item for item in data["recommendations"] if item["id"] == "home_visits")
    assert home["levers"] == {"home_visit_numbers": [1, 3]}
    exclusion = next(item for item in data["rejected"] if item["id"] == "exclude_site:s3")
    assert exclusion["levers"] == {"excluded_site_ids": ["s2", "s3"]}
    assert removed_codes(data) == set()
    assert any("Existing procedure removals" in warning for warning in data["warnings"])
    assert not any("already removes" in warning for warning in data["warnings"])


def test_noops_pressure_scenario_and_remote_share_regressions_are_not_candidates():
    design = TrialDesign.model_validate(advice_design())
    current = Levers(remote_monitoring_share=0.8, local_lab_share=0.5,
                     drug_supply_strategy="on_demand", added_country_count=5,
                     home_visit_numbers=[3], excluded_site_ids=["s1", "s2"],
                     removed_procedures=["ecg"])
    before = (design.model_dump(), current.model_dump())
    candidates, _, _ = build_candidates(design, current)
    assert candidates == []
    assert (design.model_dump(), current.model_dump()) == before
    candidates, _, _ = build_candidates(design)
    assert all(candidate.id != "slower_enrollment" for candidate in candidates)
    assert all(candidate.levers.enrollment_rate_multiplier == 1 for candidate in candidates)


def test_slower_enrollment_is_only_an_assumption_stress_scenario(ranking_client):
    client, engine = ranking_client
    data = advice(client)
    [stress] = data["stress_scenarios"]
    assert (stress["id"], stress["tag"]) == ("slower_enrollment", "assumption")
    assert stress["label"] == "Enrollment 30% slower than your current selection"
    assert stress["levers"] == {"enrollment_rate_multiplier": 0.7}
    assert stress["delta"]["cost_usd"]["p50"] == -800
    assert stress["stockout_probability"] == 0.01
    reason = stress["reason"]
    assert "assumption, not a recommendation" in reason and "not a saving" in reason
    assert not re.search(r"reduc|saving|cheaper", reason.replace("not a saving", ""), re.I)
    # A cheaper stress result that would pass every gate still never becomes advice.
    for item in data["recommendations"] + data["rejected"]:
        assert item["id"] != "slower_enrollment"
        assert "enrollment_rate_multiplier" not in item["levers"]
    assert ids(data["recommendations"])[:2] == ["on_demand_supply", "remove_procedure:ecg"]
    assert [(call[2].enrollment_rate_multiplier, call[3], call[4]) for call in engine.comparisons
            if call[2].enrollment_rate_multiplier != 1] == [(0.7, 7, 200)]


@pytest.mark.parametrize(("current", "stressed"), [(1.0, 0.7), (1.2, 0.84), (0.6, 0.5),
                                                   (0.5, None)])
def test_stress_multiplier_follows_current_selection_and_model_floor(ranking_client, current,
                                                                     stressed):
    client, engine = ranking_client
    data = advice(client, current={"enrollment_rate_multiplier": current})
    floor_warning = any("already at the model minimum" in text for text in data["warnings"])
    if stressed is None:
        assert data["stress_scenarios"] == [] and floor_warning
        assert all(call[2].enrollment_rate_multiplier == 0.5 for call in engine.comparisons)
    else:
        assert [item["levers"] for item in data["stress_scenarios"]] == [
            {"enrollment_rate_multiplier": stressed},
        ]
        assert not floor_warning
    assert (slower_enrollment(Levers(enrollment_rate_multiplier=current)) is None) == (
        stressed is None
    )
    engine.assert_advice_sampling({"enrollment_rate_multiplier": current})


def test_stress_delta_is_null_without_its_forecast(ranking_client):
    client, engine = ranking_client
    engine.no_forecast = lambda levers: levers.enrollment_rate_multiplier < 1
    data = advice(client)
    [stress] = data["stress_scenarios"]
    assert stress["delta"] is None and stress["tag"] == "assumption"
    assert "forecast unavailable" in stress["reason"]
    assert ids(data["recommendations"]) == TOP_THREE


def test_added_countries_stay_assumed_not_registry_sites(ranking_client):
    client, engine = ranking_client
    engine.cost_overrides["added_country_count"] = -5000
    data = advice(client)
    top = data["recommendations"][0]
    assert (top["id"], top["label"], top["levers"]) == (
        "added_countries", "Add 2 assumed countries", {"added_country_count": 2},
    )
    assert "assumed sites" in top["reason"] and "not registry sites" in top["reason"]
    candidates, _, _ = build_candidates(TrialDesign.model_validate(advice_design()),
                                        Levers(added_country_count=4))
    country = next(candidate for candidate in candidates if candidate.id == "added_countries")
    assert (country.label, country.patch) == ("Add 1 assumed country", {"added_country_count": 5})


def test_home_visits_use_new_remote_capable_visits_without_telehealth_collision():
    raw = advice_design()
    raw["visits"] = [{"number": n, "label": str(n), "week": n, "can_be_remote": n != 1}
                     for n in [8, 1, 5, 9, 2]]
    candidates, _, _ = build_candidates(TrialDesign.model_validate(raw),
                                        Levers(home_visit_numbers=[2], remote_visit_numbers=[5]))
    home = next(c for c in candidates if c.id == "home_visits")
    assert home.patch == {"home_visit_numbers": [2, 8, 9]}
    assert home.levers.remote_visit_numbers == [5]


def test_site_selection_uses_reported_remaining_sites_without_imputing_unknown_zero():
    raw = advice_design()
    for site, value in zip(raw["sites"], [None, 0, 5], strict=True):
        site["expected_enrollment"] = value
    candidates, _, warnings = build_candidates(TrialDesign.model_validate(raw))
    assert [c.patch["excluded_site_ids"] for c in candidates if "excluded_site_ids" in c.patch] == [["s2"]]
    assert warnings
    for site in raw["sites"]:
        site["expected_enrollment"] = None
    candidates, _, warnings = build_candidates(TrialDesign.model_validate(raw))
    assert not any(c.levers.excluded_site_ids for c in candidates)
    assert warnings


@pytest.mark.parametrize("cost", [0, 10])
def test_all_non_improving_candidates_return_empty_not_filled_top_three(ranking_client, cost):
    client, engine = ranking_client
    engine.all_cost = cost
    data = advice(client)
    assert data["recommendations"] == []
    assert len(data["rejected"]) == 7
    assert all("does not improve" in item["reason"] for item in data["rejected"])
    assert [item["delta"]["cost_usd"]["p50"] for item in data["stress_scenarios"]] == [cost]
    engine.assert_advice_sampling()


@pytest.mark.parametrize(("risk", "reason"), [(None, "is unknown"), (0.051, "exceeds")])
def test_missing_or_excess_supply_risk_rejects_all_candidates(ranking_client, risk, reason):
    client, engine = ranking_client
    engine.risk = risk
    data = advice(client)
    assert data["recommendations"] == []
    assert len(data["rejected"]) == 7
    assert all(f"stockout probability {reason}" in item["reason"] if risk is None
               else reason in item["reason"] for item in data["rejected"])
    assert [item["stockout_probability"] for item in data["stress_scenarios"]] == [risk]
    engine.assert_advice_sampling()


@pytest.mark.parametrize("drug_type", ["none", "device"])
def test_non_drug_design_does_not_require_supply(make_client, drug_type):
    engine = RankingEngine()
    engine.risk = None
    client = make_client(engine_fns=engine.fns(), mount_optional_routers=False)
    raw = advice_design()
    raw["drug_type"] = drug_type
    save_design(client, raw)
    data = advice(client)
    assert ids(data["recommendations"]) == ["remove_procedure:ecg", "local_labs", "home_visits"]
    assert all(item["stockout_probability"] is None for item in data["recommendations"])
    assert [item["stockout_probability"] for item in data["stress_scenarios"]] == [None]
    assert "on_demand_supply" not in ids(data["rejected"])


def test_unknown_cost_duration_and_staff_remain_unknown(ranking_client):
    client, engine = ranking_client
    engine.cost_overrides["drug_supply_strategy"] = None
    engine.duration_overrides["remote_monitoring_share"] = None
    engine.staff_overrides["local_lab_share"] = None
    data = advice(client)
    assert ids(data["recommendations"]) == ["remove_procedure:ecg", "home_visits", "local_labs"]
    rejected = {item["id"]: item for item in data["rejected"]}
    assert "cost delta is unknown" in rejected["on_demand_supply"]["reason"]
    assert "duration delta is unknown" in rejected["remote_monitoring"]["reason"]
    assert data["recommendations"][2]["delta"]["site_staff_hours"]["p50"] is None


@pytest.mark.parametrize("drug_type", ["biologic", "none", "device"])
def test_missing_baseline_forecast_rejects_fallback_duration(make_client, drug_type):
    engine = RankingEngine()
    engine.no_forecast = lambda levers: True
    client = make_client(engine_fns=engine.fns(), mount_optional_routers=False)
    raw = advice_design()
    raw["drug_type"] = drug_type
    save_design(client, raw)
    data = advice(client)
    assert data["baseline"]["duration_months"]["p50"] == 24
    assert data["recommendations"] == [] and data["stress_scenarios"] == []
    assert [(item["id"], item["kind"], item["procedure"]) for item in data["rejected"]] == [
        ("forecast_unavailable", "lever", None),
    ]
    assert "forecast unavailable" in data["rejected"][0]["reason"]
    assert engine.comparisons == []
    assert [setting[:2] for setting in engine.compute_settings] == [(7, 200)]


def test_candidate_missing_forecast_is_rejected_despite_zero_duration_delta(ranking_client):
    client, engine = ranking_client
    engine.no_forecast = lambda levers: levers.drug_supply_strategy == "on_demand"
    data = advice(client)
    candidate = next(item for item in data["rejected"] if item["id"] == "on_demand_supply")
    assert candidate["delta"]["duration_months"]["p50"] == 0
    assert "forecast unavailable" in candidate["reason"]


def test_policy_uses_parameter_threshold_and_allows_equality(ranking_client):
    client, engine = ranking_client
    engine.risk = 0.05
    assert advice(client)["recommendations"]
    parameter = Parameter(id="supply.stockout_warning_threshold", label="test", value_low=0.1,
                          value_mid=0.12, value_high=0.2, unit="share")
    assert advice_policy({parameter.id: parameter}).max_stockout_probability == 0.12


@pytest.mark.parametrize("mode", ["empty", "no_procedures", "assumed"])
def test_unreviewed_schedule_returns_explicit_refusal_without_candidate_compute(make_client, mode):
    engine = RankingEngine()
    client = make_client(engine_fns=engine.fns(), mount_optional_routers=False)
    raw = advice_design()
    if mode == "empty":
        raw["visits"] = []
    elif mode == "no_procedures":
        for visit in raw["visits"]:
            visit["procedures"] = []
    else:
        raw["missing_fields"] = ["visits"]
    save_design(client, raw)
    data = advice(client)
    assert data["recommendations"] == [] and data["stress_scenarios"] == []
    [refusal] = data["rejected"]
    assert (refusal["id"], refusal["kind"], refusal["procedure"], refusal["delta"]) == (
        "reviewed_schedule_required", "lever", None, None,
    )
    assert "Reviewed visit schedule required" in refusal["reason"]
    assert engine.comparisons == []
    assert [setting[:2] for setting in engine.compute_settings] == [(7, 200)]


@pytest.mark.parametrize("raw", ["oops", "null", "[]", '{"unknown":1}',
                                 '{"remote_monitoring_share":2}',
                                 '{"enrollment_rate_multiplier":0.1}',
                                 '{"excluded_site_ids":["missing"]}'])
def test_invalid_current_selection_uses_error_envelope(ranking_client, raw):
    client, engine = ranking_client
    response = client.get("/api/scenarios/advice", params={
        "design_id": "design-test-1", "design_version": 1, "current_levers": raw,
    })
    assert response.status_code == 422, response.text
    assert set(response.json()) == {"error", "message", "details"}
    assert engine.comparisons == []


@pytest.mark.parametrize(("params", "status", "code"), [
    ({"design_id": "design-test-1"}, 422, "design_version_required"),
    ({"design_id": "missing"}, 422, "design_version_required"),
    ({"design_id": "design-test-1", "design_version": 0}, 422, "validation_error"),
    ({"design_id": "design-test-1", "design_version": "bad"}, 422, "validation_error"),
    ({"design_id": "missing", "design_version": 1}, 404, "design_not_found"),
    ({"design_id": "design-test-1", "design_version": 99}, 404, "design_not_found"),
])
def test_version_errors_precede_engine(ranking_client, params, status, code):
    client, engine = ranking_client
    response = client.get("/api/scenarios/advice", params=params)
    assert response.status_code == status
    assert response.json()["error"] == code
    assert set(response.json()) == {"error", "message", "details"}
    assert engine.comparisons == []


def test_pinned_versions_are_read_only_and_scenario_draws_stay_2000(ranking_client):
    client, engine = ranking_client
    original = advice(client)
    saved = client.get("/api/designs/design-test-1")
    changed = deepcopy(saved.json())
    changed["visits"][1]["procedures"][0]["endpoint_role"] = "supports_primary"
    save_design(client, changed, **{"If-Match": saved.headers["etag"]})
    latest_before = client.get("/api/designs/design-test-1").json()
    assert advice(client, 1) == original
    latest = advice(client, 2)
    assert next(item for item in latest["blocked"] if item["code"] == "ecg")["endpoint_roles"] == ["supports_primary"]
    assert removed_codes(original) == {"ecg"} and removed_codes(latest) == set()
    assert latest["design_hash"] != original["design_hash"]
    assert client.get("/api/designs/design-test-1").json() == latest_before
    assert len(client.get("/api/designs/design-test-1/versions").json()) == 2
    assert client.get("/api/scenarios").json() == []
    engine.assert_advice_sampling()
    response = client.post("/api/scenarios/compute", json={
        "design_id": "design-test-1", "design_version": 1, "seed": 8,
    })
    assert response.status_code == 200, response.text
    assert engine.compute_settings[-1][:2] == (8, 2000)
    assert original["scenario_draws"] == 2000 and original["draws"] == 200
    assert all(call[5] is engine.comparisons[0][5] for call in engine.comparisons)


def test_scenario_draws_follow_server_default(make_client):
    engine = RankingEngine()
    client = make_client(engine_fns=engine.fns(), mount_optional_routers=False, default_draws=5000)
    save_design(client)
    data = advice(client)
    assert (data["seed"], data["draws"], data["scenario_draws"]) == (7, 200, 5000)
    assert "own draw count (5,000 draws)" in data["sampling_note"]
    engine.assert_advice_sampling()


def test_missing_engine_keeps_existing_error_shape(make_client):
    client = make_client(engine_fns=EngineFns(), mount_optional_routers=False)
    save_design(client)
    response = client.get("/api/scenarios/advice?design_id=design-test-1&design_version=1")
    assert response.status_code == 501
    assert response.json()["error"] == "engine_not_ready"
    assert set(response.json()) == {"error", "message", "details"}


def test_advice_matches_real_engine_paired_deltas_and_supply(make_client):
    client = make_client(engine_fns=load_engine(), params_dir=REPO_ROOT / "data" / "params",
                         mount_optional_routers=False)
    raw = advice_design()
    raw["enrollment_target"] = 24
    # A second not_linked code keeps a removal candidate while the current selection removes ecg.
    raw["visits"][3]["procedures"] = [
        {"code": "vitals", "label": "Vital signs", "endpoint_role": "not_linked"},
    ]
    save_design(client, raw)
    current = Levers(remote_monitoring_share=0.25, removed_procedures=["ecg"])
    data = advice(client, current=current.model_dump())
    svc = client.app.state.services
    snap = svc.params.current()
    design = TrialDesign.model_validate(raw)
    candidates, _, _ = build_candidates(design, current)
    assert "remove_procedure:vitals" in [candidate.id for candidate in candidates]
    threshold = data["policy"]["max_stockout_probability"]

    def paired(levers):
        deltas, _ = svc.engine.compare(design, current, levers, snap.params, 7, 200)
        result = svc.engine.compute(design, levers, snap.params, snap.version, 7, 200).result
        return deltas, result

    feasible = []
    for candidate in candidates:
        deltas, result = paired(candidate.levers)
        if not (deltas["cost_usd"].p50 is None or deltas["cost_usd"].p50 >= 0
                or deltas["duration_months"].p50 is None or deltas["duration_months"].p50 > 0
                or result.supply is None or result.supply.stockout_probability > threshold):
            feasible.append((candidate.id, deltas, result.supply.stockout_probability))
    feasible.sort(key=lambda item: (
        item[1]["cost_usd"].p50,
        item[1]["site_staff_hours"].p50
        if item[1]["site_staff_hours"].p50 is not None else float("inf"),
        item[0],
    ))
    assert feasible, "This real-engine fixture must exercise at least one accepted candidate."
    assert ids(data["recommendations"]) == [item[0] for item in feasible[:3]]
    for item, (_, deltas, risk) in zip(data["recommendations"], feasible[:3], strict=True):
        assert item["stockout_probability"] == risk
        for name in METRICS:
            assert item["delta"][name] == deltas[name].model_dump()
    rejected = {item["id"]: item for item in data["rejected"]}
    assert [item["id"] for item in data["rejected"] if item["reason"] == RANKED_BELOW] == [
        item[0] for item in feasible[3:]
    ]
    for identifier, deltas, _ in feasible[3:]:
        assert rejected[identifier]["delta"]["cost_usd"] == deltas["cost_usd"].model_dump()
    assert len(data["recommendations"]) + len(data["rejected"]) == len(candidates)
    assert removed_codes(data) <= {"ecg", "vitals"}
    assert {item["code"] for item in data["blocked"]} == {"blood_draw", "mri", "unknown_test"}
    stress_levers = slower_enrollment(current).levers
    deltas, result = paired(stress_levers)
    [stress] = data["stress_scenarios"]
    assert stress["delta"]["cost_usd"] == deltas["cost_usd"].model_dump()
    assert stress["stockout_probability"] == result.supply.stockout_probability
    assert data["parameter_set_version"] == snap.version
    assert (data["draws"], data["scenario_draws"], svc.settings.default_draws) == (200, 2000, 2000)
    assert client.get("/api/scenarios").json() == []

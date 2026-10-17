"""Compute, cache, levers validation, saved scenarios, immutability, versions, compare, drivers."""

from __future__ import annotations

import sqlite3

import pytest
from conftest import ADMIN, AUTHOR, REVIEWER, FakeEngine, audit_actions, make_design, save_scenario
from fastapi.testclient import TestClient

from trialpilot_api.engine_adapter import EngineFns


# ------------------------------------------------------------------------------ compute
def test_compute_happy_path_returns_ranges_and_headers(client: TestClient, design_id: str) -> None:
    r = client.post("/api/scenarios/compute", json={
        "design_id": design_id, "levers": {"remote_monitoring_share": 0.5}})
    assert r.status_code == 200, r.text
    body = r.json()
    for m in ("cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg",
              "duration_months", "drug_waste_share"):
        assert body[m]["p10"] <= body[m]["p50"] <= body[m]["p90"]
    assert body["modules"][0]["provenance"][0]["formula_id"] == "test.fake.v1"
    assert float(r.headers["x-compute-ms"]) >= 0
    assert r.headers["x-cache"] == "miss"
    assert r.headers["x-parameter-set-version"] == body["parameter_set_version"]


def test_compute_cache_hit_on_identical_request(
    client: TestClient, design_id: str, fake_engine: FakeEngine
) -> None:
    req = {"design_id": design_id, "levers": {"local_lab_share": 0.3}, "seed": 11}
    first = client.post("/api/scenarios/compute", json=req)
    second = client.post("/api/scenarios/compute", json=req)
    assert (first.headers["x-cache"], second.headers["x-cache"]) == ("miss", "hit")
    assert first.json() == second.json()
    assert fake_engine.calls == 1
    client.post("/api/scenarios/compute", json={**req, "seed": 12})
    assert fake_engine.calls == 2  # seed is part of the cache key


def test_compute_inline_design(client: TestClient) -> None:
    r = client.post("/api/scenarios/compute", json={"design": make_design("inline-1")})
    assert r.status_code == 200 and r.json()["design_id"] == "inline-1"


@pytest.mark.parametrize("levers,needle", [
    ({"remote_monitoring_share": 1.5}, "between 0 and 1"),
    ({"local_lab_share": -0.1}, "between 0 and 1"),
    ({"home_visit_numbers": [9]}, "not in the design"),
    ({"home_visit_numbers": [3], "remote_visit_numbers": [3]}, "both home"),
    ({"removed_procedures": ["mri"]}, "do not occur"),
    ({"excluded_site_ids": ["s9"]}, "not sites"),
    ({"excluded_site_ids": ["s1", "s2", "s3"]}, "every site"),
])
def test_invalid_levers_rejected_422(
    client: TestClient, design_id: str, levers: dict, needle: str
) -> None:
    r = client.post("/api/scenarios/compute", json={"design_id": design_id, "levers": levers})
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "invalid_levers"
    assert needle in r.json()["message"]


def test_unknown_lever_key_and_bad_types_rejected_422(client: TestClient, design_id: str) -> None:
    for levers in ({"remote_monitoring_shar": 0.5}, {"drug_supply_strategy": "sometimes"},
                   {"home_visit_numbers": "three"}):
        r = client.post("/api/scenarios/compute", json={"design_id": design_id, "levers": levers})
        assert r.status_code == 422, levers
        assert r.json()["error"] == "validation_error"


def test_design_reference_rules(client: TestClient, design_id: str) -> None:
    r = client.post("/api/scenarios/compute", json={})
    assert r.json()["error"] == "design_required"
    r = client.post("/api/scenarios/compute", json={"design_id": design_id,
                                                    "design": make_design("x")})
    assert r.json()["error"] == "design_required"
    r = client.post("/api/scenarios/compute", json={"design_id": design_id, "draws": 50})
    assert r.status_code == 422


def test_moving_unflagged_visit_adds_honest_warning(client: TestClient, design_id: str) -> None:
    r = client.post("/api/scenarios/compute", json={
        "design_id": design_id, "levers": {"home_visit_numbers": [2, 3]}})
    warnings = r.json()["warnings"]
    assert any("Visits [2] are not marked can_be_remote" in w for w in warnings)


def test_engine_not_ready_and_engine_errors(make_client, fake_engine: FakeEngine) -> None:  # type: ignore[no-untyped-def]
    c = make_client(engine_fns=EngineFns())
    c.post("/api/designs", json=make_design(), headers=AUTHOR)
    r = c.post("/api/scenarios/compute", json={"design_id": "design-test-1"})
    assert r.status_code == 501 and r.json()["error"] == "engine_not_ready"

    c = make_client()
    c.post("/api/designs", json=make_design(), headers=AUTHOR)
    fake_engine.raise_exc = NotImplementedError("later")
    assert c.post("/api/scenarios/compute",
                  json={"design_id": "design-test-1"}).json()["error"] == "engine_not_ready"
    fake_engine.raise_exc = ValueError("design has zero sites")
    r = c.post("/api/scenarios/compute", json={"design_id": "design-test-1", "seed": 2})
    assert r.status_code == 422 and r.json()["error"] == "engine_rejected_input"
    assert "zero sites" in r.json()["message"]
    fake_engine.raise_exc = RuntimeError("boom")
    r = c.post("/api/scenarios/compute", json={"design_id": "design-test-1", "seed": 3})
    assert r.status_code == 500 and r.json()["error"] == "engine_error"


# ------------------------------------------------------------------------------ saved scenarios
def test_save_scenario_is_draft_and_audited(client: TestClient, design_id: str) -> None:
    s = save_scenario(client, design_id, remote_monitoring_share=0.5)
    assert s["status"] == "draft" and s["version"] == 1 and s["lineage_id"] == s["id"]
    assert s["author"] == "alex.author" and len(s["record_hash"]) == 64
    assert s["levers"]["remote_monitoring_share"] == 0.5
    assert client.get(f"/api/scenarios/{s['id']}").json()["record_hash"] == s["record_hash"]
    listing = client.get("/api/scenarios", params={"design_id": design_id}).json()
    assert [x["id"] for x in listing] == [s["id"]]
    assert set(listing[0]["metrics"]) == {"cost_usd", "site_staff_hours", "patient_travel_hours",
                                          "co2e_kg", "duration_months", "drug_waste_share"}
    assert audit_actions(client, s["id"]) == ["scenario.create"]


def test_draft_edit_by_author_only(client: TestClient, design_id: str) -> None:
    s = save_scenario(client, design_id)
    r = client.patch(f"/api/scenarios/{s['id']}", headers=AUTHOR,
                     json={"name": "B2", "levers": {"drug_supply_strategy": "on_demand"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "B2" and body["levers"]["drug_supply_strategy"] == "on_demand"
    assert body["record_hash"] != s["record_hash"] and body["version"] == 1
    r = client.patch(f"/api/scenarios/{s['id']}", headers=REVIEWER, json={"name": "x"})
    assert r.status_code == 403 and r.json()["error"] == "not_author"
    assert audit_actions(client, s["id"]) == ["scenario.create", "scenario.update"]


def test_submitted_scenario_is_immutable(client: TestClient, design_id: str) -> None:
    s = save_scenario(client, design_id)
    r = client.post(f"/api/scenarios/{s['id']}/submit", headers=AUTHOR)
    assert r.status_code == 200, r.text
    sub = r.json()
    assert sub["status"] == "submitted" and sub["approval_id"]
    assert sub["approval"]["status"] == "pending"
    assert sub["record_hash"] == s["record_hash"]

    r = client.patch(f"/api/scenarios/{s['id']}", headers=AUTHOR, json={"name": "changed"})
    assert r.status_code == 409 and r.json()["error"] == "scenario_immutable"
    r = client.patch(f"/api/scenarios/{s['id']}", headers=ADMIN, json={"name": "changed"})
    assert r.status_code == 409
    r = client.post(f"/api/scenarios/{s['id']}/submit", headers=AUTHOR)
    assert r.status_code == 409 and r.json()["error"] == "already_submitted"
    assert client.get(f"/api/scenarios/{s['id']}").json()["name"] == "Scenario B"
    assert audit_actions(client, s["id"]) == ["scenario.create", "scenario.submit"]


def test_database_refuses_changes_to_submitted_rows(client: TestClient, design_id: str) -> None:
    s = save_scenario(client, design_id)
    client.post(f"/api/scenarios/{s['id']}/submit", headers=AUTHOR)
    db = client.app.state.services.settings.resolved_db_path  # type: ignore[attr-defined]
    con = sqlite3.connect(db)
    try:
        for sql in ("UPDATE scenarios SET name = 'hacked' WHERE id = ?",
                    "UPDATE scenarios SET status = 'draft' WHERE id = ?",
                    "DELETE FROM scenarios WHERE id = ?"):
            with pytest.raises(sqlite3.DatabaseError):
                con.execute(sql, (s["id"],))
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            con.execute("UPDATE designs SET title = 'x'")
    finally:
        con.close()


def test_only_author_submits(client: TestClient, design_id: str) -> None:
    s = save_scenario(client, design_id)
    r = client.post(f"/api/scenarios/{s['id']}/submit", headers=REVIEWER)
    assert r.status_code == 403 and r.json()["error"] == "not_author"


def test_new_version_leaves_submitted_row_untouched(client: TestClient, design_id: str) -> None:
    s = save_scenario(client, design_id)
    client.post(f"/api/scenarios/{s['id']}/submit", headers=AUTHOR)
    r = client.post(f"/api/scenarios/{s['id']}/versions", headers=AUTHOR,
                    json={"levers": {"local_lab_share": 1.0}})
    assert r.status_code == 201, r.text
    v2 = r.json()
    assert (v2["version"], v2["lineage_id"], v2["parent_id"], v2["status"]) == \
        (2, s["id"], s["id"], "draft")
    base = client.get(f"/api/scenarios/{s['id']}").json()
    assert base["status"] == "submitted" and base["levers"]["local_lab_share"] == 0.0
    versions = client.get(f"/api/scenarios/{v2['id']}/versions").json()
    assert [v["version"] for v in versions] == [1, 2]
    latest = client.get("/api/scenarios", params={"latest_only": True}).json()
    assert [x["id"] for x in latest] == [v2["id"]]
    assert audit_actions(client, v2["id"]) == ["scenario.version"]


def test_compare_two_saved_scenarios(client: TestClient, design_id: str) -> None:
    a = save_scenario(client, design_id)
    b = save_scenario(client, design_id, home_visit_numbers=[3])
    r = client.post("/api/scenarios/compare", json={"a_id": a["id"], "b_id": b["id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["same_parameter_set"] is True and body["warnings"] == []
    assert body["deltas"]["patient_travel_hours"]["p50"] < 0
    assert client.post("/api/scenarios/compare",
                       json={"a_id": a["id"], "b_id": "nope"}).status_code == 404


def test_compare_needs_same_design_version(client: TestClient, design_id: str) -> None:
    a = save_scenario(client, design_id)
    changed = make_design()
    changed["enrollment_target"] = 150
    client.post("/api/designs", json=changed, headers=AUTHOR)
    b = save_scenario(client, design_id)
    r = client.post("/api/scenarios/compare", json={"a_id": a["id"], "b_id": b["id"]})
    assert r.status_code == 422 and r.json()["error"] == "compare_needs_same_design"


def test_drivers_for_saved_and_unsaved(client: TestClient, design_id: str) -> None:
    s = save_scenario(client, design_id)
    r = client.get(f"/api/scenarios/{s['id']}/drivers", params={"metric": "cost_usd", "top": 2})
    assert r.status_code == 200, r.text
    d = r.json()["drivers"]
    assert d[0]["parameter_id"] == "test.cost.visit" and d[0]["source_year"] == 2024
    assert d[1]["assumption"] is True
    r = client.post("/api/scenarios/drivers", json={"design_id": design_id, "metric": "co2e_kg"})
    assert r.status_code == 200 and r.json()["metric"] == "co2e_kg"
    r = client.get(f"/api/scenarios/{s['id']}/drivers", params={"metric": "happiness"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_metric"


def test_mutations_need_identity(client: TestClient, design_id: str) -> None:
    r = client.post("/api/scenarios", json={"name": "x", "design_id": design_id})
    assert r.status_code == 401
    r = client.post("/api/scenarios", headers=AUTHOR, json={"name": "x", "design_id": "nope"})
    assert r.status_code == 404 and r.json()["error"] == "design_not_found"


# ------------------------------------------------------------------------------ A3 caching
def test_a3_forecast_and_supply_cached_on_the_levers_they_read(make_client) -> None:  # type: ignore[no-untyped-def]
    calls = {"forecast": 0, "supply": 0}
    fake = FakeEngine()

    def compute(design, levers, params, seed=7, draws=2000, forecast=None, supply=None):  # type: ignore[no-untyped-def]
        assert forecast == "FC" and supply == f"SP-{levers.drug_supply_strategy}"
        return fake.compute_scenario(design, levers, params, seed, draws)

    def forecast(design, levers, params, seed=7, draws=2000):  # type: ignore[no-untyped-def]
        calls["forecast"] += 1
        return "FC"

    def simulate_supply(design, levers, params, forecast_draws, seed=7):  # type: ignore[no-untyped-def]
        calls["supply"] += 1
        return f"SP-{levers.drug_supply_strategy}"

    fns = fake.fns()
    fns.compute, fns.forecast, fns.simulate_supply = compute, forecast, simulate_supply
    c = make_client(engine_fns=fns)
    c.post("/api/designs", json=make_design(), headers=AUTHOR)

    def run(**levers):  # type: ignore[no-untyped-def]
        r = c.post("/api/scenarios/compute", json={"design_id": "design-test-1", "levers": levers})
        assert r.status_code == 200, r.text
        return dict(calls)

    assert run() == {"forecast": 1, "supply": 1}
    # remote monitoring / local labs / removed procedures are not read by A3: no re-run
    assert run(remote_monitoring_share=0.7, local_lab_share=0.4,
               removed_procedures=["ecg"]) == {"forecast": 1, "supply": 1}
    # the supply strategy re-runs supply only
    assert run(drug_supply_strategy="on_demand") == {"forecast": 1, "supply": 2}
    # visits moved home change the forecast
    assert run(home_visit_numbers=[3]) == {"forecast": 2, "supply": 3}
    assert c.post("/api/scenarios/compute", json={"design_id": "design-test-1"}).headers[
        "x-queue-ms"]

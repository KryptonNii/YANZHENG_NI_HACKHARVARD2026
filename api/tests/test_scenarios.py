"""Compute, cache, levers validation, saved scenarios, immutability, versions, compare, drivers."""

from __future__ import annotations

import sqlite3

import pytest
from a5_support import (
    ADMIN,
    AUTHOR,
    REVIEWER,
    FakeEngine,
    audit_actions,
    make_design,
    save_scenario,
)
from fastapi.testclient import TestClient

from trialpilot_api.engine_adapter import EngineFns


# ------------------------------------------------------------------------------ compute
@pytest.mark.req("URS-004")
def test_compute_happy_path_returns_ranges_and_headers(client: TestClient, design_id: str) -> None:
    r = client.post("/api/scenarios/compute", json={
        "design_id": design_id, "design_version": 1, "levers": {"remote_monitoring_share": 0.5}})
    assert r.status_code == 200, r.text
    body = r.json()
    for m in ("cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg",
              "duration_months", "drug_waste_share"):
        assert body[m]["p10"] <= body[m]["p50"] <= body[m]["p90"]
    assert body["modules"][0]["provenance"][0]["formula_id"] == "test.fake.v1"
    assert float(r.headers["x-compute-ms"]) >= 0
    assert r.headers["x-cache"] == "miss"
    assert r.headers["x-parameter-set-version"] == body["parameter_set_version"]


@pytest.mark.req("URS-005")
def test_compute_cache_hit_on_identical_request(
    client: TestClient, design_id: str, fake_engine: FakeEngine
) -> None:
    req = {"design_id": design_id, "design_version": 1, "levers": {"local_lab_share": 0.3}, "seed": 11}
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


@pytest.mark.req("URS-005", "URS-010")
def test_stored_compute_requires_explicit_version(client: TestClient, design_id: str) -> None:
    for route in ("compute", "drivers"):
        response = client.post(f"/api/scenarios/{route}", json={"design_id": design_id})
        assert response.status_code == 422
        assert response.json()["error"] == "design_version_required"
        assert response.json()["details"]["latest_version"] == 1
    response = client.post("/api/scenarios/compute", json={
        "design": make_design("inline"), "design_version": 1})
    assert response.status_code == 422
    assert response.json()["error"] == "inline_design_version"


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
    r = client.post("/api/scenarios/compute", json={"design_id": design_id, "design_version": 1, "levers": levers})
    assert r.status_code == 422, r.text
    assert r.json()["error"] == "invalid_levers"
    assert needle in r.json()["message"]


def test_unknown_lever_key_and_bad_types_rejected_422(client: TestClient, design_id: str) -> None:
    for levers in ({"remote_monitoring_shar": 0.5}, {"drug_supply_strategy": "sometimes"},
                   {"home_visit_numbers": "three"}):
        r = client.post("/api/scenarios/compute", json={"design_id": design_id, "design_version": 1, "levers": levers})
        assert r.status_code == 422, levers
        assert r.json()["error"] == "validation_error"


def test_design_reference_rules(client: TestClient, design_id: str) -> None:
    r = client.post("/api/scenarios/compute", json={})
    assert r.json()["error"] == "design_required"
    r = client.post("/api/scenarios/compute", json={"design_id": design_id,
                                                    "design": make_design("x")})
    assert r.json()["error"] == "design_required"
    r = client.post("/api/scenarios/compute", json={"design_id": design_id, "design_version": 1, "draws": 50})
    assert r.status_code == 422


def test_moving_unflagged_visit_adds_honest_warning(client: TestClient, design_id: str) -> None:
    r = client.post("/api/scenarios/compute", json={
        "design_id": design_id, "design_version": 1, "levers": {"home_visit_numbers": [2, 3]}})
    warnings = r.json()["warnings"]
    assert any("Visits [2] are not marked can_be_remote" in w for w in warnings)
    assert sum("can_be_remote" in w or "remote-capable" in w for w in warnings) == 1


def test_engine_remote_warning_is_not_repeated(make_client, fake_engine: FakeEngine) -> None:  # type: ignore[no-untyped-def]
    original = fake_engine.compute_scenario

    def with_engine_warning(*args, **kwargs):  # type: ignore[no-untyped-def]
        result = original(*args, **kwargs)
        return result.model_copy(update={"warnings": [
            *result.warnings,
            "Visit 2 (Week 4) is not marked remote-capable in the design but was moved "
            "to home nursing by a lever.",
        ]})

    fake_engine.compute_scenario = with_engine_warning  # type: ignore[method-assign]
    client = make_client()
    client.post("/api/designs", json=make_design(), headers=AUTHOR)
    r = client.post("/api/scenarios/compute", json={
        "design_id": "design-test-1", "design_version": 1, "levers": {"home_visit_numbers": [2]}})
    warnings = r.json()["warnings"]
    assert any("remote-capable" in w for w in warnings)
    assert not any("can_be_remote" in w for w in warnings)


def test_missing_fields_are_in_the_computed_and_saved_result(
    client: TestClient, design_id: str
) -> None:
    r = client.post("/api/scenarios/compute", json={"design_id": design_id, "design_version": 1})
    assert r.status_code == 200, r.text
    assert r.headers["x-design-version"] == "1"
    needle = (
        "Design field 'visits' is not from the source; a labelled assumption fills it "
        "(design v1 missing_fields)"
    )
    assert needle in r.json()["warnings"]
    saved = save_scenario(client, design_id, design_version=1)
    assert needle in saved["result"]["warnings"]
    assert saved["design_version"] == 1
    csv_text = client.get(f"/api/export/scenario/{saved['id']}.csv").text
    assert "design,missing_fields,,,,,visits" in csv_text
    assert needle in csv_text
    pdf = client.get(f"/api/export/scenario/{saved['id']}.pdf").content
    assert b"%PDF-" == pdf[:5]
    assert "missing_fields" in _pdf_text(pdf)
    assert "visits" in _pdf_text(pdf)


def test_engine_not_ready_and_engine_errors(make_client, fake_engine: FakeEngine) -> None:  # type: ignore[no-untyped-def]
    c = make_client(engine_fns=EngineFns())
    c.post("/api/designs", json=make_design(), headers=AUTHOR)
    r = c.post("/api/scenarios/compute", json={"design_id": "design-test-1", "design_version": 1})
    assert r.status_code == 501 and r.json()["error"] == "engine_not_ready"

    c = make_client()
    c.post("/api/designs", json=make_design(), headers=AUTHOR)
    fake_engine.raise_exc = NotImplementedError("later")
    assert c.post("/api/scenarios/compute",
                  json={"design_id": "design-test-1", "design_version": 1}).json()["error"] == "engine_not_ready"
    fake_engine.raise_exc = ValueError("design has zero sites")
    r = c.post("/api/scenarios/compute", json={"design_id": "design-test-1", "design_version": 1, "seed": 2})
    assert r.status_code == 422 and r.json()["error"] == "engine_rejected_input"
    assert "zero sites" in r.json()["message"]
    fake_engine.raise_exc = RuntimeError("boom")
    r = c.post("/api/scenarios/compute", json={"design_id": "design-test-1", "design_version": 1, "seed": 3})
    assert r.status_code == 500 and r.json()["error"] == "engine_error"


# ------------------------------------------------------------------------------ saved scenarios
@pytest.mark.req("URS-015")
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


@pytest.mark.req("URS-010")
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


@pytest.mark.req("URS-010")
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


@pytest.mark.req("URS-010")
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
    etag = client.get(f"/api/designs/{design_id}").headers["etag"]
    updated = client.post("/api/designs", json=changed, headers={**AUTHOR, "If-Match": etag})
    assert updated.status_code == 201, updated.text
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
    r = client.post("/api/scenarios/drivers", json={"design_id": design_id, "design_version": 1, "metric": "co2e_kg"})
    assert r.status_code == 200 and r.json()["metric"] == "co2e_kg"
    r = client.get(f"/api/scenarios/{s['id']}/drivers", params={"metric": "happiness"})
    assert r.status_code == 422 and r.json()["error"] == "invalid_metric"


@pytest.mark.req("URS-023")
def test_mutations_need_identity(client: TestClient, design_id: str) -> None:
    r = client.post("/api/scenarios", json={"name": "x", "design_id": design_id})
    assert r.status_code == 401
    r = client.post("/api/scenarios", headers=AUTHOR, json={"name": "x", "design_id": "nope"})
    assert r.status_code == 404 and r.json()["error"] == "design_not_found"


def test_save_pins_the_design_version_on_screen(client: TestClient, design_id: str) -> None:
    changed = make_design()
    changed["enrollment_target"] = 120
    etag = client.get(f"/api/designs/{design_id}").headers["etag"]
    updated = client.post("/api/designs", json=changed, headers={**AUTHOR, "If-Match": etag})
    assert updated.status_code == 201 and updated.headers["x-design-version"] == "2"

    latest = client.post("/api/scenarios/compute", json={"design_id": design_id, "design_version": 2})
    pinned = client.post("/api/scenarios/compute", json={
        "design_id": design_id, "design_version": 1})
    assert latest.headers["x-design-version"] == "2"
    assert pinned.headers["x-design-version"] == "1"
    assert latest.json()["cost_usd"]["p50"] != pinned.json()["cost_usd"]["p50"]

    unpinned = client.post("/api/scenarios", headers=AUTHOR, json={
        "name": "Unpinned", "design_id": design_id, "levers": {}})
    assert unpinned.status_code == 422 and unpinned.json()["error"] == "design_version_required"
    assert unpinned.json()["details"]["latest_version"] == 2

    kept = save_scenario(client, design_id, design_version=1)
    assert kept["design_version"] == 1
    assert kept["result"]["cost_usd"]["p50"] == pinned.json()["cost_usd"]["p50"]
    moved = save_scenario(client, design_id, design_version=2)
    assert moved["design_version"] == 2
    assert moved["result"]["cost_usd"]["p50"] == latest.json()["cost_usd"]["p50"]


def _range(p10, p50, p90, unit):  # type: ignore[no-untyped-def]
    return {"p10": p10, "p50": p50, "p90": p90, "unit": unit}


def test_forecast_and_supply_keep_nulls_units_and_the_sample_note(make_client) -> None:  # type: ignore[no-untyped-def]
    class _Assumption:
        def __init__(self, text: str) -> None:
            self.assumptions = [text]

    class _Forecast:
        def to_dict(self) -> dict:
            return {
                "months_to_full_enrollment": _range(10, 12, 15, "months"),
                "milestone_dates": {"last_patient_in": _range(None, None, None, "months")},
                "enrollment_curve": [[0, 0, 0, 0], [6, None, 10, 12]],
                "patients_to_randomise": _range(1, 2, 3, "patients"),
                "warnings": ["forecast producer warning"],
                "draws_requested": 2000,
                "draws_used": 2000,
                "curve_draws_used": 500,
                "provenance": [{"formula_id": "test.forecast.v1",
                                "description": "TEST forecast assumption",
                                "inputs": {}, "parameter_ids": [],
                                "assumptions": ["TEST prior rate assumption"]}],
            }

    class _Supply:
        draws_used = 100
        warnings: list[str] = []
        provenance = [_Assumption("Supply simulated on 100 forecast draws in weekly steps.")]

        def to_dict(self) -> dict:
            return {
                "strategy": "upfront",
                "kits_needed": _range(1, 2, 3, "kits"),
                "kits_produced": _range(4, 5, 6, "kits"),
                "kits_wasted": _range(None, None, None, "kits"),
                "waste_share": _range(10, 20, 30, "percent"),
                "shipments": _range(7, 8, 9, "count"),
                "stockout_probability": 0.125,
                "draws_used": 100,
                "emergency_shipments": _range(1, 1, 1, "count"),
            }

    class _BrokenSupply:
        draws_used = 80
        warnings = [
            "Large trial: drug supply simulated on 80 draws (not 2000) to stay within the "
            "compute budget; supply ranges are noisier than the other metrics."
        ]
        provenance: list = []

        def to_dict(self) -> dict:
            body = _Supply().to_dict()
            del body["stockout_probability"]
            return body

    fake = FakeEngine()

    def compute(design, levers, params, seed=7, draws=2000, forecast=None, supply=None):  # type: ignore[no-untyped-def]
        return fake.compute_scenario(design, levers, params, seed, draws)

    fns = fake.fns()
    fns.compute = compute  # type: ignore[method-assign]
    fns.forecast = lambda *a, **k: _Forecast()  # type: ignore[method-assign, assignment]
    fns.simulate_supply = lambda *a, **k: _Supply()  # type: ignore[method-assign, assignment]
    client = make_client(engine_fns=fns)
    client.post("/api/designs", json=make_design(), headers=AUTHOR)
    r = client.post("/api/scenarios/compute", json={"design_id": "design-test-1", "design_version": 1, "seed": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["forecast"]["months_to_full_enrollment"]["p50"] == 12
    assert body["forecast"]["milestone_dates"]["last_patient_in"] == {
        "p10": None, "p50": None, "p90": None, "unit": "months"}
    assert body["forecast"]["enrollment_curve"] == []
    assert "patients_to_randomise" not in body["forecast"]
    assert any("Enrollment curve omitted" in w for w in body["warnings"])
    assert body["supply"]["shipments"]["unit"] == "count"
    assert body["supply"]["kits_wasted"]["p50"] is None
    assert body["supply"]["stockout_probability"] == 0.125
    assert body["supply"]["draws_requested"] is None
    assert body["supply"]["draws_used"] == 100
    assert "forecast producer warning" in body["warnings"]
    assert body["forecast"]["draws_requested"] == body["forecast"]["draws_used"] == 2000
    assert body["forecast"]["curve_draws_used"] == 500
    assert any("Supply simulated on 100 forecast draws" in w for w in body["warnings"])

    saved = save_scenario(client, "design-test-1", design_version=1)
    assert saved["result"]["supply"]["shipments"]["unit"] == "count"
    assert any("100 forecast draws" in w for w in saved["result"]["warnings"])
    csv_text = client.get(f"/api/export/scenario/{saved['id']}.csv").text
    assert "supply,shipments," in csv_text and ",count," in csv_text
    assert "supply,kits_wasted,unknown,unknown,unknown,kits" in csv_text
    assert "supply,draws_requested,,,,count,unknown" in csv_text
    assert "supply,draws_used,,,,count,100" in csv_text
    assert "TEST prior rate assumption" in csv_text
    assert saved["result"]["forecast"]["provenance"][0]["assumptions"] == [
        "TEST prior rate assumption"]
    assert "forecast,detail,,,,,not reported" not in csv_text

    fns.simulate_supply = lambda *a, **k: _BrokenSupply()  # type: ignore[method-assign, assignment]
    broken = client.post("/api/scenarios/compute", json={
        "design_id": "design-test-1", "design_version": 1, "seed": 4,
        "levers": {"drug_supply_strategy": "on_demand"}})
    assert broken.status_code == 200, broken.text
    broken_body = broken.json()
    assert broken_body["supply"] is None
    assert any("Drug supply detail omitted" in w for w in broken_body["warnings"])
    assert any("simulated on 80 draws" in w for w in broken_body["warnings"])


def _pdf_text(data: bytes) -> str:
    """Pull text out of a ReportLab PDF (ASCII85 + Flate streams)."""
    import base64
    import re
    import zlib

    parts: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        raw = match.group(1).strip(b"\r\n \t")
        blob: bytes = raw
        try:
            if raw.endswith(b"~>"):
                blob = base64.a85decode(raw[:-2], adobe=False)
            blob = zlib.decompress(blob)
        except Exception:
            blob = raw
        parts.append(blob.decode("latin-1", errors="ignore"))
    return "\n".join(parts)


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
        r = c.post("/api/scenarios/compute", json={"design_id": "design-test-1", "design_version": 1, "levers": levers})
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
    assert c.post("/api/scenarios/compute", json={"design_id": "design-test-1", "design_version": 1}).headers[
        "x-queue-ms"]

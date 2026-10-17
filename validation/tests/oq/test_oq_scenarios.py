"""OQ: import → design → compute → scenario lifecycle through the real API, real engine and real
parameter library (offline, cached ClinicalTrials.gov fixture). Black-box: only HTTP is used."""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable
from typing import Any

import pytest

from .conftest import AUTHOR, PINS, REPO

METRICS = ("cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg", "duration_months",
           "drug_waste_share")


def _fixture_ncts() -> list[str]:
    d = REPO / "data" / "fixtures" / "ctgov"
    return sorted(p.stem for p in d.glob("NCT*.json") if not p.stem.endswith(".meta"))


def _import_design(api: Any) -> dict[str, Any]:
    ncts = _fixture_ncts()
    if not ncts:
        pytest.skip("no cached ClinicalTrials.gov fixtures")
    r = api.post(f"/api/import/ctgov/{ncts[0]}", headers=AUTHOR)
    if r.status_code == 501:
        pytest.skip("importer router not mounted")
    assert r.status_code == 200, r.text
    body = r.json()
    design = body["design"]
    r = api.post("/api/designs", json=design, headers=AUTHOR)
    assert r.status_code in (200, 201), r.text
    return design


def _compute(api: Any, design_id: str, levers: dict[str, Any] | None = None,
             seed: int = 11, draws: int = 2000) -> tuple[dict[str, Any], Any]:
    r = api.post("/api/scenarios/compute", json={"design_id": design_id, "levers": levers or {},
                                                 "seed": seed, "draws": draws})
    if r.status_code == 503:
        pytest.skip(f"engine not ready: {r.text[:200]}")
    assert r.status_code == 200, r.text
    return r.json(), r


def _p50(result: dict[str, Any], metric: str) -> float:
    v = result[metric]["p50"]
    return float("nan") if v is None else float(v)


@pytest.mark.req("URS-001")
def test_ctgov_import_offline_lists_missing_fields(api: Any) -> None:
    ncts = _fixture_ncts()
    if not ncts:
        pytest.skip("no cached ClinicalTrials.gov fixtures")
    r = api.post(f"/api/import/ctgov/{ncts[0]}", headers=AUTHOR)
    if r.status_code == 501:
        pytest.skip("importer router not mounted")
    assert r.status_code == 200, r.text
    body = r.json()
    d = body["design"]
    assert d["registry_id"] == ncts[0] and d["source"] == "ctgov"
    assert d["sites"] and d["enrollment_target"] > 0
    assert isinstance(d["missing_fields"], list) and body["missing_fields"] == d["missing_fields"]
    assert body["source"]["simulated"] is False


@pytest.mark.req("URS-004")
def test_every_metric_is_an_ordered_range_with_a_unit(api: Any) -> None:
    design = _import_design(api)
    res, _ = _compute(api, design["id"])
    for m in METRICS:
        r = res[m]
        assert r["unit"], m
        vals = [r["p10"], r["p50"], r["p90"]]
        if all(v is not None and math.isfinite(v) for v in vals):
            assert r["p10"] <= r["p50"] <= r["p90"], (m, vals)
    assert res["cost_usd"]["unit"] == "usd" and res["co2e_kg"]["unit"] == "kg_co2e"
    known = [m for m in ("cost_usd", "co2e_kg", "patient_travel_hours")
             if res[m]["p50"] is not None and math.isfinite(res[m]["p50"])]
    assert known, "no core metric could be computed for a real imported trial"
    for m in known:  # a real multi-site trial never costs/emits exactly nothing
        assert res[m]["p50"] > 0, m


@pytest.mark.req("URS-005")
def test_same_inputs_and_seed_reproduce_exactly(make_api: Callable[[], Any]) -> None:
    a, b = make_api(), make_api()  # two apps: no shared cache
    design = _import_design(a)
    b.post("/api/designs", json=design, headers=AUTHOR)
    ra, _ = _compute(a, design["id"], seed=123)
    rb, hb = _compute(b, design["id"], seed=123)
    assert hb.headers.get("X-Cache") == "miss"
    for m in METRICS:
        assert ra[m] == rb[m], m
    assert ra["parameter_set_version"] == rb["parameter_set_version"]
    rc, _ = _compute(a, design["id"], seed=124)
    assert any(ra[m] != rc[m] for m in METRICS), "seed has no effect on any metric"


@pytest.mark.req("URS-006")
def test_metrics_explain_themselves(api: Any) -> None:
    design = _import_design(api)
    res, _ = _compute(api, design["id"])
    params = api.get("/api/params").json()
    plist = params["parameters"] if isinstance(params, dict) else params
    known = {p["id"] for p in plist}
    assert res["modules"], "no module breakdown"
    for mod in res["modules"]:
        assert mod["provenance"], mod["module"]
        for item in mod["provenance"]:
            assert item["formula_id"] and item["description"]
            unknown = [pid for pid in item["parameter_ids"] if pid not in known]
            assert unknown == [], (mod["module"], unknown)


@pytest.mark.req("URS-007")
def test_levers_move_the_metrics_they_should(api: Any) -> None:
    design = _import_design(api)
    base, _ = _compute(api, design["id"])
    later = [v["number"] for v in design["visits"] if v["number"] > 1][:3]
    if later:
        home, _ = _compute(api, design["id"], {"home_visit_numbers": later})
        assert _p50(home, "patient_travel_hours") < _p50(base, "patient_travel_hours")
    od, _ = _compute(api, design["id"], {"drug_supply_strategy": "on_demand"})
    assert _p50(od, "drug_waste_share") < _p50(base, "drug_waste_share")
    rm, _ = _compute(api, design["id"], {"remote_monitoring_share": 0.5})

    def module_co2(res: dict[str, Any], name: str) -> float:
        return next(float(m["co2e_kg"]["p50"]) for m in res["modules"] if m["module"] == name)

    assert module_co2(rm, "meetings_travel") < module_co2(base, "meetings_travel")


@pytest.mark.req("URS-009")
def test_compute_p50_latency_under_300ms(api: Any) -> None:
    design = _import_design(api)
    times = []
    for seed in range(200, 207):  # distinct seeds: every call is a cache miss
        _, resp = _compute(api, design["id"], seed=seed, draws=2000)
        assert resp.headers["X-Cache"] == "miss"
        times.append(float(resp.headers["X-Compute-Ms"]))
    assert statistics.median(times) < 300, f"median {statistics.median(times):.0f} ms: {times}"


@pytest.mark.req("URS-010", "URS-021")
def test_submitted_scenario_is_immutable_and_author_cannot_approve(api: Any) -> None:
    design = _import_design(api)
    r = api.post("/api/scenarios", json={"name": "OQ scenario", "design_id": design["id"],
                                         "levers": {"remote_monitoring_share": 0.5}},
                 headers=AUTHOR)
    if r.status_code == 503:
        pytest.skip("engine not ready")
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r = api.post(f"/api/scenarios/{sid}/submit", json={}, headers=AUTHOR)
    assert r.status_code == 200, r.text
    approval_id = r.json()["approval_id"]
    assert approval_id
    r = api.patch(f"/api/scenarios/{sid}", json={"name": "edited after submit"}, headers=AUTHOR)
    assert r.status_code == 409, r.text
    r = api.post(f"/api/approvals/{approval_id}/sign",
                 json={"meaning": "approved", "pin": PINS["alex.author"]},
                 headers={"X-User": "alex.author"})
    assert r.status_code == 403 and r.json()["error"] == "self_approval_forbidden"
    view = api.get(f"/api/approvals/{approval_id}").json()
    assert view["record_type"] == "scenario" and view["status"] == "pending"
    assert view["record_changed"] is False

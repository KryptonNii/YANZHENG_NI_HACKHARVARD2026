"""Health, error shape, offline flag, designs, params, science results, static web, mounts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import AUTHOR, VIEWER, audit_actions, make_design
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from trialpilot_api.engine_adapter import EngineFns
from trialpilot_api.errors import install_error_handlers
from trialpilot_api.mounts import _include, _stub_router
from trialpilot_api.settings import Settings


# ------------------------------------------------------------------------------ health / errors
def test_health_reports_status_offline_and_modules(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["offline"] is False
    assert body["database"]["ok"] is True
    assert body["params"]["ok"] is True and body["params"]["count"] == 2
    assert body["engine"]["ready"] is True
    assert set(body["modules"]) >= {"importers", "ops", "compliance", "web"}


def test_health_offline_flag(make_client) -> None:  # type: ignore[no-untyped-def]
    assert make_client(demo_offline=True).get("/api/health").json()["offline"] is True


def test_offline_flag_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    assert Settings().demo_offline is True
    monkeypatch.setenv("DEMO_OFFLINE", "0")
    assert Settings().demo_offline is False


def test_data_dir_controls_sqlite_location(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path)
    assert s.resolved_db_path == tmp_path / "trialpilot.sqlite"


def test_error_shape_for_unknown_route_and_validation(client: TestClient) -> None:
    r = client.get("/api/nope")
    assert r.status_code == 404
    body = r.json()
    assert set(body) == {"error", "message", "details"}
    assert body["details"]["request_id"] == r.headers["x-request-id"]
    r = client.post("/api/scenarios/compute", json={"design_id": 5, "levers": []})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"


def test_request_id_is_echoed(client: TestClient) -> None:
    r = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["x-request-id"] == "abc123"


# ------------------------------------------------------------------------------ designs
def test_design_create_get_list_and_versions(client: TestClient) -> None:
    r = client.post("/api/designs", json=make_design(), headers=AUTHOR)
    assert r.status_code == 201
    assert r.headers["x-design-version"] == "1"
    assert client.get("/api/designs/design-test-1").json()["title"] == "Test trial"

    # identical content -> no new version, no audit entry
    r = client.post("/api/designs", json=make_design(), headers=AUTHOR)
    assert r.status_code == 200 and r.headers["x-design-version"] == "1"

    changed = make_design()
    changed["enrollment_target"] = 120
    r = client.post("/api/designs", json=changed, headers=AUTHOR)
    assert r.status_code == 201 and r.headers["x-design-version"] == "2"
    assert client.get("/api/designs/design-test-1?version=1").json()["enrollment_target"] == 100
    assert client.get("/api/designs/design-test-1").json()["enrollment_target"] == 120

    listing = client.get("/api/designs").json()
    assert [(d["id"], d["version"], d["site_count"]) for d in listing] == [("design-test-1", 2, 3)]
    assert len(client.get("/api/designs/design-test-1/versions").json()) == 2
    assert audit_actions(client, "design-test-1") == ["design.create", "design.update"]


def test_design_id_generated_when_missing(client: TestClient) -> None:
    r = client.post("/api/designs", json=make_design(design_id=None), headers=AUTHOR)
    assert r.status_code == 201
    assert len(r.json()["id"]) == 36


def test_design_validation_and_identity(client: TestClient) -> None:
    bad = make_design()
    del bad["sites"]
    assert client.post("/api/designs", json=bad, headers=AUTHOR).status_code == 422
    dup = make_design()
    dup["sites"].append(dup["sites"][0])
    r = client.post("/api/designs", json=dup, headers=AUTHOR)
    assert r.status_code == 422 and r.json()["error"] == "invalid_design"
    r = client.post("/api/designs", json=make_design())
    assert r.status_code == 401 and r.json()["error"] == "identity_required"
    r = client.post("/api/designs", json=make_design(), headers=VIEWER)
    assert r.status_code == 403 and r.json()["error"] == "forbidden_role"
    r = client.post("/api/designs", json=make_design(), headers={"X-User": "a b"})
    assert r.status_code == 400
    assert client.get("/api/designs/unknown").json()["error"] == "design_not_found"


def test_fixture_designs_are_seeded(make_client, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    trials = tmp_path / "fixtures" / "trials"
    trials.mkdir(parents=True)
    (trials / "demo.json").write_text(json.dumps({"design": make_design("demo-1")}))
    (trials / "broken.json").write_text("{not json")
    c = make_client(seed_fixture_designs=True)
    assert [d["id"] for d in c.get("/api/designs").json()] == ["demo-1"]
    assert audit_actions(c, "demo-1") == ["design.create"]


# ------------------------------------------------------------------------------ params
def test_params_listing_with_sources(client: TestClient) -> None:
    body = client.get("/api/params").json()
    assert body["ok"] is True and body["count"] == 2 and body["assumption_count"] == 1
    assert len(body["parameter_set_version"]) == 12
    sourced = client.get("/api/params/test.cost.visit").json()
    assert sourced["source_url"] == "https://example.org/test" and sourced["source_year"] == 2024
    only = client.get("/api/params", params={"ids": "test.ef.car_km"}).json()["parameters"]
    assert [p["id"] for p in only] == ["test.ef.car_km"]
    assert client.get("/api/params/nope").json()["error"] == "param_not_found"
    assert len(client.get("/api/params/test.ef.car_km/history").json()) == 1


def test_param_change_without_version_bump_is_reported_and_kept(
    client: TestClient, tmp_path: Path
) -> None:
    v1 = client.get("/api/params").json()["parameter_set_version"]
    f = tmp_path / "params" / "test.yaml"
    f.write_text(f.read_text().replace("value_high: 30", "value_high: 35"))
    svc = client.app.state.services  # type: ignore[attr-defined]
    svc.params._checked_at = 0.0  # skip the 1 s reload throttle
    body = client.get("/api/params").json()
    assert body["parameter_set_version"] != v1
    assert any("test.cost.visit v1 changed without a version bump" in c for c in body["conflicts"])
    assert [p["value_high"] for p in client.get("/api/params/test.cost.visit/history").json()] \
        == [30, 35]
    old = {p.id: p for p in svc.params.params_for_set(v1)}
    assert old["test.cost.visit"].value_high == 30  # old results stay explainable


def test_invalid_param_library_blocks_compute(make_client, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    bad = tmp_path / "badparams"
    bad.mkdir()
    (bad / "x.yaml").write_text("parameters:\n  - id: Bad Id\n    label: x\n")
    c = make_client(params_dir=bad)
    assert c.get("/api/health").json()["params"]["ok"] is False
    c.post("/api/designs", json=make_design(), headers=AUTHOR)
    r = c.post("/api/scenarios/compute", json={"design_id": "design-test-1"})
    assert r.status_code == 503 and r.json()["error"] == "params_invalid"
    assert r.json()["details"]["problems"]


# ------------------------------------------------------------------------------ science / web
def test_science_results_missing_then_served(make_client, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    c = make_client()
    r = c.get("/api/science/results")
    assert r.status_code == 404 and r.json()["error"] == "science_results_missing"
    (tmp_path / "results.json").write_text(json.dumps({"trials": [{"id": "CASPS"}]}))
    assert c.get("/api/science/results").json() == {"trials": [{"id": "CASPS"}]}


def test_built_web_app_served_with_spa_fallback(make_client, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>TrialPilot</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    c = make_client()
    assert "TrialPilot" in c.get("/").text
    assert "TrialPilot" in c.get("/scenario/abc").text
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/api/unknown").json()["error"] == "not_found"
    assert c.get("/api/health").json()["modules"]["web"]["status"] == "served"


# ------------------------------------------------------------------------------ mounts
def test_router_prefix_detection_and_not_ready_stub() -> None:
    app = FastAPI()
    install_error_handlers(app)
    relative = APIRouter()
    relative.add_api_route("/{trial_id}/health", lambda trial_id: {"t": trial_id})
    absolute = APIRouter()
    absolute.add_api_route("/api/audit/verify", lambda: {"ok": True})
    assert _include(app, relative, ["/api/ops"]) == "/api/ops"
    assert _include(app, absolute, ["/api/audit", "/api/approvals"]) == ""
    app.include_router(_stub_router("/api/import", "importers", "A4", "not built"))
    c = TestClient(app)
    assert c.get("/api/ops/t1/health").json() == {"t": "t1"}
    assert c.get("/api/audit/verify").json() == {"ok": True}
    r = c.post("/api/import/ctgov/NCT1")
    assert r.status_code == 501 and r.json()["details"]["owner"] == "A4"


def test_missing_optional_modules_answer_501_not_ready(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client(mount_optional_routers=False)
    for path in ("/api/ops/t1/health", "/api/audit", "/api/import/ctgov/NCT00000000"):
        r = c.get(path) if "import" not in path else c.post(path)
        assert r.status_code == 501, path
        assert r.json()["error"] == "not_ready"


def test_engine_missing_reports_not_ready(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client(engine_fns=EngineFns(status={"engine": "not_installed"}))
    assert c.get("/api/health").json()["engine"]["ready"] is False

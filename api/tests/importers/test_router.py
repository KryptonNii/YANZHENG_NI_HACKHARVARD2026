"""HTTP behaviour of the importer router (offline, bad input, double submit, audit)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trialpilot_api.importers import router as router_mod
from trialpilot_api.importers.tools.make_synthetic_protocol import make_pdf

from .conftest import DEMO_NCT

AUTHOR = {"X-User": "alex.author", "X-Role": "author"}


@pytest.mark.req("URS-001", "URS-029", "URS-015")
def test_import_ctgov_offline(client: TestClient, audit_log: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    r = client.post(f"/api/import/ctgov/{DEMO_NCT.lower()}", headers=AUTHOR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["design"]["registry_id"] == DEMO_NCT and body["raw_cached"] is True
    assert body["missing_fields"] == body["design"]["missing_fields"] and "visits" in body["missing_fields"]
    assert body["source"]["simulated"] is False and body["source"]["name"] == "ClinicalTrials.gov"
    assert body["design"]["drug_type"] == "biologic" and len(body["design"]["sites"]) == 275
    prot = [d for d in body["documents"] if d["has_protocol"]]
    assert prot and prot[0]["extraction_cached"] is True
    assert audit_log[-1]["action"] == "import.ctgov" and audit_log[-1]["actor"] == "alex.author"
    assert audit_log[-1]["after_hash"] and audit_log[-1]["object_id"] == body["design"]["id"]


@pytest.mark.parametrize("bad", ["12345", "NCT12", "ISRCTN12345678", "NCT0393073X"])
@pytest.mark.req("URS-001")
def test_invalid_registry_id(client: TestClient, bad: str, audit_log: list[dict[str, Any]]) -> None:
    r = client.post(f"/api/import/ctgov/{bad}")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_registry_id" and set(r.json()) == {"error", "message", "details"}
    assert audit_log == []  # only successful imports are audited


@pytest.mark.req("URS-001", "URS-029")
def test_offline_unknown_trial(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    r = client.post("/api/import/ctgov/NCT09999999")
    assert r.status_code == 503 and r.json()["error"] == "offline_cache_miss"


@pytest.mark.req("URS-001")
def test_not_found_maps_to_404(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from trialpilot_api.importers.ctgov import StudyNotFound

    def nf(*_: Any, **__: Any) -> Any:
        raise StudyNotFound("NCT09999999 was not found on ClinicalTrials.gov.", {"nct_id": "NCT09999999"})

    monkeypatch.setattr(router_mod, "fetch_study_result", nf)
    r = client.post("/api/import/ctgov/NCT09999999")
    assert r.status_code == 404 and r.json()["error"] == "study_not_found"


@pytest.mark.req("URS-001")
def test_network_failure_maps_to_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from trialpilot_api.importers.ctgov import RegistryUnavailable

    def down(*_: Any, **__: Any) -> Any:
        raise RegistryUnavailable("ClinicalTrials.gov could not be reached.")

    monkeypatch.setattr(router_mod, "fetch_study_result", down)
    r = client.post("/api/import/ctgov/NCT09999999")
    assert r.status_code == 503 and r.json()["error"] == "registry_unavailable"


@pytest.mark.req("URS-001", "URS-029")
def test_list_cached_studies(client: TestClient) -> None:
    r = client.get("/api/import/ctgov")
    assert r.status_code == 200
    ids = {s["nct_id"]: s for s in r.json()["studies"]}
    assert set(ids) == {"NCT03930732", "NCT04429503", "NCT04456673", "NCT04535986"}
    assert ids[DEMO_NCT]["protocol_extraction_cached"] is True and ids[DEMO_NCT]["sites"] == 275


@pytest.mark.req("URS-002", "URS-015")
def test_protocol_upload_returns_candidates_not_applied(client: TestClient, audit_log: list[dict[str, Any]]) -> None:
    pdf = make_pdf("text")
    r = client.post("/api/import/protocol", files={"file": ("tp-syn.pdf", pdf, "application/pdf")},
                    data={"design_id": "d-123"}, headers=AUTHOR)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["auto_applied"] is False and body["design_id"] == "d-123"
    assert len(body["candidates"]) == 7 and body["warnings"]
    c0 = body["candidates"][0]
    assert {"visit", "source_page", "quote", "confidence", "procedures"} <= set(c0)
    assert audit_log[-1]["action"] == "import.protocol.extract"
    assert "not applied" in audit_log[-1]["reason"]


@pytest.mark.req("URS-002")
def test_double_submit_hits_cache(client: TestClient) -> None:
    pdf = make_pdf("text")
    a = client.post("/api/import/protocol", files={"file": ("a.pdf", pdf, "application/pdf")}).json()
    b = client.post("/api/import/protocol", files={"file": ("b.pdf", pdf, "application/pdf")}).json()
    assert a["extraction_id"] == b["extraction_id"] and b["from_cache"] is True


@pytest.mark.req("URS-002", "URS-029")
def test_protocol_by_nct_offline_uses_cached_demo_extraction(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    r = client.post("/api/import/protocol", data={"nct_id": DEMO_NCT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["from_cache"] is True and len(body["candidates"]) == 19
    assert body["document"]["source"] == "ctgov" and body["document"]["url"].endswith("Prot_000.pdf")


@pytest.mark.req("URS-002", "URS-029")
def test_protocol_by_nct_offline_without_cache(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    r = client.post("/api/import/protocol", data={"nct_id": "NCT04456673"})
    assert r.status_code == 503 and r.json()["error"] == "offline_cache_miss"


@pytest.mark.req("URS-002")
def test_protocol_too_large(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router_mod, "MAX_UPLOAD_BYTES", 1000)
    r = client.post("/api/import/protocol", files={"file": ("big.pdf", b"%PDF" + b"0" * 5000, "application/pdf")})
    assert r.status_code == 413 and r.json()["error"] == "payload_too_large"


@pytest.mark.req("URS-002")
def test_protocol_bad_inputs(client: TestClient) -> None:
    assert client.post("/api/import/protocol").json()["error"] == "missing_input"
    r = client.post("/api/import/protocol", files={"file": ("x.pdf", b"", "application/pdf")})
    assert r.status_code == 400 and r.json()["error"] == "empty_file"
    r = client.post("/api/import/protocol", files={"file": ("x.txt", b"not a pdf", "text/plain")})
    assert r.status_code == 415 and r.json()["error"] == "not_a_pdf"
    r = client.post("/api/import/protocol", data={"nct_id": "bogus"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_registry_id"


@pytest.mark.req("URS-002", "URS-015")
def test_apply_replaces_visits_and_clears_missing_flag(client: TestClient, audit_log: list[dict[str, Any]],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    design = client.post(f"/api/import/ctgov/{DEMO_NCT}").json()["design"]
    ext = client.post("/api/import/protocol", data={"nct_id": DEMO_NCT}).json()
    visits = [c["visit"] for c in ext["candidates"]]
    r = client.post("/api/import/protocol/apply", json={"design": design, "visits": visits,
                                                        "extraction_id": ext["extraction_id"]}, headers=AUTHOR)
    assert r.status_code == 200, r.text
    new = r.json()["design"]
    assert len(new["visits"]) == 19 and "visits" not in new["missing_fields"]
    assert new["id"] == design["id"] and new["sites"] == design["sites"]
    last = audit_log[-1]
    assert last["action"] == "import.protocol.apply" and last["before_hash"] != last["after_hash"]


@pytest.mark.req("URS-002")
def test_apply_rejects_bad_schedules(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    design = client.post(f"/api/import/ctgov/{DEMO_NCT}").json()["design"]
    bad = [{"number": 1, "label": "a", "week": 10}, {"number": 2, "label": "b", "week": 4}]
    r = client.post("/api/import/protocol/apply", json={"design": design, "visits": bad}, headers=AUTHOR)
    assert r.status_code == 422 and r.json()["error"] == "weeks_not_increasing"
    dup = [{"number": 1, "label": "a", "week": 0}, {"number": 1, "label": "b", "week": 4}]
    assert client.post("/api/import/protocol/apply", json={"design": design, "visits": dup},
                       headers=AUTHOR).json()["error"] == "duplicate_visit_numbers"


@pytest.mark.req("URS-002", "URS-023")
@pytest.mark.parametrize(("headers", "status", "code"), [
    ({}, 401, "identity_required"),
    ({"X-User": "val.viewer", "X-Role": "viewer"}, 403, "forbidden_role"),
    ({"X-User": "ai:extractor", "X-Role": "author"}, 403, "ai_confirmation_forbidden"),
])
def test_only_a_person_can_confirm(client: TestClient, monkeypatch: pytest.MonkeyPatch, audit_log: list[dict[str, Any]],
                                   headers: dict[str, str], status: int, code: str) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    design = client.post(f"/api/import/ctgov/{DEMO_NCT}").json()["design"]
    visits = [{"number": 1, "label": "a", "week": 0}]
    n_audit = len(audit_log)
    r = client.post("/api/import/protocol/apply", json={"design": design, "visits": visits}, headers=headers)
    assert r.status_code == status and r.json()["error"] == code
    r = client.post("/api/import/protocol/review", json={"extraction_id": "e1", "accepted": 1, "edited": 0,
                                                         "rejected": 0}, headers=headers)
    assert r.status_code == status and r.json()["error"] == code
    assert len(audit_log) == n_audit  # nothing was confirmed, so nothing is audited as confirmed


@pytest.mark.req("URS-002", "URS-015")
def test_review_log_and_stats(client: TestClient, isolated_dirs: dict[str, Path], audit_log: list[dict[str, Any]]) -> None:
    assert client.get("/api/import/protocol/review/stats").json()["reviews"] == 0
    r = client.post("/api/import/protocol/review", json={"extraction_id": "e1", "accepted": 15, "edited": 3, "rejected": 1},
                    headers=AUTHOR)
    assert r.status_code == 200
    r = client.post("/api/import/protocol/review", json={"extraction_id": "e2", "accepted": 5, "edited": 0, "rejected": 0},
                    headers=AUTHOR)
    s = r.json()
    assert s["reviews"] == 2 and s["accepted"] == 20 and s["accepted_unchanged_share"] == round(20 / 24, 3)
    assert (isolated_dirs["runtime"] / "review_log.jsonl").exists()
    assert audit_log[-1]["action"] == "import.protocol.review"
    assert client.post("/api/import/protocol/review", json={"extraction_id": "e3", "accepted": -1,
                                                            "edited": 0, "rejected": 0}, headers=AUTHOR).status_code == 422


@pytest.mark.req("URS-015")
def test_audit_failure_blocks_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    app = FastAPI()
    app.include_router(router_mod.router, prefix="/api/import")

    def broken_audit(*_: Any, **__: Any) -> None:
        raise RuntimeError("disk full")

    app.dependency_overrides[router_mod.get_auditor] = lambda: broken_audit
    with TestClient(app) as c:
        r = c.post(f"/api/import/ctgov/{DEMO_NCT}")
    assert r.status_code == 503 and r.json()["error"] == "audit_unavailable" and "design" not in r.json()


@pytest.mark.req("URS-001", "URS-015")
def test_mounted_in_the_real_app_uses_a7_audit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke test through A5's create_app (skipped if A5's app factory is not importable yet)."""
    main = pytest.importorskip("trialpilot_api.main")
    settings_mod = pytest.importorskip("trialpilot_api.settings")
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    try:
        settings = settings_mod.Settings(db_path=str(tmp_path / "tp.sqlite"), seed_fixture_designs=False)
    except Exception as exc:  # pragma: no cover - A5 settings shape changed
        pytest.skip(f"A5 Settings signature differs: {exc}")
    app = main.create_app(settings)
    with TestClient(app) as c:
        r = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers=AUTHOR)
        assert r.status_code == 200, r.text
        audit = c.get("/api/audit", params={"action": "import.ctgov"})
        if audit.status_code == 200:
            entries = audit.json()["items"]  # A7: {"items": [...], "total": n}
            assert any(e["object_id"] == r.json()["design"]["id"] and e["actor"] == "alex.author" for e in entries)


@pytest.mark.req("URS-023", "URS-015")
def test_real_app_takes_the_role_from_the_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inside A5's app a claimed X-Role must match A7's registry; the audited role is the registered one."""
    main = pytest.importorskip("trialpilot_api.main")
    settings_mod = pytest.importorskip("trialpilot_api.settings")
    if not hasattr(pytest.importorskip("trialpilot_api.deps"), "resolve_identity"):
        pytest.skip("A5's deps.resolve_identity (registry roles) not present; the router uses the header fallback")
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    settings = settings_mod.Settings(db_path=str(tmp_path / "tp.sqlite"), seed_fixture_designs=False)
    with TestClient(main.create_app(settings)) as c:
        if not c.app.state.services.compliance.has_user_registry:  # type: ignore[attr-defined]
            pytest.skip("A7 user registry not available (stub mode)")
        r = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers={"X-User": "alex.author", "X-Role": "qa"})
        assert r.status_code == 403 and r.json()["error"] == "role_mismatch"
        r = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers={"X-User": "mallory", "X-Role": "author"})
        assert r.status_code == 403 and r.json()["error"] == "unknown_user"
        r = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers={"X-User": "riley.reviewer"})  # no X-Role at all
        assert r.status_code == 200, r.text
        design = r.json()["design"]
        r = c.post("/api/import/protocol/apply", headers={"X-User": "val.viewer"},
                   json={"design": design, "visits": [{"number": 1, "label": "a", "week": 0}]})
        assert r.status_code == 403 and r.json()["error"] == "forbidden_role"
        entries = c.get("/api/audit", params={"action": "import.ctgov"}).json()["items"]
        mine = [e for e in entries if e["object_id"] == design["id"] and e["actor"] == "riley.reviewer"]
        assert mine and all(e["role"] == "reviewer" for e in mine)

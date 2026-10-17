"""HTTP behaviour of the importer router (offline, bad input, double submit, audit)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
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


@pytest.mark.req("URS-001")
def test_non_json_registry_answer_maps_to_503(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from trialpilot_api.importers import ctgov

    def maintenance_page(*_: Any, **__: Any) -> httpx.Response:
        return httpx.Response(200, text="<html>Down for maintenance</html>")

    monkeypatch.setattr(ctgov, "_get_json", maintenance_page)
    r = client.post("/api/import/ctgov/NCT09999999")
    assert r.status_code == 503 and set(r.json()) == {"error", "message", "details"}
    assert r.json()["error"] == "registry_unavailable"
    assert r.json()["details"] == {"nct_id": "NCT09999999", "status": 200}
    r = client.post(f"/api/import/ctgov/{DEMO_NCT}", params={"refresh": "true"})
    assert r.status_code == 200 and r.json()["stale_fallback"] is True
    assert r.json()["notes"][0].startswith("ClinicalTrials.gov could not be reached; the cached copy from ")


@pytest.mark.req("URS-001", "URS-029")
def test_import_notes_are_tagged_by_field(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    body = client.post(f"/api/import/ctgov/{DEMO_NCT}").json()
    assert body["notes"] == [n["text"] for n in body["field_notes"]]
    visits = body["notes_by_field"]["visits"]
    assert len(visits) == 1
    assert visits[0]["kind"] == "assumption" and visits[0]["assumption"] is True
    assert visits[0]["clears_when_present"] is True
    assert visits[0]["field"] == "visits" and "NOT in the registry" in visits[0]["text"]
    enrolled = body["notes_by_field"]["enrollment_target"][0]
    assert enrolled["kind"] == "fact" and enrolled["assumption"] is False
    assert enrolled["clears_when_present"] is False
    assert "actual number enrolled" in enrolled["text"]
    per_site = body["notes_by_field"]["sites.expected_enrollment"][0]
    assert per_site["kind"] == "missing" and per_site["assumption"] is False
    assert per_site["clears_when_present"] is True
    geo = next(n for n in body["field_notes"] if "GeoNames" in n["text"])
    assert geo["field"] == "sites.lat_lon" and geo["kind"] == "assumption" and geo["assumption"] is True
    assert geo["clears_when_present"] is False
    ecg = next(p for v in body["design"]["visits"] for p in v["procedures"] if p["code"] == "ecg")
    assert ecg["group_label"] == "Electrocardiogram"
    assert "12-lead" not in ecg["group_label"]
    questionnaire = next(p for v in body["design"]["visits"] for p in v["procedures"] if p["code"] == "questionnaire")
    assert questionnaire["group_label"] == "Questionnaires and diaries"
    assert body["procedure_group_labels"]["questionnaire"] == "Questionnaires and diaries"
    assert "SGRQ" not in body["procedure_group_labels"]["questionnaire"]


@pytest.mark.req("URS-001")
def test_procedure_code_catalog(client: TestClient) -> None:
    r = client.get("/api/import/procedure-codes")
    assert r.status_code == 200
    body = r.json()
    codes = {c["code"]: c for c in body["codes"]}
    assert codes["questionnaire"]["group_label"] == "Questionnaires and diaries"
    assert codes["biomarker_sample"]["group_label"] == "Biomarker and genetic samples"
    assert codes["spirometry"]["group_label"] == "Spirometry assessments"
    for code, row in codes.items():
        assert row["group_label"].strip() and "PARC" not in row["group_label"]
        assert "pre-BD" not in row["group_label"] and code not in row["group_label"]


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
    assert body["auto_applied"] is False and body["notice"].startswith("DRAFT")
    assert body["llm_accuracy"] == "unmeasured"
    assert body["llm_accuracy_note"] == "Real LLM accuracy was not measured."
    assert body["candidates"][0]["quote"] and body["candidates"][0]["source_page"]
    labels = body["procedure_group_labels"]
    assert labels["questionnaire"] == "Questionnaires and diaries"
    assert "PARC" not in labels["biomarker_sample"]
    assert "pre-BD" not in labels["spirometry"] and "post-BD" not in labels["spirometry"]
    spirometry = next(p for c in body["candidates"] for p in c["visit"]["procedures"] if p["code"] == "spirometry")
    assert spirometry["group_label"] == "Spirometry assessments"
    assert spirometry["label"] in {"Spirometry (pre-BD)", "Spirometry (post-BD)"}


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
    assert r.json()["cleared_fields"] == ["visits"]
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
    empty = client.get("/api/import/protocol/review/stats").json()
    assert empty["reviews"] == 0 and empty["accepted_unchanged_share_status"] == "no_reviews"
    assert empty["llm_accuracy"] == "unmeasured"
    assert empty["llm_accuracy_note"] == "Real LLM accuracy was not measured."
    # An old client omits bulk_accepted. That is unknown, not a claim that every row was checked.
    r = client.post("/api/import/protocol/review", json={"extraction_id": "e1", "accepted": 15, "edited": 3, "rejected": 1},
                    headers=AUTHOR)
    assert r.status_code == 200
    r = client.post("/api/import/protocol/review", json={"extraction_id": "e2", "accepted": 5, "edited": 0, "rejected": 0},
                    headers=AUTHOR)
    s = r.json()
    assert s["reviews"] == 2 and s["accepted"] == 20
    assert s["accepted_unchanged_share"] is None and s["accepted_unchanged_share_status"] == "unknown"
    assert s["accuracy_unknown_reviews"] == 2 and s["bulk_accepted"] is None and s["individually_accepted"] is None
    logged = [json.loads(ln) for ln in (isolated_dirs["runtime"] / "review_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(row["bulk_accepted"] is None for row in logged)  # omitted stays null; it is not written as 0
    assert audit_log[-1]["action"] == "import.protocol.review"
    assert client.post("/api/import/protocol/review", json={"extraction_id": "e3", "accepted": -1,
                                                            "edited": 0, "rejected": 0}, headers=AUTHOR).status_code == 422


@pytest.mark.req("URS-002")
def test_explicit_zero_bulk_keeps_the_per_row_share(client: TestClient) -> None:
    """bulk_accepted: 0 means the client attests that each accepted row was opened."""
    client.post("/api/import/protocol/review", headers=AUTHOR, json={
        "extraction_id": "e1", "accepted": 15, "edited": 3, "rejected": 1, "bulk_accepted": 0})
    r = client.post("/api/import/protocol/review", headers=AUTHOR, json={
        "extraction_id": "e2", "accepted": 5, "edited": 0, "rejected": 0, "bulk_accepted": 0})
    s = r.json()
    assert s["accepted_unchanged_share"] == round(20 / 24, 3)
    assert s["accepted_unchanged_share_status"] == "review_log_only"
    assert s["individually_accepted"] == 20 and s["bulk_accepted"] == 0
    assert s["accuracy_unknown_reviews"] == 0
    assert s["llm_accuracy"] == "unmeasured"


@pytest.mark.req("URS-002")
def test_bulk_accepted_is_excluded_from_the_share(client: TestClient) -> None:
    # 10 accepted, 4 of them in one "accept all", plus 2 edits and 1 rejection.
    # Share uses the 6 rows opened and accepted: 6 / (6 + 2 + 1).
    r = client.post("/api/import/protocol/review", headers=AUTHOR, json={
        "extraction_id": "e1", "accepted": 10, "edited": 2, "rejected": 1, "bulk_accepted": 4})
    s = r.json()
    assert s["individually_accepted"] == 6 and s["bulk_accepted"] == 4
    assert s["accepted_unchanged_share"] == round(6 / 9, 3)
    assert s["accepted_unchanged_share_status"] == "review_log_only"
    # Every row bulk-accepted: there is no per-row check, so the share is not 1.
    r = client.post("/api/import/protocol/review", headers=AUTHOR, json={
        "extraction_id": "e2", "accepted": 19, "edited": 0, "rejected": 0, "bulk_accepted": 19})
    s = r.json()
    assert s["accepted"] == 29 and s["individually_accepted"] == 6 and s["bulk_accepted"] == 23
    assert s["accepted_unchanged_share"] == round(6 / 9, 3)
    r = client.post("/api/import/protocol/review", headers=AUTHOR, json={
        "extraction_id": "e3", "accepted": 8, "edited": 0, "rejected": 0, "bulk_accepted": 9})
    assert r.status_code == 422 and r.json()["error"] == "bulk_accepted_exceeds_accepted"


@pytest.mark.req("URS-002")
def test_bulk_only_review_is_not_an_accuracy(client: TestClient) -> None:
    r = client.post("/api/import/protocol/review", headers=AUTHOR, json={
        "extraction_id": "e1", "accepted": 19, "edited": 0, "rejected": 0, "bulk_accepted": 19})
    s = r.json()
    assert s["accepted_unchanged_share"] is None
    assert s["accepted_unchanged_share_status"] == "no_individual_review"
    assert s["individually_accepted"] == 0 and s["bulk_accepted"] == 19
    assert s["llm_accuracy"] == "unmeasured"


@pytest.mark.req("URS-002")
def test_old_review_log_is_unknown_and_not_rewritten(client: TestClient, isolated_dirs: dict[str, Path]) -> None:
    path = isolated_dirs["runtime"] / "review_log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {"extraction_id": "legacy", "accepted": 19, "edited": 0, "rejected": 0, "added": 0, "unit": "visit"}
    path.write_text(json.dumps(old) + "\n", encoding="utf-8")
    s = client.get("/api/import/protocol/review/stats").json()
    assert s["reviews"] == 1 and s["accepted"] == 19
    assert s["accepted_unchanged_share"] is None and s["accepted_unchanged_share_status"] == "unknown"
    assert s["accuracy_unknown_reviews"] == 1
    assert s["bulk_accepted"] is None and s["individually_accepted"] is None
    assert json.loads(path.read_text(encoding="utf-8")) == old  # no fabricated bulk_accepted
    client.post("/api/import/protocol/review", headers=AUTHOR, json={
        "extraction_id": "new", "accepted": 4, "edited": 1, "rejected": 0, "bulk_accepted": 0})
    s = client.get("/api/import/protocol/review/stats").json()
    assert s["reviews"] == 2 and s["accepted"] == 23
    assert s["accepted_unchanged_share"] is None and s["accuracy_unknown_reviews"] == 1
    first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert first == old


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


# ---------------------------------------------------------------- mounted app: endpoint annotations
def _mounted_app(tmp_path: Path, **settings: Any) -> Any:
    main = pytest.importorskip("trialpilot_api.main")
    settings_mod = pytest.importorskip("trialpilot_api.settings")
    return main.create_app(settings_mod.Settings(db_path=str(tmp_path / "tp.sqlite"), seed_fixture_designs=False,
                                                 **settings))


@pytest.fixture
def mounted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A5's app, offline through both the environment and its Settings (the documented launch paths)."""
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    app = _mounted_app(tmp_path, _env_file=None)
    with TestClient(app) as c:
        yield c
    app.state.db_engine.dispose()


def _candidate_visits(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [c["visit"] for c in body["candidates"]]


def _annotation(body: dict[str, Any], target: dict[str, Any]) -> tuple[str, str, str]:
    """(role, note, basis) of the candidate procedure in visit 2 with the target's code and label."""
    visit = next(v for v in _candidate_visits(body) if v["number"] == 2)
    p = next(p for p in visit["procedures"] if (p["code"], p["label"]) == (target["code"], target["label"]))
    return p["endpoint_role"], p["endpoint_note"], p["link_basis"]


def _human_count(body: dict[str, Any]) -> int:
    return sum(p["link_basis"] == "human" for v in _candidate_visits(body) for p in v["procedures"])


def _save_with_human_choice(c: TestClient, design: dict[str, Any], visits: list[dict[str, Any]],
                            role: str, note: str) -> dict[str, Any]:
    """Store `design` with `visits`, where visit 2's first procedure carries a human endpoint decision."""
    visits = json.loads(json.dumps(visits))
    target: dict[str, Any] = next(v for v in visits if v["number"] == 2)["procedures"][0]
    target.update(endpoint_role=role, endpoint_note=note, link_basis="human")
    r = c.post("/api/designs", json={**design, "visits": visits}, headers=AUTHOR)
    assert r.status_code in (200, 201), r.text
    return target


@pytest.mark.req("URS-002", "URS-001")
def test_protocol_candidates_get_the_saved_human_choice(mounted: TestClient) -> None:
    c = mounted
    first = c.post("/api/import/protocol", data={"nct_id": DEMO_NCT}).json()
    design = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers=AUTHOR).json()["design"]
    target = _save_with_human_choice(c, design, _candidate_visits(first), "supports_secondary", "checked by a person")
    for form in ({"nct_id": DEMO_NCT.lower()}, {"nct_id": DEMO_NCT, "design_id": design["id"]}):
        body = c.post("/api/import/protocol", data=form).json()
        assert _annotation(body, target) == ("supports_secondary", "checked by a person", "human"), form
        assert _human_count(body) == 1, form
        assert body["design_id"] == form.get("design_id") and body["document"]["source"] == "ctgov"
    # The cached extraction itself is not rewritten: without a stored design nothing is human.
    assert _human_count(first) == 0


@pytest.mark.req("URS-002", "URS-001")
def test_protocol_annotation_uses_design_id_only_for_the_same_registry_id(mounted: TestClient) -> None:
    c = mounted
    visits = _candidate_visits(c.post("/api/import/protocol", data={"nct_id": DEMO_NCT}).json())
    demo = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers=AUTHOR).json()["design"]
    other = c.post("/api/import/ctgov/NCT04535986", headers=AUTHOR).json()["design"]
    target = _save_with_human_choice(c, demo, visits, "not_linked", "from the imported design")
    _save_with_human_choice(c, other, visits, "supports_secondary", "from another trial")
    _save_with_human_choice(c, {**demo, "id": "copy-of-demo"}, visits, "supports_primary", "from a saved copy")
    # A design for another registry id is ignored; the design imported from nct_id is used instead.
    body = c.post("/api/import/protocol", data={"nct_id": DEMO_NCT, "design_id": other["id"]}).json()
    assert _annotation(body, target) == ("not_linked", "from the imported design", "human")
    assert body["design_id"] == other["id"]
    # A design for the same registry id is the one given.
    body = c.post("/api/import/protocol", data={"nct_id": DEMO_NCT, "design_id": "copy-of-demo"}).json()
    assert _annotation(body, target) == ("supports_primary", "from a saved copy", "human")


@pytest.mark.req("URS-002", "URS-001")
def test_uploaded_protocol_uses_the_stored_design(mounted: TestClient) -> None:
    c = mounted
    upload = {"file": ("tp-syn.pdf", make_pdf("text"), "application/pdf")}
    first = c.post("/api/import/protocol", files=upload).json()
    design = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers=AUTHOR).json()["design"]
    target = _save_with_human_choice(c, design, _candidate_visits(first), "supports_secondary", "seen in the CSR")
    body = c.post("/api/import/protocol", files=upload, data={"design_id": design["id"]}).json()
    assert _annotation(body, target) == ("supports_secondary", "seen in the CSR", "human")
    assert _human_count(body) == 1 and body["document"]["source"] == "upload"
    # An unknown design and no NCT id: no registry record and no saved decision, so nothing is linked.
    body = c.post("/api/import/protocol", files=upload, data={"design_id": "no-such-design"}).json()
    assert all((p["endpoint_role"], p["endpoint_note"], p["link_basis"]) == ("unknown", "", "unmatched")
               for v in _candidate_visits(body) for p in v["procedures"])


@pytest.mark.req("URS-002")
def test_uploaded_protocol_without_registry_record_stays_unknown(client: TestClient) -> None:
    pdf = make_pdf("text")
    body = client.post("/api/import/protocol", files={"file": ("tp-syn.pdf", pdf, "application/pdf")}).json()
    procedures = [p for v in _candidate_visits(body) for p in v["procedures"]]
    assert procedures and all((p["endpoint_role"], p["endpoint_note"], p["link_basis"]) == ("unknown", "", "unmatched")
                              for p in procedures)
    assert body["document"] == {"filename": "tp-syn.pdf", "size_bytes": len(pdf), "source": "upload"}
    assert body["design_id"] is None


@pytest.mark.req("URS-001")
def test_reimport_keeps_the_saved_human_choice(mounted: TestClient) -> None:
    c = mounted
    design = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers=AUTHOR).json()["design"]
    visits = json.loads(json.dumps(design["visits"]))
    target = visits[0]["procedures"][0]
    target.update(endpoint_role="supports_primary", endpoint_note="a person linked this", link_basis="human")
    assert c.post("/api/designs", json={**design, "visits": visits}, headers=AUTHOR).status_code in (200, 201)
    again = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers=AUTHOR).json()["design"]
    got = again["visits"][0]["procedures"][0]
    assert (got["code"], got["label"]) == (target["code"], target["label"])
    assert (got["endpoint_role"], got["endpoint_note"], got["link_basis"]) == (
        "supports_primary", "a person linked this", "human")
    # Every other procedure is linked exactly as on the first import.
    first = [p for v in design["visits"] for p in v["procedures"]][1:]
    second = [p for v in again["visits"] for p in v["procedures"]][1:]
    assert second == first


# ---------------------------------------------------------------- mounted app: offline flag
def _no_network(*_: Any, **__: Any) -> Any:
    raise AssertionError("network used")


@pytest.mark.req("URS-029", "URS-001", "URS-002")
def test_mounted_importers_follow_the_app_offline_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings say offline (what /api/health reports) while DEMO_OFFLINE is unset: no network call."""
    monkeypatch.delenv("DEMO_OFFLINE", raising=False)
    monkeypatch.delenv("TP_DEMO_OFFLINE", raising=False)
    monkeypatch.setattr(httpx, "Client", _no_network)
    app = _mounted_app(tmp_path, _env_file=None, demo_offline=True)
    with TestClient(app) as c:
        assert c.get("/api/health").json()["offline"] is True
        assert c.get("/api/import/ctgov").json()["offline"] is True
        r = c.post("/api/import/ctgov/NCT09999999", headers=AUTHOR)
        assert r.status_code == 503 and r.json()["error"] == "offline_cache_miss"
        r = c.post(f"/api/import/ctgov/{DEMO_NCT}", params={"refresh": "true"}, headers=AUTHOR)
        assert r.status_code == 200 and r.json()["raw_cached"] is True and r.json()["stale_fallback"] is False
        r = c.post("/api/import/protocol", data={"nct_id": "NCT04456673"})
        assert r.status_code == 503 and r.json()["error"] == "offline_cache_miss"
        r = c.post("/api/import/protocol", files={"file": ("scan.pdf", make_pdf("image"), "application/pdf")})
        assert r.status_code == 503 and r.json()["error"] == "extraction_unavailable"
        assert "offline demo mode" in r.json()["message"]
    app.state.db_engine.dispose()


@pytest.mark.req("URS-029", "URS-001")
def test_mounted_importers_online_setting_wins_over_the_environment(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    monkeypatch.setattr(httpx, "Client", _no_network)
    app = _mounted_app(tmp_path, _env_file=None, demo_offline=False)
    with TestClient(app) as c:
        assert c.get("/api/health").json()["offline"] is False
        assert c.get("/api/import/ctgov").json()["offline"] is False
        r = c.post(f"/api/import/ctgov/{DEMO_NCT}", headers=AUTHOR)  # cache first, so still no network call
        assert r.status_code == 200 and r.json()["raw_cached"] is True
    app.state.db_engine.dispose()

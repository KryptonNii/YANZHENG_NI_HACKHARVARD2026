"""HTTP layer of the compliance router (mounted on a bare FastAPI app)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trialpilot_api.compliance import (
    ComplianceError,
    compliance_error_handler,
    hashing,
    router,
    store,
)

from .conftest import PINS

H = hashing.sha256_hex("scenario B")


@pytest.fixture()
def client(db: store.Store) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.add_exception_handler(ComplianceError, compliance_error_handler)
    return TestClient(app)


def _as(user: str) -> dict[str, str]:
    return {"X-User": user}


@pytest.mark.req("URS-021", "URS-022")
def test_demo_sequence_over_http(client: TestClient) -> None:
    r = client.post("/api/approvals", json={"record_type": "scenario", "record_id": "B",
                                            "record_hash": H, "title": "Scenario B"},
                    headers=_as("alex.author"))
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert r.json()["next_meaning"] == "reviewed" and r.json()["status"] == "pending"

    r = client.post(f"/api/approvals/{rid}/sign", json={"meaning": "approved", "pin": "1111"},
                    headers=_as("alex.author"))
    assert r.status_code == 403
    body = r.json()
    assert body["error"] == "self_approval_forbidden" and body["message"] and "details" in body

    r = client.post(f"/api/approvals/{rid}/sign", json={"meaning": "approved", "pin": "3333"},
                    headers=_as("sam.qa"))
    assert r.status_code == 409 and r.json()["error"] == "out_of_order"

    r = client.post(f"/api/approvals/{rid}/sign",
                    json={"meaning": "reviewed", "pin": PINS["riley.reviewer"]},
                    headers=_as("riley.reviewer"))
    assert r.status_code == 200 and r.json()["next_meaning"] == "approved"
    r = client.post(f"/api/approvals/{rid}/sign",
                    json={"meaning": "approved", "pin": PINS["sam.qa"]}, headers=_as("sam.qa"))
    assert r.status_code == 200
    view = r.json()
    assert view["status"] == "approved"
    assert [s["meaning"] for s in view["signatures"]] == ["reviewed", "approved"]
    assert "Sam QA" in view["signatures"][1]["manifestation"]

    v = client.get("/api/audit/verify").json()
    assert v["ok"] is True and v["checked"] >= 6
    assert client.get("/api/approvals", params={"status": "approved"}).json()["items"][0]["id"] == rid


@pytest.mark.req("URS-023")
def test_mutations_need_identity(client: TestClient) -> None:
    r = client.post("/api/approvals", json={"record_type": "scenario", "record_id": "B",
                                            "record_hash": H})
    assert r.status_code == 401 and r.json()["error"] == "identity_required"
    r = client.post("/api/approvals/x/sign", json={"meaning": "reviewed", "pin": "1"})
    assert r.status_code == 401


@pytest.mark.req("URS-018")
def test_wrong_pin_and_lockout_over_http(client: TestClient) -> None:
    rid = client.post("/api/approvals", json={"record_type": "scenario", "record_id": "B",
                                              "record_hash": H},
                      headers=_as("alex.author")).json()["id"]
    codes = [client.post(f"/api/approvals/{rid}/sign", json={"meaning": "reviewed", "pin": "0"},
                         headers=_as("riley.reviewer")).status_code for _ in range(4)]
    assert codes == [401, 401, 423, 423]


@pytest.mark.req("URS-015", "URS-028")
def test_audit_list_and_export(client: TestClient) -> None:
    client.post("/api/approvals", json={"record_type": "scenario", "record_id": "B",
                                        "record_hash": H}, headers=_as("alex.author"))
    page = client.get("/api/audit", params={"limit": 10}).json()
    assert page["total"] == len(page["items"]) >= 1
    assert page["items"][0]["action"] == "approval.submit"
    r = client.get("/api/audit/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert len(rows) - 1 == page["total"]


def test_users_and_roles(client: TestClient) -> None:
    users = client.get("/api/compliance/users").json()["items"]
    assert {u["username"] for u in users} >= {"alex.author", "riley.reviewer", "sam.qa", "admin"}
    roles = client.get("/api/compliance/roles").json()
    assert roles["permissions"]["sign.approved"] == ["qa"]


def test_served_output_pointer_is_used_only_when_env_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from trialpilot_api.compliance import config

    pointer = tmp_path / "served_output.txt"
    pointer.write_text(str(tmp_path / "stamp") + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "served_output_pointer", lambda: pointer)
    monkeypatch.delenv("TP_VALIDATION_OUT", raising=False)
    assert config.validation_out_dir() == tmp_path / "stamp"
    monkeypatch.setenv("TP_VALIDATION_OUT", str(tmp_path / "env-wins"))
    assert config.validation_out_dir() == tmp_path / "env-wins"


def test_validation_package_missing_then_served(client: TestClient, tmp_path: Path) -> None:
    r = client.get("/api/validation/package")
    assert r.status_code == 404 and r.json()["error"] == "package_not_built"
    pkg = tmp_path / "vout" / "package"
    pkg.mkdir(parents=True)
    (pkg / "package_index.json").write_text(json.dumps({"deliverables": [
        {"id": "plan", "status": "draft"}]}), encoding="utf-8")
    (pkg / "plan.md").write_text("# Plan\n", encoding="utf-8")
    assert client.get("/api/validation/package").json()["deliverables"][0]["id"] == "plan"
    r = client.get("/api/validation/package/files/plan.md")
    assert r.status_code == 200 and r.text.startswith("# Plan")
    assert client.get("/api/validation/package/files/..%2F..%2Fsecret").status_code in (400, 404)
    assert client.get("/api/validation/package/files/nope.md").status_code == 404


@pytest.mark.req("URS-020")
def test_validation_package_status_follows_the_live_approval(client: TestClient,
                                                             tmp_path: Path) -> None:
    """A build-time 'approved' / 'awaiting approval' label never outlives the approval behind it."""
    from trialpilot_api.compliance import records, workflow

    doc = tmp_path / "report.md"
    doc.write_text("summary v1", encoding="utf-8")
    records.register_file("validation_report", "VSR-1", doc)
    vsr = workflow.create_request("validation_report", "VSR-1", "alex.author").id
    workflow.sign_request(vsr, "sam.qa", PINS["sam.qa"], "approved")
    cr = workflow.create_request("change_record", "CR-1", "alex.author", record_hash=H).id
    workflow.reject_request(cr, "sam.qa", PINS["sam.qa"], "out of scope")
    workflow.create_request("scenario", "B", "alex.author", record_hash=H)  # stays pending

    def d(did: str, status: str, record_type: str, record_id: str) -> dict[str, str]:
        return {"id": did, "status": status, "approval_record_type": record_type,
                "approval_record_id": record_id}

    pkg = tmp_path / "vout" / "package"
    pkg.mkdir(parents=True)
    (pkg / "package_index.json").write_text(json.dumps({"deliverables": [
        d("A1", "awaiting approval", "validation_report", "VSR-1"),
        d("A2", "approved", "validation_report", "VSR-1"),
        d("A3", "generated", "validation_report", "VSR-1"),
        d("R1", "awaiting approval", "change_record", "CR-1"),
        d("R2", "approved", "change_record", "CR-1"),
        d("R3", "draft", "change_record", "CR-1"),
        d("P1", "awaiting approval", "scenario", "B"),
        d("P2", "approved", "scenario", "B"),
        d("P3", "draft", "scenario", "B"),
        d("N1", "awaiting approval", "validation_report", "VSR-9"),
        d("N2", "approved", "validation_report", "VSR-9"),
        {"id": "plan", "status": "generated"},
    ]}), encoding="utf-8")

    def statuses() -> dict[str, str]:
        r = client.get("/api/validation/package")
        assert r.status_code == 200, r.text
        return {x["id"]: x["status"] for x in r.json()["deliverables"]}

    assert statuses() == {
        "A1": "approved", "A2": "approved", "A3": "approved",
        "R1": "rejected", "R2": "rejected", "R3": "draft",
        "P1": "awaiting approval", "P2": "awaiting approval", "P3": "draft",
        "N1": "awaiting approval", "N2": "approval unconfirmed",
        "plan": "generated",
    }

    doc.write_text("summary v2 (edited after QA approval)", encoding="utf-8")
    by_id = {x["id"]: x for x in client.get("/api/validation/package").json()["deliverables"]}
    assert {i: by_id[i]["status"] for i in ("A1", "A2", "A3")} == {
        "A1": "approval invalid", "A2": "approval invalid", "A3": "generated"}
    assert by_id["A2"]["approval"]["approved"] is False
    assert by_id["A2"]["approval"]["status"] == "approved"
    assert "changed after approval" in by_id["A2"]["approval"]["reason"]


@pytest.mark.req("URS-026", "URS-028")
def test_deep_evidence_paths_can_be_hashed_and_downloaded(client: TestClient, tmp_path: Path) -> None:
    from trialpilot_api.compliance import records

    relative = Path("evidence") / ("scenario-" + "x" * 80) / ("attachments-" + "y" * 80)
    relative /= "screenshot-" + "z" * 60 + ".png"
    path = tmp_path / "vout" / "package" / relative
    assert len(str(path)) > 260
    target = hashing.fs_path(path)
    target.parent.mkdir(parents=True)
    target.write_bytes(b"PNG fixture")
    records.register_file("test_artifact", "long-path", path)
    assert records.current_hash("test_artifact", "long-path") == hashing.sha256_hex(b"PNG fixture")
    response = client.get(f"/api/validation/package/files/{relative.as_posix()}")
    assert response.status_code == 200 and response.content == b"PNG fixture"
    assert response.headers["content-type"] == "image/png"

"""Demo step 3 end to end (submit -> self-approval blocked -> review -> QA approval), the
compliance stub, CSV/PDF export and the SSE helper."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest
from a5_support import AUTHOR, PINS, QA, REVIEWER, audit_actions, make_design, save_scenario
from fastapi.testclient import TestClient

from trialpilot_api.sse import EventBroker, sse_response


def _a7_active(client: TestClient) -> bool:
    return client.app.state.services.compliance.status.get("audit") == "a7"  # type: ignore[attr-defined]


def _sign(client: TestClient, approval_id: str, who: dict[str, str], meaning: str):  # type: ignore[no-untyped-def]
    return client.post(f"/api/approvals/{approval_id}/sign", headers=who,
                       json={"meaning": meaning, "pin": PINS[who["X-User"]]})


# ------------------------------------------------------------------------------ approval flow
def test_demo_approval_flow_with_a7(client: TestClient, design_id: str) -> None:
    if not _a7_active(client):
        pytest.skip("A7 compliance package not importable")
    s = save_scenario(client, design_id, remote_monitoring_share=0.5)
    sub = client.post(f"/api/scenarios/{s['id']}/submit", headers=AUTHOR).json()
    approval_id = sub["approval_id"]

    r = _sign(client, approval_id, AUTHOR, "reviewed")
    assert r.status_code == 403 and r.json()["error"] == "self_approval_forbidden"
    assert _sign(client, approval_id, REVIEWER, "reviewed").status_code == 200
    assert client.get(f"/api/scenarios/{s['id']}").json()["status"] == "submitted"
    assert _sign(client, approval_id, QA, "approved").status_code == 200

    final = client.get(f"/api/scenarios/{s['id']}").json()
    assert final["status"] == "approved" and final["decided_at"]
    assert [x["meaning"] for x in final["approval"]["signatures"]] == ["reviewed", "approved"]
    assert all(x["record_hash"] == s["record_hash"] for x in final["approval"]["signatures"])
    actions = audit_actions(client, s["id"])
    assert actions[:2] == ["scenario.create", "scenario.submit"]
    assert actions[-1] == "scenario.approved"
    verify = client.get("/api/audit/verify").json()
    assert verify["ok"] is True

    r = client.patch(f"/api/scenarios/{s['id']}", headers=AUTHOR, json={"name": "after"})
    assert r.status_code == 409


@pytest.mark.req("URS-023")
def test_compliance_errors_use_the_app_error_shape(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compliance errors carry details.request_id like every other route; a malformed body is
    still a 422 before the identity check."""
    if not _a7_active(client):
        pytest.skip("A7 compliance package not importable")
    sign = {"meaning": "reviewed", "pin": PINS[REVIEWER["X-User"]]}

    r = client.post("/api/approvals/nope/sign", headers=REVIEWER, json=sign)
    assert r.status_code == 404 and r.json()["error"] == "approval_not_found"
    assert r.json()["details"]["request_id"] == r.headers["x-request-id"]

    r = client.post("/api/approvals/nope/sign", json=sign)
    assert r.status_code == 401 and r.json()["error"] == "identity_required"
    assert r.json()["details"]["request_id"] == r.headers["x-request-id"]

    r = client.post("/api/approvals/nope/sign", json={"meaning": "bogus", "pin": "1"})
    assert r.status_code == 422 and r.json()["error"] == "validation_error"

    monkeypatch.setenv("TP_VALIDATION_OUT", str(tmp_path / "no-package-here"))
    r = client.get("/api/validation/package")
    assert r.status_code == 404 and r.json()["error"] == "package_not_built"
    assert r.json()["details"]["expected_path"] == "validation/out/package/package_index.json"
    assert r.json()["details"]["request_id"] == r.headers["x-request-id"]


@pytest.mark.req("URS-015")
def test_stub_compliance_keeps_mutations_audited(make_client) -> None:  # type: ignore[no-untyped-def]
    c = make_client(mount_optional_routers=False)
    svc = c.app.state.services
    assert svc.compliance.status["audit"] == "stub"
    c.post("/api/designs", json=make_design(), headers=AUTHOR)
    s = save_scenario(c, "design-test-1")
    sub = c.post(f"/api/scenarios/{s['id']}/submit", headers=AUTHOR).json()
    assert sub["status"] == "submitted" and sub["approval"]["status"] == "pending"
    assert sub["approval"]["record_hash"] == s["record_hash"]
    assert sub["approval"]["created_at"]
    assert audit_actions(c, s["id"]) == ["scenario.create", "scenario.submit"]
    # A row stored by an older constructor can omit the v3 keys. The columns still have them.
    import json
    import sqlite3

    db = svc.settings.resolved_db_path
    con = sqlite3.connect(db)
    try:
        approval_id, payload, record_hash, created_at = con.execute(
            "SELECT id, data, record_hash, created_at FROM approvals_stub"
        ).fetchone()
        body = json.loads(payload)
        body.pop("record_hash", None)
        body.pop("created_at", None)
        con.execute("UPDATE approvals_stub SET data = ? WHERE id = ?",
                    (json.dumps(body), approval_id))
        con.commit()
    finally:
        con.close()
    again = c.get(f"/api/scenarios/{s['id']}")
    assert again.status_code == 200, again.text
    approval = again.json()["approval"]
    assert approval["record_hash"] == record_hash
    assert approval["created_at"].startswith(created_at[:19])
    assert svc.compliance.stub_verify() == {"ok": True, "first_bad_seq": None, "checked": 3}
    assert c.get("/api/audit").status_code == 501


def test_stub_audit_chain_detects_tampering(make_client) -> None:  # type: ignore[no-untyped-def]
    import sqlite3

    c = make_client(mount_optional_routers=False)
    c.post("/api/designs", json=make_design(), headers=AUTHOR)
    save_scenario(c, "design-test-1")
    svc = c.app.state.services
    con = sqlite3.connect(svc.settings.resolved_db_path)
    con.execute("DROP TRIGGER audit_stub_no_update")
    con.execute("UPDATE audit_stub SET actor = 'mallory' WHERE seq = 1")
    con.commit()
    con.close()
    assert svc.compliance.stub_verify()["first_bad_seq"] == 1


# ------------------------------------------------------------------------------ export
@pytest.mark.req("URS-028")
def test_export_csv_and_pdf(client: TestClient, design_id: str) -> None:
    s = save_scenario(client, design_id, remote_monitoring_share=0.5)
    client.post(f"/api/scenarios/{s['id']}/submit", headers=AUTHOR)
    r = client.get(f"/api/export/scenario/{s['id']}.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = [line.split(",")[0] for line in r.text.splitlines()[1:]]
    for section in ("scenario", "lever", "metric", "module", "provenance", "warning",
                    "assumption", "parameter", "approval"):
        assert section in rows, section
    assert rows.count("metric") == 6
    assert "https://example.org/test" in r.text and "ASSUMPTION: test fixture only" in r.text
    assert "design,missing_fields,,,,,visits" in r.text
    assert "Design field 'visits' is not from the source" in r.text
    assert "forecast,detail,,,,,not reported" in r.text
    assert "supply,detail,,,,,not reported" in r.text

    r = client.get(f"/api/export/scenario/{s['id']}.pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-"
    assert client.get("/api/export/scenario/nope.csv").status_code == 404


@pytest.mark.req("URS-028")
def test_export_pdf_lists_signatures(client: TestClient, design_id: str) -> None:
    if not _a7_active(client):
        pytest.skip("A7 compliance package not importable")
    s = save_scenario(client, design_id)
    approval_id = client.post(f"/api/scenarios/{s['id']}/submit",
                              headers=AUTHOR).json()["approval_id"]
    _sign(client, approval_id, REVIEWER, "reviewed")
    r = client.get(f"/api/export/scenario/{s['id']}.csv")
    assert "signature,riley.reviewer" in r.text and "Riley" in r.text  # printed name
    assert client.get(f"/api/export/scenario/{s['id']}.pdf").content[:5] == b"%PDF-"


# ------------------------------------------------------------------------------ SSE
def test_broker_replays_after_last_event_id() -> None:
    b = EventBroker(buffer_size=3)
    for i in range(4):
        b.publish("ops:t1", "ops_event", {"i": i})
    assert [m.data["i"] for m in b.replay("ops:t1", None)] == [1, 2, 3]  # bounded buffer
    assert [m.data["i"] for m in b.replay("ops:t1", "3")] == [3]
    assert [m.id for m in b.replay("ops:t1", "4")] == []
    assert b.replay("other", None) == []


def test_subscribe_replays_then_streams_live_from_other_threads() -> None:
    b = EventBroker()
    b.publish("ops:t1", "ops_event", {"n": 1})
    b.publish("ops:t1", "alert_new", {"n": 2})

    async def run() -> list[tuple[str, str, int]]:
        got: list[tuple[str, str, int]] = []
        agen = b.subscribe("ops:t1", last_event_id="1")
        got.append(_t(await agen.__anext__()))  # replayed id 2
        threading.Thread(target=b.publish, args=("ops:t1", "alert_update", {"n": 3})).start()
        got.append(_t(await asyncio.wait_for(agen.__anext__(), 2)))  # live id 3
        await agen.aclose()
        return got

    def _t(m):  # type: ignore[no-untyped-def]
        return (m.id, m.event, m.data["n"])

    assert asyncio.run(run()) == [("2", "alert_new", 2), ("3", "alert_update", 3)]
    assert b.subscriber_count("ops:t1") == 0


def test_sse_response_uses_15s_heartbeat_and_last_event_id() -> None:
    from starlette.requests import Request

    scope = {"type": "http", "method": "GET", "path": "/s", "query_string": b"",
             "headers": [(b"last-event-id", b"7")]}
    resp = sse_response(Request(scope), "ops:t1", EventBroker())
    assert resp.ping_interval == 15
    assert resp.headers["cache-control"] == "no-cache"


@pytest.mark.req("URS-004")
def test_unknown_metrics_survive_save_and_export(make_client, fake_engine) -> None:  # type: ignore[no-untyped-def]
    """The engine reports a metric it cannot compute as NaN (unknown, never 0): JSON shows null,
    storage round-trips it, exports say 'unknown'."""
    original = fake_engine.compute_scenario

    def with_unknown(*args, **kwargs):  # type: ignore[no-untyped-def]
        r = original(*args, **kwargs)
        nan = float("nan")
        return r.model_copy(update={"co2e_kg": r.co2e_kg.model_copy(
            update={"p10": nan, "p50": nan, "p90": nan})})

    fake_engine.compute_scenario = with_unknown
    c = make_client()
    c.post("/api/designs", json=make_design(), headers=AUTHOR)
    s = save_scenario(c, "design-test-1")
    assert s["result"]["co2e_kg"]["p50"] is None
    assert c.get(f"/api/scenarios/{s['id']}").json()["result"]["co2e_kg"]["p50"] is None
    csv_text = c.get(f"/api/export/scenario/{s['id']}.csv").text
    assert "metric,co2e_kg,unknown,unknown,unknown,kg_co2e" in csv_text
    assert c.get(f"/api/export/scenario/{s['id']}.pdf").status_code == 200

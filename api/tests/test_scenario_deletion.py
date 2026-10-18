"""Removing a scenario version keeps the signed record and its history intact."""

from __future__ import annotations

from typing import Any

import pytest
from a5_support import ADMIN, AUTHOR, PINS, QA, REVIEWER, VIEWER, audit_actions, save_scenario
from fastapi.testclient import TestClient
from sqlmodel import Session

from trialpilot_api.db import ScenarioDeletionRow, ScenarioRow
from trialpilot_api.routes_scenarios import resolve_scenario_hash


def _sign(client: TestClient, approval_id: str, who: dict[str, str], meaning: str) -> None:
    response = client.post(f"/api/approvals/{approval_id}/sign", headers=who,
                           json={"meaning": meaning, "pin": PINS[who["X-User"]]})
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("status", ["draft", "submitted", "approved", "rejected"])
def test_delete_preserves_record_hash_approvals_and_exports(
    client: TestClient, design_id: str, status: str,
) -> None:
    scenario = save_scenario(client, design_id)
    sid = scenario["id"]
    approval: dict[str, Any] | None = None
    if status != "draft":
        submitted = client.post(f"/api/scenarios/{sid}/submit", headers=AUTHOR)
        assert submitted.status_code == 200, submitted.text
        aid = submitted.json()["approval_id"]
        if status == "approved":
            _sign(client, aid, REVIEWER, "reviewed")
            _sign(client, aid, QA, "approved")
        elif status == "rejected":
            rejected = client.post(f"/api/approvals/{aid}/reject", headers=REVIEWER,
                                   json={"pin": "2222", "reason": "Superseded by a new plan."})
            assert rejected.status_code == 200, rejected.text
        # Sync the decision before comparing the preserved scenario row below.
        assert client.get(f"/api/scenarios/{sid}").json()["status"] == status
        approval = client.get(f"/api/approvals/{aid}").json()

    engine = client.app.state.db_engine  # type: ignore[attr-defined]
    with Session(engine) as session:
        row = session.get(ScenarioRow, sid)
        assert row is not None
        before = row.model_dump()

    response = client.delete(f"/api/scenarios/{sid}", headers=AUTHOR)
    assert response.status_code == 204 and response.content == b""
    assert client.get(f"/api/scenarios/{sid}").status_code == 404
    assert client.get("/api/scenarios", params={"design_id": design_id}).json() == []
    with Session(engine) as session:
        row = session.get(ScenarioRow, sid)
        assert row is not None and row.model_dump() == before
        deletion = session.get(ScenarioDeletionRow, sid)
        assert deletion is not None
        assert deletion.deleted_by == "alex.author" and deletion.deleted_at.endswith("Z")
    assert resolve_scenario_hash(engine, sid) == scenario["record_hash"]
    if approval is not None:
        assert client.get(f"/api/approvals/{approval['id']}").json() == approval
    # Historical reports remain available from their original links.
    exported = client.get(f"/api/export/scenario/{sid}.csv")
    assert exported.status_code == 200 and scenario["name"] in exported.text
    entries = client.get("/api/audit", params={"object_id": sid}).json()["items"]
    deletion_entry = next(item for item in entries if item["action"] == "scenario.delete")
    assert deletion_entry["before_hash"] == deletion_entry["after_hash"] == scenario["record_hash"]
    assert client.get("/api/audit/verify").json()["ok"] is True
    actions = audit_actions(client, sid)
    assert client.delete(f"/api/scenarios/{sid}", headers=AUTHOR).status_code == 204
    assert audit_actions(client, sid) == actions


@pytest.mark.parametrize("headers,expected", [({}, 401), (VIEWER, 403), (REVIEWER, 403), (QA, 403)])
def test_delete_requires_author_or_admin(
    client: TestClient, design_id: str, headers: dict[str, str], expected: int,
) -> None:
    scenario = save_scenario(client, design_id)
    assert client.delete(f"/api/scenarios/{scenario['id']}", headers=headers).status_code == expected
    assert client.get(f"/api/scenarios/{scenario['id']}").status_code == 200
    assert audit_actions(client, scenario["id"]) == ["scenario.create"]


def test_admin_can_delete_without_impersonating_author(client: TestClient, design_id: str) -> None:
    scenario = save_scenario(client, design_id)
    sid = scenario["id"]
    assert client.delete(f"/api/scenarios/{sid}", headers=ADMIN).status_code == 204
    assert client.delete(f"/api/scenarios/{sid}", headers=AUTHOR).status_code == 204
    assert client.delete(f"/api/scenarios/{sid}", headers=REVIEWER).status_code == 403
    assert client.delete("/api/scenarios/nonexistent", headers=AUTHOR).status_code == 404
    entries = client.get("/api/audit", params={"object_id": sid}).json()["items"]
    assert next(e for e in entries if e["action"] == "scenario.delete")["actor"] == "admin"


def test_deleted_version_cannot_be_loaded_edited_submitted_compared_or_branched(
    client: TestClient, design_id: str,
) -> None:
    scenario = save_scenario(client, design_id)
    other = save_scenario(client, design_id, local_lab_share=0.4)
    sid = scenario["id"]
    assert client.delete(f"/api/scenarios/{sid}", headers=AUTHOR).status_code == 204
    for suffix in ("", "/versions", "/drivers"):
        assert client.get(f"/api/scenarios/{sid}{suffix}").status_code == 404
    assert client.patch(f"/api/scenarios/{sid}", headers=AUTHOR,
                        json={"name": "Changed"}).status_code == 404
    for suffix in ("/versions", "/submit"):
        assert client.post(f"/api/scenarios/{sid}{suffix}", headers=AUTHOR).status_code == 404
    for a_id, b_id in ((sid, other["id"]), (other["id"], sid)):
        assert client.post("/api/scenarios/compare", json={"a_id": a_id, "b_id": b_id}).status_code == 404
    assert [item["id"] for item in client.get("/api/scenarios").json()] == [other["id"]]


def test_deleted_versions_are_hidden_without_reusing_version_numbers(
    client: TestClient, design_id: str,
) -> None:
    base = save_scenario(client, design_id)
    v2 = client.post(f"/api/scenarios/{base['id']}/versions", headers=AUTHOR).json()
    assert v2["version"] == 2
    assert client.delete(f"/api/scenarios/{v2['id']}", headers=AUTHOR).status_code == 204
    versions = client.get(f"/api/scenarios/{base['id']}/versions").json()
    assert [item["version"] for item in versions] == [1]
    latest = client.get("/api/scenarios", params={"latest_only": True}).json()
    assert [item["id"] for item in latest] == [base["id"]]
    v3_response = client.post(f"/api/scenarios/{base['id']}/versions", headers=AUTHOR)
    assert v3_response.status_code == 201, v3_response.text
    v3 = v3_response.json()
    assert v3["version"] == 3 and v3["lineage_id"] == base["id"]
    # Removing a parent keeps its child accessible and its historical relationship intact.
    assert client.delete(f"/api/scenarios/{base['id']}", headers=AUTHOR).status_code == 204
    assert client.get(f"/api/scenarios/{v3['id']}").json()["parent_id"] == base["id"]
    versions = client.get(f"/api/scenarios/{v3['id']}/versions").json()
    assert [item["version"] for item in versions] == [3]

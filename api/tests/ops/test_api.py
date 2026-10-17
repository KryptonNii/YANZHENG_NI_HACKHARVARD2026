from __future__ import annotations

import asyncio
import json

import pytest

from trialpilot_api.ops import audit
from trialpilot_api.ops.fixtures import load_demo_design
from trialpilot_api.ops.router import stream_messages
from trialpilot_api.ops.store import OpsError, TrialState

AUTHOR = {"X-User": "alex.author", "X-Role": "author"}
VIEWER = {"X-User": "val.viewer", "X-Role": "viewer"}
BASE = "/api/ops/demo-40"
pytestmark = pytest.mark.req("URS-012")


def test_ops_end_to_end_with_real_a7_audit(client):
    assert client.get("/api/health").json()["modules"]["ops"]["status"] == "mounted"
    assert client.get(BASE + "/health").status_code == 404
    r = client.post(BASE + "/simulate", json={"seed": 42, "speed": 0}, headers=AUTHOR)
    assert r.status_code == 200, r.text
    assert r.json()["simulated"] is True
    h = client.get(BASE + "/health").json()
    assert len(h["kpis"]) == 14
    st = client.app.state.ops_trials["demo-40"]
    alerts = client.get(BASE + "/alerts").json()["items"]
    a = next(x for x in alerts if x["kind"] == "drug_overstock" and x["status"] == "open")
    aid = a["id"]
    assert client.get(BASE + "/alerts/" + aid).json()["provenance"]
    r = client.post(BASE + "/alerts/" + aid, json={"status": "acknowledged"}, headers=AUTHOR)
    assert r.status_code == 200
    r = client.post(BASE + "/interventions", headers=AUTHOR,
                    json={"alert_id": aid, "action": "supply_on_demand", "owner": "alex.author"})
    assert r.status_code == 201, r.text
    iv = r.json()
    assert iv["target_site_ids"] == [a["site_id"]]
    assert client.get(BASE + "/interventions/" + iv["id"]).status_code == 200
    before = [st.to_ops_event(e).model_dump(mode="json") for e in st.events if e.t < st.clock_day]
    r = client.post(BASE + "/interventions/" + iv["id"], headers=AUTHOR, json={"status": "in_progress"})
    assert r.status_code == 200, r.text
    after = [st.to_ops_event(e).model_dump(mode="json") for e in st.events if e.t < st.clock_day]
    assert before == after
    r = client.post(BASE + "/clock", headers=AUTHOR, json={"advance_days": 42})
    assert r.status_code == 200, r.text
    assert r.json()["clock_day"] == 448
    assert r.json()["new_events"] > 0
    assert client.get(BASE + "/effects").json()["items"]
    assert client.get(BASE + "/effects/" + iv["id"]).json()["bootstrap_draws"] == 1000
    events = client.get(BASE + "/events?limit=5").json()["items"]
    assert len(events) == 5 and all(e["simulated"] for e in events)
    assert [e["occurred_at"] for e in events] == sorted(e["occurred_at"] for e in events)
    assert client.get(BASE + "/actions").json()["items"]
    r = client.get("/api/audit", params={"action": "ops.", "limit": 1000})
    assert r.status_code == 200, r.text
    actions = {e["action"] for e in r.json()["items"]}
    assert {"ops.simulate", "ops.alert.status", "ops.intervention.create",
            "ops.intervention.update", "ops.clock.advance"} <= actions
    assert client.get("/api/audit/verify").json()["ok"]
    keys = [st.alert_meta[a.id]["key"] for a in st.alert_list()
            if a.status in {"open", "acknowledged", "action_planned"}]
    assert len(keys) == len(set(keys))


@pytest.mark.parametrize("payload", [
    {"seed": -1}, {"speed": -1}, {"speed": 31}, {"horizon_days": 10},
    {"start_day": 600}, {"unknown": True}, {"scenario": "fiction"},
])
def test_invalid_simulation_input(client, payload):
    r = client.post(BASE + "/simulate", json=payload, headers=AUTHOR)
    assert r.status_code == 422
    assert {"error", "message", "details"} <= r.json().keys()


def test_identity_and_registered_role_required(client):
    assert client.post(BASE + "/simulate", json={}).status_code == 401
    assert client.post(BASE + "/simulate", json={}, headers=VIEWER).status_code == 403
    assert client.post(BASE + "/simulate", json={}, headers={**AUTHOR, "X-Role": "admin"}).status_code == 403
    assert not hasattr(client.app.state, "ops_trials")


def test_stored_design_is_used_and_apps_are_isolated(make_client):
    a, b = make_client(), make_client()
    assert a.post("/api/ops/missing/simulate", json={}, headers=AUTHOR).status_code == 404
    a.post(BASE + "/simulate", json={"start_day": 0}, headers=AUTHOR).raise_for_status()
    assert b.get(BASE + "/health").status_code == 404
    design = a.app.state.ops_trials["demo-40"].plan.design.model_dump(mode="json")
    design["id"] = "stored-ops-design"
    a.post("/api/designs", json=design, headers=AUTHOR).raise_for_status()
    a.post("/api/ops/stored-ops-design/simulate", json={"start_day": 0}, headers=AUTHOR).raise_for_status()
    assert a.app.state.ops_trials["stored-ops-design"].plan.design.id == "stored-ops-design"


def test_crud_failures_and_audit_failure_leave_state_unchanged(client):
    client.post(BASE + "/simulate", json={}, headers=AUTHOR).raise_for_status()
    st = client.app.state.ops_trials["demo-40"]
    body = {"action": "feasibility_call", "target_site_ids": ["S14"],
            "metric": "enrollment_rate_per_month"}
    iv = client.post(BASE + "/interventions", json=body, headers=AUTHOR).json()
    path = BASE + "/interventions/" + iv["id"]
    assert client.patch(path, json={"target_site_ids": ["missing"]}, headers=AUTHOR).status_code == 422
    assert client.get(path).json() == iv
    assert client.delete(path, headers=AUTHOR).status_code == 422
    assert client.delete(path + "?reason=duplicate", headers=AUTHOR).status_code == 204
    assert client.get(path).status_code == 404
    assert client.post(BASE + "/clock", json={"advance_days": -1}, headers=AUTHOR).status_code == 422
    before = dict(st.interventions)
    sink = st.audit_sink
    def fail(**kwargs):
        raise RuntimeError("test audit unavailable")
    st.audit_sink = fail
    with pytest.raises(RuntimeError, match="audit unavailable"):
        st.create_intervention(body, "tester", "author")
    assert st.interventions == before
    st.audit_sink = sink
    started = st.create_intervention({**body, "status": "in_progress"}, "tester", "author")
    with pytest.raises(OpsError, match="return to planned"):
        st.update_intervention(started.id, {"status": "planned"}, "tester", "author")


def test_ops_audit_requires_a_bound_sink():
    """No silent fallback: without a bound sink an ops mutation cannot be audited, so it fails."""
    entry = {"actor": "alex.author", "role": "author", "action": "ops.x", "object_type": "ops_trial",
             "object_id": "t"}
    with pytest.raises(RuntimeError, match="not bound"):
        audit.append(**entry)
    with pytest.raises(TypeError, match="audit_sink"):
        TrialState("t", load_demo_design(), None, 42, 0, "demo", 0, 600)  # type: ignore[call-arg]
    seen = []

    def sink(actor, role, action, object_type, object_id, before_hash, after_hash, reason=None):
        seen.append((actor, role, action, object_type, object_id, before_hash, after_hash, reason))
        return "entry"

    with audit.bound(sink):
        assert audit.append(**{**entry, "role": "owner"}, after={"a": 1}, reason="why") == "entry"
    assert seen == [("alex.author", "viewer", "ops.x", "ops_trial", "t", None, audit.record_hash({"a": 1}),
                     "why")]


@pytest.mark.req("URS-015")
def test_sse_replay_all_message_types_and_reconnect_cursor(client):
    client.post(BASE + "/simulate", json={"start_day": 0}, headers=AUTHOR).raise_for_status()
    st = client.app.state.ops_trials["demo-40"]
    client.post(BASE + "/clock", json={"advance_days": 365}, headers=AUTHOR).raise_for_status()
    client.post(BASE + "/clock", json={"advance_days": 42}, headers=AUTHOR).raise_for_status()
    kinds = {kind for _, kind, _ in st.outbox}
    assert {"ops_event", "alert_new", "alert_update", "effect_update"} <= kinds
    async def read_replay():
        cursor = f"{st.run_id}:{st.last_seq - 2}"
        stream = stream_messages(st, cursor)
        try:
            messages = [await anext(stream), await anext(stream)]
            assert [m.seq for m in messages] == [st.last_seq - 1, st.last_seq]
            assert messages[0].to_sse().encode().startswith(b"id: ")
            assert json.loads(messages[0].to_sse().data) is not None
        finally:
            await stream.aclose()
    asyncio.run(read_replay())
    assert client.get(BASE + "/stream", headers={"Last-Event-ID": "old:1"}).status_code == 409
    assert client.get(BASE + "/stream?last_event_id=bad").status_code == 400

"""Approval workflow: segregation of duties, order, record binding, every action audited."""

from __future__ import annotations

from pathlib import Path

import pytest

from trialpilot_api.compliance import audit, records, store, workflow
from trialpilot_api.compliance.errors import ComplianceError
from trialpilot_api.compliance.hashing import file_sha256, sha256_hex

from .conftest import PINS

H = sha256_hex("scenario B v1")


def _err(fn, *a, **kw) -> ComplianceError:  # type: ignore[no-untyped-def]
    with pytest.raises(ComplianceError) as ei:
        fn(*a, **kw)
    return ei.value


def _submit() -> str:
    return workflow.create_request("scenario", "scenario-b", "alex.author", record_hash=H).id


@pytest.mark.req("URS-021", "URS-022")
def test_demo_flow_self_approval_blocked_then_review_then_qa_approval(db: store.Store) -> None:
    rid = _submit()
    e = _err(workflow.sign_request, rid, "alex.author", PINS["alex.author"], "approved")
    assert (e.status, e.code) == (403, "self_approval_forbidden")
    e = _err(workflow.sign_request, rid, "alex.author", PINS["alex.author"], "reviewed")
    assert (e.status, e.code) == (403, "self_approval_forbidden")
    e = _err(workflow.sign_request, rid, "sam.qa", PINS["sam.qa"], "approved")
    assert (e.status, e.code) == (409, "out_of_order")
    assert e.details["next_meaning"] == "reviewed"

    req = workflow.sign_request(rid, "riley.reviewer", PINS["riley.reviewer"], "reviewed")
    assert req.status == "pending" and [s.meaning for s in req.signatures] == ["reviewed"]
    req = workflow.sign_request(rid, "sam.qa", PINS["sam.qa"], "approved")
    assert req.status == "approved"
    assert [(s.signer, s.meaning) for s in req.signatures] == [
        ("riley.reviewer", "reviewed"), ("sam.qa", "approved")]
    assert all(s.record_hash == H for s in req.signatures)
    assert audit.verify_chain()["ok"] is True


@pytest.mark.req("URS-015", "URS-021")
def test_every_action_including_denials_is_audited(db: store.Store) -> None:
    rid = _submit()
    _err(workflow.sign_request, rid, "alex.author", PINS["alex.author"], "approved")
    workflow.sign_request(rid, "riley.reviewer", PINS["riley.reviewer"], "reviewed")
    workflow.sign_request(rid, "sam.qa", PINS["sam.qa"], "approved")
    items, _ = audit.list_entries(limit=100, newest_first=False)
    actions = [(e.actor, e.action, e.reason) for e in items]
    assert actions[0][:2] == ("alex.author", "approval.submit")
    assert ("alex.author", "approval.sign_denied", "self_approval_forbidden") in actions
    assert sum(1 for a in actions if a[1] == "signature.create") == 2
    assert actions[-1][:2] == ("sam.qa", "approval.approve")


@pytest.mark.req("URS-022")
def test_one_signer_per_step_and_qa_only_final_approval(db: store.Store) -> None:
    rid = _submit()
    workflow.sign_request(rid, "riley.reviewer", PINS["riley.reviewer"], "reviewed")
    e = _err(workflow.sign_request, rid, "riley.reviewer", PINS["riley.reviewer"], "approved")
    assert (e.status, e.code) == (403, "duplicate_signer")
    e = _err(workflow.sign_request, rid, "sam.qa", PINS["sam.qa"], "reviewed")
    assert (e.status, e.code) == (409, "already_signed")

    rid2 = workflow.create_request("change_record", "CR-1", "sam.qa", record_hash=H).id
    workflow.sign_request(rid2, "riley.reviewer", PINS["riley.reviewer"], "reviewed")
    e = _err(workflow.sign_request, rid2, "admin", PINS["admin"], "approved")
    assert (e.status, e.code) == (403, "role_not_permitted")


@pytest.mark.req("URS-022")
def test_meaning_outside_workflow_rejected(db: store.Store) -> None:
    rid = _submit()
    e = _err(workflow.sign_request, rid, "sam.qa", PINS["sam.qa"], "executed")
    assert (e.status, e.code) == (422, "meaning_not_required")


@pytest.mark.req("URS-018")
def test_wrong_pin_in_workflow_is_401(db: store.Store) -> None:
    rid = _submit()
    e = _err(workflow.sign_request, rid, "riley.reviewer", "nope", "reviewed")
    assert (e.status, e.code) == (401, "invalid_credential")
    assert workflow.get_request(rid).signatures == []


@pytest.mark.req("URS-020", "URS-024")
def test_protocol_gate_follows_the_exact_file_version(db: store.Store, tmp_path: Path) -> None:
    doc = tmp_path / "OQ-protocol.md"
    doc.write_text("# OQ protocol\n- URS-015: test_append\n", encoding="utf-8")
    records.register_file("test_protocol", "OQ-001", doc)
    st = workflow.approval_status("test_protocol", "OQ-001")
    assert st["approved"] is False and "no approval request" in st["reason"]

    rid = workflow.create_request("test_protocol", "OQ-001", "alex.author").id
    assert workflow.get_request(rid).required_meanings == ["reviewed", "approved"]
    workflow.sign_request(rid, "riley.reviewer", PINS["riley.reviewer"], "reviewed")
    st = workflow.approval_status("test_protocol", "OQ-001")
    assert st["approved"] is False and st["next_meaning"] == "approved"
    workflow.sign_request(rid, "sam.qa", PINS["sam.qa"], "approved")
    assert workflow.approval_status("test_protocol", "OQ-001")["approved"] is True

    doc.write_text("# OQ protocol\n- URS-015: (test removed)\n", encoding="utf-8")
    st = workflow.approval_status("test_protocol", "OQ-001")
    assert st["approved"] is False and "changed after approval" in st["reason"]
    view = workflow.view(rid)
    assert view["record_changed"] is True
    assert [s["valid"] for s in view["signatures"]] == [False, False]


@pytest.mark.req("URS-020")
def test_cannot_sign_a_record_that_changed_since_submission(db: store.Store,
                                                            tmp_path: Path) -> None:
    doc = tmp_path / "report.md"
    doc.write_text("summary v1", encoding="utf-8")
    records.register_file("validation_report", "VSR-1", doc)
    rid = workflow.create_request("validation_report", "VSR-1", "alex.author").id
    assert workflow.view(rid)["record_hash"] == file_sha256(doc)
    doc.write_text("summary v2", encoding="utf-8")
    e = _err(workflow.sign_request, rid, "sam.qa", PINS["sam.qa"], "approved")
    assert (e.status, e.code) == (409, "record_changed")


@pytest.mark.req("URS-021")
@pytest.mark.parametrize("author", ["alex.author", "riley.reviewer", "sam.qa"])
def test_no_role_is_exempt_from_segregation_of_duties(db: store.Store, author: str) -> None:
    rid = workflow.create_request("change_record", f"CR-{author}", author, record_hash=H).id
    for meaning in ("reviewed", "approved"):
        e = _err(workflow.sign_request, rid, author, PINS[author], meaning)
        assert (e.status, e.code) == (403, "self_approval_forbidden"), (author, meaning)
    assert workflow.get_request(rid).signatures == []


@pytest.mark.req("URS-021")
def test_reject_needs_reason_and_non_author(db: store.Store) -> None:
    rid = _submit()
    e = _err(workflow.reject_request, rid, "sam.qa", PINS["sam.qa"], "  ")
    assert (e.status, e.code) == (422, "reason_required")
    e = _err(workflow.reject_request, rid, "alex.author", PINS["alex.author"], "meh")
    assert (e.status, e.code) == (403, "self_approval_forbidden")
    req = workflow.reject_request(rid, "riley.reviewer", PINS["riley.reviewer"],
                                  "travel distances look wrong")
    assert req.status == "rejected"
    e = _err(workflow.sign_request, rid, "sam.qa", PINS["sam.qa"], "reviewed")
    assert (e.status, e.code) == (409, "request_closed")
    assert workflow.view(rid)["reject_reason"] == "travel distances look wrong"


@pytest.mark.req("URS-023")
def test_submission_permissions(db: store.Store) -> None:
    e = _err(workflow.create_request, "scenario", "s", "val.viewer", record_hash=H)
    assert (e.status, e.code) == (403, "role_not_permitted")
    e = _err(workflow.create_request, "scenario", "s", "mallory", record_hash=H)
    assert (e.status, e.code) == (403, "unknown_user")
    e = _err(workflow.create_request, "scenario", "s", "", record_hash=H)
    assert (e.status, e.code) == (401, "identity_required")
    e = _err(workflow.create_request, "invoice", "s", "alex.author", record_hash=H)
    assert e.code == "invalid_record_type"


@pytest.mark.req("URS-022")
def test_one_pending_request_per_record(db: store.Store) -> None:
    rid = _submit()
    e = _err(workflow.create_request, "scenario", "scenario-b", "alex.author", record_hash=H)
    assert (e.status, e.code) == (409, "already_pending")
    assert e.details["approval_id"] == rid


@pytest.mark.req("URS-022")
def test_validation_report_needs_only_qa_approval(db: store.Store) -> None:
    rid = workflow.create_request("validation_report", "VSR-2", "alex.author", record_hash=H).id
    e = _err(workflow.sign_request, rid, "riley.reviewer", PINS["riley.reviewer"], "approved")
    assert (e.status, e.code) == (403, "role_not_permitted")
    assert workflow.sign_request(rid, "sam.qa", PINS["sam.qa"], "approved").status == "approved"

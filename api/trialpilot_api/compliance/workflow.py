"""Approval workflow: `ApprovalRequest` lifecycle with segregation of duties enforced in code.

Rules (each one has a test in api/tests/compliance and a URS in validation/requirements.yaml):
- required meanings per record type, signed strictly in order (else 409 `out_of_order`);
- the author can never sign `reviewed`/`approved` on their own record (403 `self_approval_forbidden`);
- one person signs at most one meaning per request (403 `duplicate_signer`);
- the final `approved` signature needs an approver role (QA);
- a record that changed since submission cannot be signed (409 `record_changed`);
- every action — including denied attempts — is written to the audit trail.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from . import audit, esign, records, roles
from ._contracts import APPROVAL_RECORD_TYPES, ApprovalRequest, Signature
from .errors import ComplianceError
from .hashing import iso_utc, now
from .store import Store, get_store

REQUIRED_MEANINGS: dict[str, list[str]] = {
    "scenario": ["reviewed", "approved"],
    "test_protocol": ["reviewed", "approved"],  # must be approved before tpv execute runs
    "validation_report": ["approved"],  # QA approval
    "change_record": ["reviewed", "approved"],
}

SOD_MEANINGS = frozenset({"reviewed", "approved"})


def _load(request_id: str, st: Store) -> dict[str, Any]:
    row = st.query_one("SELECT * FROM approvals WHERE id = ?", (request_id,))
    if row is None:
        raise ComplianceError(404, "approval_not_found", f"No approval request {request_id!r}.")
    return dict(row)


def _to_model(row: dict[str, Any], st: Store) -> ApprovalRequest:
    sigs = esign.list_signatures(approval_id=row["id"], store=st)
    return ApprovalRequest(
        id=row["id"],
        record_type=row["record_type"],
        record_id=row["record_id"],
        author=row["author"],
        required_meanings=json.loads(row["required_meanings"]),
        status=row["status"],
        signatures=sigs,
    )


def _next_meaning(required: list[str], sigs: list[Signature]) -> str | None:
    done = {s.meaning for s in sigs}
    for m in required:
        if m not in done:
            return m
    return None


def view(request_id: str, *, store: Store | None = None) -> dict[str, Any]:
    """ApprovalRequest + record hash, signature validity/manifestation, next meaning."""
    st = store or get_store()
    row = _load(request_id, st)
    return _view_row(row, st)


def _view_row(row: dict[str, Any], st: Store) -> dict[str, Any]:
    model = _to_model(row, st)
    current = records.current_hash(row["record_type"], row["record_id"], store=st)
    data = model.model_dump(mode="json")
    data["signatures"] = [esign.signature_view(s, current=current, store=st)
                          for s in model.signatures]
    data["record_hash"] = row["record_hash"]
    data["current_record_hash"] = current
    data["record_changed"] = current is not None and current != row["record_hash"]
    data["title"] = row.get("title")
    data["created_at"] = row["created_at"]
    data["closed_at"] = row["closed_at"]
    data["closed_by"] = row["closed_by"]
    data["reject_reason"] = row["reject_reason"]
    data["author_name"] = esign.display_name(row["author"], st)
    data["next_meaning"] = (
        _next_meaning(model.required_meanings, model.signatures)
        if model.status == "pending" else None
    )
    return data


def create_request(
    record_type: str,
    record_id: str,
    author: str,
    *,
    record_hash: str | None = None,
    reason: str | None = None,
    title: str | None = None,
    store: Store | None = None,
) -> ApprovalRequest:
    """Submit a record for approval. `record_hash` defaults to the record owner's current hash."""
    st = store or get_store()
    if record_type not in APPROVAL_RECORD_TYPES:
        raise ComplianceError(422, "invalid_record_type", f"Unknown record type {record_type!r}.",
                              {"allowed": list(APPROVAL_RECORD_TYPES)})
    if not record_id:
        raise ComplianceError(422, "invalid_record_id", "record_id is required.")
    user = roles.require_user(author, st)
    if not roles.can(user.role, "approval.submit"):
        audit.append(user.username, user.role, "approval.submit_denied", record_type, record_id,
                     None, None, f"role {user.role} may not submit records", store=st)
        raise ComplianceError(403, "role_not_permitted",
                              f"Role {user.role!r} may not submit records for approval.")
    if record_hash is None:
        record_hash = records.current_hash(record_type, record_id, store=st)
        if record_hash is None:
            raise ComplianceError(422, "record_hash_required",
                                  "Could not resolve the record's current hash; send record_hash.")
    if len(record_hash) != 64:
        raise ComplianceError(422, "invalid_record_hash", "record_hash must be a sha256 hex digest.")
    pending = st.query_one(
        "SELECT id FROM approvals WHERE record_type = ? AND record_id = ? AND status = 'pending'",
        (record_type, record_id),
    )
    if pending is not None:
        raise ComplianceError(409, "already_pending",
                              "This record already has a pending approval request.",
                              {"approval_id": pending["id"]})
    req_id = str(uuid.uuid4())
    required = REQUIRED_MEANINGS[record_type]
    with st.tx() as conn:
        conn.execute(
            "INSERT INTO approvals (id, record_type, record_id, record_hash, author,"
            " required_meanings, status, created_at, title) VALUES (?,?,?,?,?,?,?,?,?)",
            (req_id, record_type, record_id, record_hash, user.username, json.dumps(required),
             "pending", iso_utc(now()), title),
        )
        audit.append(user.username, user.role, "approval.submit", "approval", req_id, None,
                     record_hash, reason or f"submitted {record_type}/{record_id} for approval",
                     store=st)
    return _to_model(_load(req_id, st), st)


def _deny(st: Store, user: roles.User, req: dict[str, Any], code: str, status: int,
          message: str, details: dict[str, Any] | None = None) -> ComplianceError:
    audit.append(user.username, user.role, "approval.sign_denied", "approval", req["id"], None,
                 None, code, store=st)
    return ComplianceError(status, code, message, details)


def sign_request(
    request_id: str,
    signer: str,
    credential: str,
    meaning: str,
    *,
    reason: str | None = None,
    store: Store | None = None,
) -> ApprovalRequest:
    st = store or get_store()
    req = _load(request_id, st)
    if req["status"] != "pending":
        raise ComplianceError(409, "request_closed",
                              f"This request is already {req['status']}.")
    user = esign.reauthenticate(signer, credential, store=st)
    required: list[str] = json.loads(req["required_meanings"])
    sigs = esign.list_signatures(approval_id=request_id, store=st)

    if meaning in SOD_MEANINGS and user.username == req["author"]:
        raise _deny(st, user, req, "self_approval_forbidden", 403,
                    "Authors can't review or approve their own work.")
    if meaning not in required:
        raise _deny(st, user, req, "meaning_not_required", 422,
                    f"'{meaning}' is not part of this request's workflow.",
                    {"required_meanings": required})
    if any(s.meaning == meaning for s in sigs):
        raise _deny(st, user, req, "already_signed", 409, f"'{meaning}' has already been signed.")
    nxt = _next_meaning(required, sigs)
    if meaning != nxt:
        raise _deny(st, user, req, "out_of_order", 409,
                    f"'{nxt}' must be signed before '{meaning}'.",
                    {"next_meaning": nxt, "required_meanings": required})
    if any(s.signer == user.username for s in sigs):
        raise _deny(st, user, req, "duplicate_signer", 403,
                    "One person can sign only one step of a request (segregation of duties).")
    if not roles.can(user.role, f"sign.{meaning}") or (
        meaning == "approved"
        and user.role not in roles.APPROVER_ROLES.get(req["record_type"], frozenset())
    ):
        raise _deny(st, user, req, "role_not_permitted", 403,
                    f"Role {user.role!r} may not sign '{meaning}' on a {req['record_type']}.")
    current = records.current_hash(req["record_type"], req["record_id"], store=st)
    if current is not None and current != req["record_hash"]:
        raise _deny(st, user, req, "record_changed", 409,
                    "The record changed after it was submitted; submit the new version.",
                    {"submitted_hash": req["record_hash"], "current_hash": current})

    with st.tx() as conn:
        esign.record_signature(user, meaning, req["record_type"], req["record_id"],
                               req["record_hash"], approval_id=request_id, reason=reason, store=st)
        audit.append(user.username, user.role, "approval.sign", "approval", request_id,
                     req["record_hash"], req["record_hash"], reason or meaning, store=st)
        if _next_meaning(required, esign.list_signatures(approval_id=request_id, store=st)) is None:
            conn.execute(
                "UPDATE approvals SET status = 'approved', closed_at = ?, closed_by = ?"
                " WHERE id = ?",
                (iso_utc(now()), user.username, request_id),
            )
            audit.append(user.username, user.role, "approval.approve", "approval", request_id,
                         req["record_hash"], req["record_hash"],
                         f"all required signatures present: {', '.join(required)}", store=st)
    return _to_model(_load(request_id, st), st)


def reject_request(
    request_id: str,
    signer: str,
    credential: str,
    reason: str,
    *,
    store: Store | None = None,
) -> ApprovalRequest:
    st = store or get_store()
    if not reason or not reason.strip():
        raise ComplianceError(422, "reason_required", "A rejection needs a reason.")
    req = _load(request_id, st)
    if req["status"] != "pending":
        raise ComplianceError(409, "request_closed", f"This request is already {req['status']}.")
    user = esign.reauthenticate(signer, credential, store=st)
    if user.username == req["author"]:
        raise _deny(st, user, req, "self_approval_forbidden", 403,
                    "Authors can't review or reject their own work.")
    if not roles.can(user.role, "approval.reject"):
        raise _deny(st, user, req, "role_not_permitted", 403,
                    f"Role {user.role!r} may not reject approval requests.")
    with st.tx() as conn:
        conn.execute(
            "UPDATE approvals SET status = 'rejected', closed_at = ?, closed_by = ?,"
            " reject_reason = ? WHERE id = ?",
            (iso_utc(now()), user.username, reason, request_id),
        )
        audit.append(user.username, user.role, "approval.reject", "approval", request_id,
                     req["record_hash"], req["record_hash"], reason, store=st)
    return _to_model(_load(request_id, st), st)


def get_request(request_id: str, *, store: Store | None = None) -> ApprovalRequest:
    st = store or get_store()
    return _to_model(_load(request_id, st), st)


def list_views(
    *,
    status: str | None = None,
    record_type: str | None = None,
    record_id: str | None = None,
    store: Store | None = None,
) -> list[dict[str, Any]]:
    st = store or get_store()
    clauses, params = [], []
    for col, val in (("status", status), ("record_type", record_type), ("record_id", record_id)):
        if val:
            clauses.append(f"{col} = ?")
            params.append(val)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = st.query(f"SELECT * FROM approvals{where} ORDER BY created_at DESC, rowid DESC", params)
    return [_view_row(dict(r), st) for r in rows]


def approval_status(
    record_type: str, record_id: str, *, record_hash: str | None = None,
    store: Store | None = None,
) -> dict[str, Any]:
    """Is this exact record version approved, with every signature still valid?

    Returns `{approved, approval_id, reason, signatures}` — used by `tpv execute` (protocol gate)
    and `tpv report` (QA sign-off status).
    """
    st = store or get_store()
    current = record_hash or records.current_hash(record_type, record_id, store=st)
    rows = st.query(
        "SELECT * FROM approvals WHERE record_type = ? AND record_id = ?"
        " ORDER BY created_at DESC, rowid DESC",
        (record_type, record_id),
    )
    if not rows:
        return {"approved": False, "approval_id": None, "status": None,
                "reason": f"no approval request exists for {record_type}/{record_id}",
                "signatures": []}
    latest = dict(rows[0])
    v = _view_row(latest, st)
    if latest["status"] != "approved":
        return {"approved": False, "approval_id": latest["id"], "status": latest["status"],
                "reason": f"approval request is {latest['status']}", "signatures": v["signatures"],
                "next_meaning": v["next_meaning"]}
    if current is None or current != latest["record_hash"]:
        return {"approved": False, "approval_id": latest["id"], "status": "approved",
                "reason": "the record changed after approval (signatures no longer valid)",
                "signatures": v["signatures"]}
    return {"approved": True, "approval_id": latest["id"], "status": "approved", "reason": None,
            "signatures": v["signatures"]}

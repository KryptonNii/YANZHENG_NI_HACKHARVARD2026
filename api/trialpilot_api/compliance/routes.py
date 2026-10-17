"""FastAPI routes for `/api/audit`, `/api/approvals`, `/api/signatures`, `/api/compliance`,
`/api/validation`. Paths are absolute: mount with `app.include_router(router)` (no prefix).

Identity: `X-User` header names the acting user (demo identity only); the role comes from the
compliance user registry, never from the request. Signing additionally re-checks the PIN.
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from . import audit, esign, records, roles, workflow
from .config import validation_out_dir
from .errors import ComplianceError
from .hashing import fs_path

router = APIRouter(tags=["compliance"])


def error_response(exc: ComplianceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.to_dict())


async def compliance_error_handler(_request: Request, exc: Exception) -> Response:
    """Register app-wide: `app.add_exception_handler(ComplianceError, compliance_error_handler)`."""
    assert isinstance(exc, ComplianceError)
    return error_response(exc)


# ---- audit ---------------------------------------------------------------------------------------


@router.get("/api/audit")
def get_audit(
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    actor: str | None = None,
    action: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    order: Literal["desc", "asc"] = "desc",
) -> Any:
    items, total = audit.list_entries(
        limit=limit, offset=offset, actor=actor, action=action, object_type=object_type,
        object_id=object_id, newest_first=(order == "desc"),
    )
    return {"items": [e.model_dump(mode="json") for e in items], "total": total,
            "limit": limit, "offset": offset}


@router.get("/api/audit/verify")
def get_audit_verify() -> Any:
    return audit.verify_chain()


@router.get("/api/audit/export.csv")
def get_audit_export(
    actor: str | None = None,
    action: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
) -> Any:
    body = audit.export_csv(actor=actor, action=action, object_type=object_type,
                            object_id=object_id)
    return PlainTextResponse(
        body, media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit_trail.csv"'},
    )


# ---- approvals -----------------------------------------------------------------------------------


class ApprovalCreate(BaseModel):
    record_type: Literal["scenario", "test_protocol", "validation_report", "change_record"]
    record_id: str = Field(min_length=1)
    record_hash: str | None = None
    reason: str | None = None
    title: str | None = None


class SignBody(BaseModel):
    meaning: Literal["authored", "reviewed", "approved", "executed", "verified"]
    pin: str = Field(min_length=1, description="Re-authentication at signing (demo PIN)")
    reason: str | None = None


class RejectBody(BaseModel):
    pin: str = Field(min_length=1)
    reason: str = Field(min_length=1)


@router.get("/api/approvals")
def get_approvals(
    status: Literal["pending", "approved", "rejected"] | None = None,
    record_type: str | None = None,
    record_id: str | None = None,
) -> Any:
    return {"items": workflow.list_views(
        status=status, record_type=record_type, record_id=record_id)}


# Mutations check identity in the handler body, not as a dependency: FastAPI resolves dependencies
# before it validates the body, and a malformed body must stay a 422 even without X-User.


@router.post("/api/approvals", status_code=201)
def post_approval(body: ApprovalCreate, x_user: str | None = Header(None)) -> Any:
    author = roles.require_identity(x_user)
    if body.record_type == "scenario" and records.current_hash("scenario", body.record_id):
        # A saved scenario is submitted through its own route, which freezes the row first.
        # Approving it here would leave the draft editable and its signatures invalid.
        raise ComplianceError(
            409, "submit_via_scenario",
            "Submit a saved scenario with POST /api/scenarios/{id}/submit, which freezes it "
            "for review.",
            {"record_id": body.record_id,
             "submit_path": f"/api/scenarios/{body.record_id}/submit"},
        )
    req = workflow.create_request(
        body.record_type, body.record_id, author, record_hash=body.record_hash,
        reason=body.reason, title=body.title,
    )
    return workflow.view(req.id)


@router.get("/api/approvals/{approval_id}")
def get_approval(approval_id: str) -> Any:
    return workflow.view(approval_id)


@router.post("/api/approvals/{approval_id}/sign")
def post_sign(approval_id: str, body: SignBody, x_user: str | None = Header(None)) -> Any:
    signer = roles.require_identity(x_user)
    workflow.sign_request(approval_id, signer, body.pin, body.meaning, reason=body.reason)
    return workflow.view(approval_id)


@router.post("/api/approvals/{approval_id}/reject")
def post_reject(approval_id: str, body: RejectBody, x_user: str | None = Header(None)) -> Any:
    signer = roles.require_identity(x_user)
    workflow.reject_request(approval_id, signer, body.pin, body.reason)
    return workflow.view(approval_id)


# ---- signatures, users, roles --------------------------------------------------------------------


@router.get("/api/signatures")
def get_signatures(record_type: str | None = None, record_id: str | None = None) -> Any:
    return {"items": [
        esign.signature_view(s)
        for s in esign.list_signatures(record_type=record_type, record_id=record_id)
    ]}


@router.get("/api/compliance/users")
def get_users() -> Any:
    return {"items": [
        {"username": u.username, "display_name": u.display_name, "role": u.role}
        for u in roles.list_users()
    ], "note": "Demo identities. Send the acting user as the X-User header."}


@router.get("/api/compliance/roles")
def get_roles() -> Any:
    return {"permissions": roles.permission_matrix(),
            "required_meanings": workflow.REQUIRED_MEANINGS,
            "approver_roles": {k: sorted(v) for k, v in roles.APPROVER_ROLES.items()}}


# ---- validation package --------------------------------------------------------------------------


def _package_dir() -> Path:
    return validation_out_dir() / "package"


def _live_status(build_status: str, st: dict[str, Any]) -> str:
    """Deliverable label from the live approval `st` (`workflow.approval_status`).

    `tpv package` labels a deliverable "approved" / "awaiting approval" from the approval at build
    time; those labels follow the live approval, so a deliverable never shows "approved" without a
    valid one. Other build labels (draft, generated, ...) are kept unless the record is approved.
    """
    if st["approved"]:
        return "approved"
    if build_status not in ("approved", "awaiting approval"):
        return build_status
    if st["status"] == "pending":
        return "awaiting approval"
    if st["status"] == "rejected":
        return "rejected"
    if st["status"] == "approved":
        return "approval invalid"  # approved, then the record changed
    # No approval request in this store (e.g. the package was built against another database).
    return "approval unconfirmed" if build_status == "approved" else build_status


@router.get("/api/validation/package")
def get_validation_package() -> Any:
    index = fs_path(_package_dir() / "package_index.json")
    if not index.is_file():
        raise ComplianceError(
            404, "package_not_built",
            "No validation package has been generated yet. Run `tpv package`.",
            {
                "expected_path": "validation/out/package/package_index.json",
                "resolved_path": str(index),
                "config": (
                    "TP_VALIDATION_OUT, else validation/out/served_output.txt, "
                    "else validation/out"
                ),
            },
        )
    data = json.loads(index.read_text(encoding="utf-8"))
    # Approval status is live (QA may sign, or the record may change, after the package was built).
    try:
        for d in data.get("deliverables", []):
            rt, rid = d.get("approval_record_type"), d.get("approval_record_id")
            if rt and rid:
                st = workflow.approval_status(rt, rid)
                d["approval"] = {k: st.get(k) for k in ("approved", "approval_id", "status",
                                                         "reason")}
                d["status"] = _live_status(d.get("status", "draft"), st)
        report = data.get("report")
        if isinstance(report, dict) and report.get("record_id"):
            _refresh_report(report, workflow.report_approval(report["record_id"]))
    except ComplianceError:
        pass
    return data


def _refresh_report(report: dict[str, Any], live: dict[str, Any]) -> None:
    """Make the package's QA sign-off line follow the live approval, like the deliverables.

    With no approval request in this store (the package was built against another database),
    the build label stays, except that "approved" becomes "approval unconfirmed".
    """
    if live["approval_id"] is None:
        if report.get("status") == "approved":
            report["status"] = "approval unconfirmed"
        return
    for key in ("approval_id", "signatures", "qa_signature", "reason"):
        report.pop(key, None)
    report.update(live)


@router.get("/api/validation/package/files/{file_path:path}")
def get_validation_file(file_path: str) -> Any:
    base = _package_dir().resolve()
    target = (base / file_path).resolve()
    if base not in target.parents and target != base:
        raise ComplianceError(400, "invalid_path", "Path escapes the package.")
    target = fs_path(target)
    if not target.is_file():
        raise ComplianceError(404, "file_not_found", f"{file_path} not found.")
    media = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if target.suffix == ".md":
        media = "text/markdown; charset=utf-8"
    return FileResponse(target, media_type=media)

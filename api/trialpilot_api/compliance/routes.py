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

from . import audit, esign, roles, workflow
from .config import validation_out_dir
from .errors import ComplianceError

router = APIRouter(tags=["compliance"])


def error_response(exc: ComplianceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.to_dict())


async def compliance_error_handler(_request: Request, exc: Exception) -> Response:
    """Register app-wide: `app.add_exception_handler(ComplianceError, compliance_error_handler)`."""
    assert isinstance(exc, ComplianceError)
    return error_response(exc)


def _guard(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except ComplianceError as exc:
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
    def run() -> dict[str, Any]:
        items, total = audit.list_entries(
            limit=limit, offset=offset, actor=actor, action=action, object_type=object_type,
            object_id=object_id, newest_first=(order == "desc"),
        )
        return {"items": [e.model_dump(mode="json") for e in items], "total": total,
                "limit": limit, "offset": offset}

    return _guard(run)


@router.get("/api/audit/verify")
def get_audit_verify() -> Any:
    return _guard(audit.verify_chain)


@router.get("/api/audit/export.csv")
def get_audit_export(
    actor: str | None = None,
    action: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
) -> Any:
    def run() -> Response:
        body = audit.export_csv(actor=actor, action=action, object_type=object_type,
                                object_id=object_id)
        return PlainTextResponse(
            body, media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="audit_trail.csv"'},
        )

    return _guard(run)


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
    return _guard(lambda: {"items": workflow.list_views(
        status=status, record_type=record_type, record_id=record_id)})


@router.post("/api/approvals", status_code=201)
def post_approval(body: ApprovalCreate, x_user: str | None = Header(None)) -> Any:
    def run() -> Any:
        req = workflow.create_request(
            body.record_type, body.record_id, x_user or "", record_hash=body.record_hash,
            reason=body.reason, title=body.title,
        )
        return JSONResponse(status_code=201, content=workflow.view(req.id))

    if not x_user:
        return _guard(roles.require_user, None)
    return _guard(run)


@router.get("/api/approvals/{approval_id}")
def get_approval(approval_id: str) -> Any:
    return _guard(workflow.view, approval_id)


@router.post("/api/approvals/{approval_id}/sign")
def post_sign(approval_id: str, body: SignBody, x_user: str | None = Header(None)) -> Any:
    if not x_user:
        return _guard(roles.require_user, None)

    def run() -> Any:
        workflow.sign_request(approval_id, x_user, body.pin, body.meaning, reason=body.reason)
        return workflow.view(approval_id)

    return _guard(run)


@router.post("/api/approvals/{approval_id}/reject")
def post_reject(approval_id: str, body: RejectBody, x_user: str | None = Header(None)) -> Any:
    if not x_user:
        return _guard(roles.require_user, None)

    def run() -> Any:
        workflow.reject_request(approval_id, x_user, body.pin, body.reason)
        return workflow.view(approval_id)

    return _guard(run)


# ---- signatures, users, roles --------------------------------------------------------------------


@router.get("/api/signatures")
def get_signatures(record_type: str | None = None, record_id: str | None = None) -> Any:
    return _guard(lambda: {"items": [
        esign.signature_view(s)
        for s in esign.list_signatures(record_type=record_type, record_id=record_id)
    ]})


@router.get("/api/compliance/users")
def get_users() -> Any:
    return _guard(lambda: {"items": [
        {"username": u.username, "display_name": u.display_name, "role": u.role}
        for u in roles.list_users()
    ], "note": "Demo identities. Send the acting user as the X-User header."})


@router.get("/api/compliance/roles")
def get_roles() -> Any:
    return {"permissions": roles.permission_matrix(),
            "required_meanings": workflow.REQUIRED_MEANINGS,
            "approver_roles": {k: sorted(v) for k, v in roles.APPROVER_ROLES.items()}}


# ---- validation package --------------------------------------------------------------------------


def _package_dir() -> Path:
    return validation_out_dir() / "package"


@router.get("/api/validation/package")
def get_validation_package() -> Any:
    index = _package_dir() / "package_index.json"
    if not index.is_file():
        return error_response(ComplianceError(
            404, "package_not_built",
            "No validation package has been generated yet. Run `tpv package`.",
            {"expected_path": "validation/out/package/package_index.json"},
        ))
    data = json.loads(index.read_text(encoding="utf-8"))
    # Approval status is live (QA may sign after the package was generated).
    try:
        for d in data.get("deliverables", []):
            rt, rid = d.get("approval_record_type"), d.get("approval_record_id")
            if rt and rid:
                st = workflow.approval_status(rt, rid)
                d["approval"] = {k: st.get(k) for k in ("approved", "approval_id", "status",
                                                         "reason")}
                d["status"] = "approved" if st["approved"] else d.get("status", "draft")
    except ComplianceError:
        pass
    return data


@router.get("/api/validation/package/files/{file_path:path}")
def get_validation_file(file_path: str) -> Any:
    base = _package_dir().resolve()
    target = (base / file_path).resolve()
    if base not in target.parents and target != base:
        return error_response(ComplianceError(400, "invalid_path", "Path escapes the package."))
    if not target.is_file():
        return error_response(ComplianceError(404, "file_not_found", f"{file_path} not found."))
    media = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if target.suffix == ".md":
        media = "text/markdown; charset=utf-8"
    return FileResponse(target, media_type=media)

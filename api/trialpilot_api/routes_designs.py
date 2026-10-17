"""/api/designs — store trial designs (versioned, rows immutable).

POST the same id again with different content -> new version (audited); identical content -> 200,
no new version. GET returns the plain `TrialDesign` (version + hash in headers and in the list).
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Response
from pydantic import BaseModel, ValidationError
from sqlmodel import Session, col, func, select

from ._contracts import TrialDesign
from .db import DesignRow, get_session, utcnow_iso
from .deps import Identity, require_editor, services
from .errors import ApiError
from .hashing import canonical_json, sha256_hex

log = logging.getLogger("trialpilot.designs")
router = APIRouter(prefix="/api/designs", tags=["designs"])


class DesignSummary(BaseModel):
    id: str
    version: int
    title: str
    source: str
    registry_id: str | None
    phase: str | None
    enrollment_target: int
    duration_months: float
    site_count: int
    visit_count: int
    countries: list[str]
    drug_type: str
    missing_fields: list[str]
    design_hash: str
    created_at: str
    created_by: str


def _summary(row: DesignRow) -> DesignSummary:
    d = TrialDesign.model_validate_json(row.data)
    return DesignSummary(
        id=d.id, version=row.version, title=d.title, source=d.source, registry_id=d.registry_id,
        phase=d.phase, enrollment_target=d.enrollment_target, duration_months=d.duration_months,
        site_count=len(d.sites), visit_count=len(d.visits),
        countries=sorted({s.country for s in d.sites}), drug_type=d.drug_type,
        missing_fields=list(d.missing_fields), design_hash=row.design_hash,
        created_at=row.created_at, created_by=row.created_by,
    )


def latest_design_row(session: Session, design_id: str, version: int | None = None) -> DesignRow:
    q = select(DesignRow).where(DesignRow.design_id == design_id)
    q = q.where(DesignRow.version == version) if version is not None else q.order_by(
        col(DesignRow.version).desc())
    row = session.exec(q).first()
    if row is None:
        raise ApiError(404, "design_not_found",
                       f"No trial design with id {design_id!r}"
                       + (f" and version {version}." if version is not None else "."),
                       {"design_id": design_id, "version": version})
    return row


def load_design(
    session: Session, design_id: str, version: int | None = None
) -> tuple[DesignRow, TrialDesign]:
    row = latest_design_row(session, design_id, version)
    return row, TrialDesign.model_validate_json(row.data)


def _design_headers(response: Response, row: DesignRow) -> None:
    response.headers["X-Design-Version"] = str(row.version)
    response.headers["ETag"] = f'"{row.design_hash}"'


def store_design(
    svc: Any, session: Session, ident: Identity, design: TrialDesign, reason: str | None = None
) -> tuple[DesignRow, bool]:
    """Insert a new version unless the latest version has identical content. Returns
    (row, created)."""
    data = canonical_json(design)
    h = sha256_hex(data)
    prev = session.exec(
        select(DesignRow).where(DesignRow.design_id == design.id)
        .order_by(col(DesignRow.version).desc())
    ).first()
    if prev is not None and prev.design_hash == h:
        return prev, False
    row = DesignRow(
        design_id=design.id, version=(prev.version + 1) if prev else 1, title=design.title,
        source=design.source, registry_id=design.registry_id, design_hash=h, data=data,
        created_at=utcnow_iso(), created_by=ident.user,
    )
    action = "design.update" if prev else "design.create"

    def write(s: Session) -> DesignRow:
        s.add(row)
        s.flush()
        return row

    svc.audited_write(session, ident, action, "design", design.id,
                      prev.design_hash if prev else None, h, write, reason)
    session.refresh(row)
    return row, True


@router.get("", response_model=list[DesignSummary])
def list_designs(
    session: Session = Depends(get_session),
    source: str | None = Query(default=None, description="Filter by TrialDesign.source"),
) -> list[DesignSummary]:
    latest = (
        select(DesignRow.design_id, func.max(DesignRow.version).label("v"))
        .group_by(DesignRow.design_id).subquery()
    )
    rows = session.exec(
        select(DesignRow).join(
            latest, (DesignRow.design_id == latest.c.design_id) & (DesignRow.version == latest.c.v)
        ).order_by(col(DesignRow.created_at).desc())
    ).all()
    out = [_summary(r) for r in rows]
    return [s for s in out if source is None or s.source == source]


@router.post("", response_model=TrialDesign, status_code=201)
def create_design(
    response: Response,
    body: dict[str, Any] = Body(..., description="A TrialDesign; `id` is generated if omitted."),
    ident: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
    svc: Any = Depends(services),
) -> TrialDesign:
    payload = dict(body)
    payload.setdefault("id", str(uuid.uuid4()))
    try:
        design = TrialDesign.model_validate(payload)
    except ValidationError as exc:
        errors = [{"loc": [str(x) for x in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        first = errors[0]
        raise ApiError(422, "validation_error",
                       f"Invalid trial design: {'.'.join(first['loc'])}: {first['msg']}",
                       {"errors": errors}) from exc
    _check_design(design)
    row, created = store_design(svc, session, ident, design)
    if not created:
        response.status_code = 200
    response.headers["Location"] = f"/api/designs/{design.id}"
    _design_headers(response, row)
    return design


def _check_design(d: TrialDesign) -> None:
    problems = []
    if not d.id.strip() or "/" in d.id:
        problems.append("id must be non-empty and contain no '/'")
    if d.enrollment_target < 0:
        problems.append("enrollment_target must be >= 0")
    if d.duration_months <= 0:
        problems.append("duration_months must be > 0")
    for label, ids in (("site", [s.id for s in d.sites]), ("visit", [v.number for v in d.visits])):
        if len(ids) != len(set(ids)):
            problems.append(f"duplicate {label} ids/numbers")
    if problems:
        raise ApiError(422, "invalid_design", "Invalid trial design: " + "; ".join(problems),
                       {"problems": problems})


@router.get("/{design_id}", response_model=TrialDesign)
def get_design(
    design_id: str,
    response: Response,
    version: int | None = Query(default=None, ge=1),
    session: Session = Depends(get_session),
) -> TrialDesign:
    row, design = load_design(session, design_id, version)
    _design_headers(response, row)
    return design


@router.get("/{design_id}/versions", response_model=list[DesignSummary])
def design_versions(design_id: str, session: Session = Depends(get_session)) -> list[DesignSummary]:
    rows = session.exec(
        select(DesignRow).where(DesignRow.design_id == design_id).order_by(col(DesignRow.version))
    ).all()
    if not rows:
        raise ApiError(404, "design_not_found", f"No trial design with id {design_id!r}.",
                       {"design_id": design_id})
    return [_summary(r) for r in rows]


# ------------------------------------------------------------------------------------------
# Startup seeding from A4's fixtures (data/fixtures/trials/*.json)
# ------------------------------------------------------------------------------------------
def seed_fixture_designs(svc: Any, fixtures_dir: Path) -> list[str]:
    """Store every valid TrialDesign fixture that is not in the DB yet. Returns stored ids."""
    trials_dir = fixtures_dir / "trials"
    if not trials_dir.is_dir():
        return []
    stored: list[str] = []
    system = Identity(user="system.seed", role="admin")
    for f in sorted(trials_dir.glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("design"), dict):
                raw = raw["design"]
            design = TrialDesign.model_validate(raw)
        except Exception as exc:
            log.warning("skipping fixture design", extra={"file": f.name, "error": str(exc)[:200]})
            continue
        with Session(svc.db_engine) as s:
            exists = s.exec(select(DesignRow).where(DesignRow.design_id == design.id)).first()
            if exists is not None:
                continue
            store_design(svc, s, system, design, reason=f"seeded from fixture {f.name}")
            stored.append(design.id)
    return stored

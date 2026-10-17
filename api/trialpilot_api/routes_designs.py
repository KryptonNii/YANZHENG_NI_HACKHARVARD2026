"""/api/designs — store trial designs (versioned, rows immutable).

POST a new id creates version 1. POST the same id with identical content returns 200 and does
not mint a version. POST different content for an existing id is an update: it requires
`If-Match` equal to the current strong ETag (the design hash), and it cannot replace
`registry_id` or `source`. A missing or different tag is 409 `design_changed` and includes
the current version. GET returns the plain `TrialDesign` (version + hash in headers and in
the list).
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
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


def _strong_etags(header: str | None) -> list[str]:
    """Strong entity tags from an If-Match header. `*` and weak tags do not count."""
    if not header or not header.strip():
        return []
    found: list[str] = []
    for part in header.split(","):
        token = part.strip()
        if not token or token == "*" or token[:2].upper() == "W/":
            continue
        if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
            token = token[1:-1].strip()
        if token:
            found.append(token)
    return found


def _reject_identity_change(prev: DesignRow, design: TrialDesign) -> None:
    stored = TrialDesign.model_validate_json(prev.data)
    changed = [name for name, old, new in (
        ("registry_id", stored.registry_id, design.registry_id),
        ("source", stored.source, design.source),
    ) if old != new]
    if not changed:
        return
    raise ApiError(
        422, "design_identity_immutable",
        "registry_id and source identify where this design came from. An edit cannot replace "
        + " or ".join(changed) + ".",
        {
            "design_id": design.id, "fields": changed, "version": prev.version,
            "registry_id": stored.registry_id, "source": stored.source,
            "sent_registry_id": design.registry_id, "sent_source": design.source,
        },
    )


def _design_conflict(prev: DesignRow) -> ApiError:
    etag = f'"{prev.design_hash}"'
    return ApiError(
        409, "design_changed",
        f"Design {prev.design_id!r} is now version {prev.version}. Send If-Match with that "
        "version's ETag to store a new version. Do not reuse a stale body with the new tag.",
        {
            "design_id": prev.design_id, "version": prev.version,
            "design_hash": prev.design_hash, "etag": etag,
        },
        headers={"ETag": etag, "X-Design-Version": str(prev.version)},
    )


def store_design(
    svc: Any, session: Session, ident: Identity, design: TrialDesign, reason: str | None = None,
    if_match: list[str] | None = None,
) -> tuple[DesignRow, bool]:
    """Insert a new version unless the latest version has identical content. Returns
    (row, created).

    `if_match` is the list of strong tags the caller presented. `None` skips the check
    (startup seeding of a design id that is not stored yet). A list, including an empty
    one, is required to differ from the current hash.
    """
    data = canonical_json(design)
    h = sha256_hex(data)
    prev = session.exec(
        select(DesignRow).where(DesignRow.design_id == design.id)
        .order_by(col(DesignRow.version).desc())
    ).first()
    if prev is not None and prev.design_hash == h:
        return prev, False
    if prev is not None:
        _reject_identity_change(prev, design)
        if if_match is not None and prev.design_hash not in if_match:
            raise _design_conflict(prev)
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

    try:
        svc.audited_write(session, ident, action, "design", design.id,
                          prev.design_hash if prev else None, h, write, reason)
    except IntegrityError:
        # Another request may have committed this version after the initial
        # If-Match check. The unique (design_id, version) constraint protects the
        # immutable history; expose the race as the same actionable conflict.
        session.rollback()
        current = latest_design_row(session, design.id)
        if current.version >= row.version:
            raise _design_conflict(current) from None
        raise
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
    request: Request,
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
    row, created = store_design(
        svc, session, ident, design, if_match=_strong_etags(request.headers.get("if-match")),
    )
    if not created:
        response.status_code = 200
    response.headers["Location"] = f"/api/designs/{design.id}"
    _design_headers(response, row)
    return design


def _check_design(d: TrialDesign) -> None:
    problems: list[str] = []
    codes: list[str] = []
    if not d.id.strip() or "/" in d.id:
        problems.append("id must be non-empty and contain no '/'")
    if d.enrollment_target < 0:
        problems.append("enrollment_target must be >= 0")
    if d.duration_months <= 0:
        problems.append("duration_months must be > 0")
    for label, ids in (("site", [s.id for s in d.sites]), ("visit", [v.number for v in d.visits])):
        if len(ids) != len(set(ids)):
            problems.append(f"duplicate {label} ids/numbers")
    weeks = [v.week for v in sorted(d.visits, key=lambda v: v.number)]
    if weeks != sorted(weeks):
        problems.append(
            "Visit weeks must be non-decreasing as the visit number increases "
            f"(got {weeks})."
        )
        codes.append("weeks_not_increasing")
    for site in d.sites:
        if site.expected_enrollment is not None and site.expected_enrollment < 0:
            problems.append(
                f"Site {site.id}: expected_enrollment must be >= 0 "
                f"(got {site.expected_enrollment})."
            )
            codes.append("negative_enrollment")
        if site.lat is not None and not -90.0 <= site.lat <= 90.0:
            problems.append(f"Site {site.id}: lat must be between -90 and 90 (got {site.lat}).")
            codes.append("invalid_latitude")
        if site.lon is not None and not -180.0 <= site.lon <= 180.0:
            problems.append(f"Site {site.id}: lon must be between -180 and 180 (got {site.lon}).")
            codes.append("invalid_longitude")
    if problems:
        code = codes[0] if codes and len(codes) == len(problems) and len(set(codes)) == 1 \
            else "invalid_design"
        raise ApiError(422, code, "Invalid trial design: " + "; ".join(problems),
                       {"problems": problems, "codes": codes})


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

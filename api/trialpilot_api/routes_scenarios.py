"""/api/scenarios — compute, compare, drivers, saved scenarios (versioned), submit for approval.

Lifecycle of a saved scenario (one DB row per version, shared `lineage_id`):

    draft --submit--> submitted --(A7 signatures)--> approved | rejected

- A draft may be edited in place by its author (PATCH).
- Once submitted it is immutable (SQLite triggers + route checks): changes go to a NEW version
  (POST /api/scenarios/{id}/versions), the submitted row never changes.
- `record_hash` = sha256 of the scenario content; A7 binds signatures to it.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update
from sqlmodel import Session, col, select

from ._contracts import (
    ApprovalRequest,
    Levers,
    MetricRange,
    Parameter,
    ScenarioResult,
    TrialDesign,
)
from .db import DesignRow, ScenarioRow, get_session, utcnow_iso
from .deps import Identity, require_editor, services
from .engine_adapter import METRICS
from .errors import ApiError
from .hashing import canonical_json, sha256_hex
from .routes_designs import latest_design_row, load_design

log = logging.getLogger("trialpilot.scenarios")
router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])

Status = Literal["draft", "submitted", "approved", "rejected"]


# ------------------------------------------------------------------------------------------
# Request / response models
# ------------------------------------------------------------------------------------------
class LeversIn(Levers):
    """Levers with unknown keys rejected (a typo must not be silently ignored)."""

    model_config = ConfigDict(extra="forbid")


class ComputeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    design_id: str | None = Field(
        default=None,
        description="Stored design. Send design_version to pin the version on screen.",
    )
    design_version: int | None = Field(
        default=None, ge=1,
        description="Required with design_id for compute, drivers and save. "
        "Use X-Design-Version returned by GET /api/designs/{id}.",
    )
    design: TrialDesign | None = Field(default=None, description="Inline design (not stored)")
    levers: LeversIn = Field(default_factory=LeversIn)
    seed: int | None = None
    draws: int | None = Field(default=None, ge=100, le=20000)


class DriversRequest(ComputeRequest):
    metric: str = "co2e_kg"
    top: int = Field(default=5, ge=1, le=25)


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a_id: str
    b_id: str


class ScenarioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    design_id: str
    design_version: int | None = Field(
        default=None, ge=1,
        description="Required. The design version on screen (X-Design-Version from compute).",
    )
    levers: LeversIn = Field(default_factory=LeversIn)
    seed: int | None = None
    draws: int | None = Field(default=None, ge=100, le=20000)


class ScenarioPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    design_version: int | None = Field(
        default=None, ge=1,
        description="Omit to keep this scenario's design version. Does not jump to the latest design.",
    )
    levers: LeversIn | None = None
    seed: int | None = None
    draws: int | None = Field(default=None, ge=100, le=20000)


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=2000)


class ScenarioOut(BaseModel):
    id: str
    lineage_id: str
    version: int
    parent_id: str | None
    name: str
    description: str | None
    design_id: str
    design_version: int
    design_hash: str
    levers: Levers
    seed: int
    draws: int
    result: ScenarioResult
    parameter_set_version: str
    record_hash: str
    author: str
    author_role: str
    status: Status
    approval_id: str | None
    approval: ApprovalRequest | None = None
    created_at: str
    submitted_at: str | None
    decided_at: str | None


class ScenarioSummary(BaseModel):
    id: str
    lineage_id: str
    version: int
    parent_id: str | None
    name: str
    design_id: str
    design_version: int
    status: Status
    author: str
    created_at: str
    parameter_set_version: str
    record_hash: str
    metrics: dict[str, MetricRange]


class Driver(BaseModel):
    parameter_id: str
    share: float = Field(description="Share of the metric's variance (engine definition)")
    label: str | None = None
    unit: str | None = None
    value_low: float | None = None
    value_mid: float | None = None
    value_high: float | None = None
    source_title: str | None = None
    source_url: str | None = None
    source_year: int | None = None
    assumption: bool | None = None


class DriversOut(BaseModel):
    metric: str
    parameter_set_version: str
    drivers: list[Driver]
    warnings: list[str] = []


class CompareOut(BaseModel):
    a_id: str
    b_id: str
    deltas: dict[str, MetricRange] = Field(
        description="b − a per draw (common random numbers): the six headline metrics plus "
        "`cost_usd.<module>` / `co2e_kg.<module>`")
    seed: int
    draws: int
    parameter_set_version: str
    a_metrics: dict[str, MetricRange]
    b_metrics: dict[str, MetricRange]
    same_parameter_set: bool
    warnings: list[str] = []


# ------------------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------------------
def validate_levers(design: TrialDesign, levers: Levers) -> list[str]:
    """Reject levers that cannot apply to this design (422); return honest warnings."""
    problems: list[str] = []
    warnings: list[str] = []
    for name in ("remote_monitoring_share", "local_lab_share"):
        v = getattr(levers, name)
        if not 0.0 <= v <= 1.0:
            problems.append(f"{name} must be between 0 and 1 (got {v})")
    visits = {v.number: v for v in design.visits}
    for name in ("home_visit_numbers", "remote_visit_numbers"):
        unknown = sorted(set(getattr(levers, name)) - set(visits))
        if unknown:
            problems.append(f"{name}: visit numbers {unknown} are not in the design")
    both = sorted(set(levers.home_visit_numbers) & set(levers.remote_visit_numbers))
    if both:
        problems.append(f"visits {both} cannot be both home visits and telehealth visits")
    codes = {p.code for v in design.visits for p in v.procedures}
    unknown_codes = sorted(set(levers.removed_procedures) - codes)
    if unknown_codes:
        problems.append(f"removed_procedures: {unknown_codes} do not occur in the design")
    site_ids = {s.id for s in design.sites}
    unknown_sites = sorted(set(levers.excluded_site_ids) - site_ids)
    if unknown_sites:
        problems.append(f"excluded_site_ids: {unknown_sites} are not sites of this design")
    if site_ids and site_ids <= set(levers.excluded_site_ids):
        problems.append("excluded_site_ids would exclude every site")
    if problems:
        raise ApiError(422, "invalid_levers", "Invalid levers: " + "; ".join(problems),
                       {"problems": problems})
    moved = sorted(set(levers.home_visit_numbers) | set(levers.remote_visit_numbers))
    not_flagged = [n for n in moved if not visits[n].can_be_remote]
    if not_flagged:
        warnings.append(
            f"Visits {not_flagged} are not marked can_be_remote in the design; moving them out of "
            "the site is a clinical decision that a human must confirm."
        )
    return warnings


def _params_snapshot(svc: Any) -> Any:
    snap = svc.params.current()
    if not snap.ok:
        raise ApiError(503, "params_invalid",
                       "The parameter library is invalid, so nothing is computed. Fix the YAML "
                       "files listed in details.problems.",
                       {"problems": snap.problems[:50], "source_dir": snap.source_dir})
    return snap


def _seed_draws(svc: Any, seed: int | None, draws: int | None) -> tuple[int, int]:
    s = svc.settings
    d = draws if draws is not None else s.default_draws
    if d > s.max_draws:
        raise ApiError(422, "too_many_draws", f"draws must be <= {s.max_draws}.",
                       {"max_draws": s.max_draws})
    return (seed if seed is not None else s.default_seed), d


def _resolve_design(
    session: Session, req: ComputeRequest
) -> tuple[TrialDesign, int | None, str | None]:
    if (req.design is None) == (req.design_id is None):
        raise ApiError(422, "design_required",
                       "Send exactly one of `design_id` (stored design) or `design` (inline).")
    if req.design is not None:
        if req.design_version is not None:
            raise ApiError(422, "inline_design_version",
                           "An inline design has no stored design_version.")
        return req.design, None, None
    assert req.design_id is not None
    if req.design_version is None:
        latest = latest_design_row(session, req.design_id)
        raise ApiError(422, "design_version_required",
                       "Send design_version with design_id to compute the version on screen.",
                       {"design_id": req.design_id, "latest_version": latest.version,
                        "etag": f'"{latest.design_hash}"'})
    row, design = load_design(session, req.design_id, req.design_version)
    return design, row.version, row.design_hash


def _missing_field_warnings(design: TrialDesign, version: int | None) -> list[str]:
    """One warning per design field that was not in the source. These travel with the result."""
    where = f"design v{version}" if version is not None else "inline design"
    return [
        f"Design field '{field}' is not from the source; a labelled assumption fills it "
        f"({where} missing_fields)"
        for field in design.missing_fields
    ]


def _with_warnings(result: ScenarioResult, extra: list[str]) -> ScenarioResult:
    new = [w for w in extra if w not in result.warnings]
    return result.model_copy(update={"warnings": [*result.warnings, *new]}) if new else result


def _compute(
    svc: Any, design: TrialDesign, levers: Levers, seed: int, draws: int,
    design_version: int | None,
) -> tuple[ScenarioResult, Any]:
    snap = _params_snapshot(svc)
    lever_warnings = validate_levers(design, levers)
    plain = Levers.model_validate(levers.model_dump())
    outcome = svc.engine.compute(design, plain, snap.params, snap.version, seed, draws)
    extra = [*lever_warnings, *_missing_field_warnings(design, design_version)]
    # The engine already names each visit that is not remote-capable. A second summary
    # of the same fact is the same warning twice.
    if any("remote-capable" in w for w in outcome.result.warnings):
        extra = [w for w in extra if "not marked can_be_remote" not in w]
    return _with_warnings(outcome.result, extra), outcome


def _metrics(result: ScenarioResult) -> dict[str, MetricRange]:
    return {m: getattr(result, m) for m in METRICS}


def scenario_content(row: ScenarioRow) -> dict[str, Any]:
    """Everything a signature vouches for. Status/workflow fields are excluded on purpose."""
    import json

    return {
        "id": row.id, "lineage_id": row.lineage_id, "version": row.version,
        "parent_id": row.parent_id, "name": row.name, "description": row.description,
        "design_id": row.design_id, "design_version": row.design_version,
        "design_hash": row.design_hash, "levers": json.loads(row.levers), "seed": row.seed,
        "draws": row.draws, "result": json.loads(row.result),
        "parameter_set_version": row.parameter_set_version, "author": row.author,
        "author_role": row.author_role, "created_at": row.created_at,
    }


def scenario_hash(row: ScenarioRow) -> str:
    return sha256_hex(scenario_content(row))


def _get_row(session: Session, scenario_id: str) -> ScenarioRow:
    row = session.get(ScenarioRow, scenario_id)
    if row is None:
        raise ApiError(404, "scenario_not_found", f"No saved scenario with id {scenario_id!r}.",
                       {"scenario_id": scenario_id})
    return row


def _out(row: ScenarioRow, approval: ApprovalRequest | None = None) -> ScenarioOut:
    return ScenarioOut(
        id=row.id, lineage_id=row.lineage_id, version=row.version, parent_id=row.parent_id,
        name=row.name, description=row.description, design_id=row.design_id,
        design_version=row.design_version, design_hash=row.design_hash,
        levers=Levers.model_validate_json(row.levers), seed=row.seed, draws=row.draws,
        result=ScenarioResult.model_validate_json(row.result),
        parameter_set_version=row.parameter_set_version, record_hash=row.record_hash,
        author=row.author, author_role=row.author_role, status=row.status,  # type: ignore[arg-type]
        approval_id=row.approval_id, approval=approval, created_at=row.created_at,
        submitted_at=row.submitted_at, decided_at=row.decided_at,
    )


def _summary(row: ScenarioRow) -> ScenarioSummary:
    result = ScenarioResult.model_validate_json(row.result)
    return ScenarioSummary(
        id=row.id, lineage_id=row.lineage_id, version=row.version, parent_id=row.parent_id,
        name=row.name, design_id=row.design_id, design_version=row.design_version,
        status=row.status, author=row.author, created_at=row.created_at,  # type: ignore[arg-type]
        parameter_set_version=row.parameter_set_version, record_hash=row.record_hash,
        metrics=_metrics(result),
    )


def sync_status(svc: Any, session: Session, row: ScenarioRow) -> ApprovalRequest | None:
    """Pull the approval decision (A7) into the scenario row: submitted -> approved/rejected."""
    approval = svc.compliance.get_approval(row.approval_id)
    if row.status != "submitted" or approval is None or approval.status == "pending":
        return approval
    new_status = approval.status
    rid, before = row.id, row.record_hash
    system = Identity(user="system.workflow", role="admin")

    def write(s: Session) -> None:
        s.execute(
            update(ScenarioRow)
            .where(col(ScenarioRow.id) == rid, col(ScenarioRow.status) == "submitted")
            .values(status=new_status, decided_at=utcnow_iso())
        )

    svc.audited_write(session, system, f"scenario.{new_status}", "scenario", rid, before, before,
                      write, reason=f"approval request {approval.id} is {new_status}")
    session.refresh(row)
    return approval


def _sync_submitted(svc: Any, session: Session, rows: list[ScenarioRow]) -> None:
    """`sync_status` for every submitted row, so listings report the decided status."""
    for r in rows:
        if r.status == "submitted":
            sync_status(svc, session, r)


def resolve_scenario_hash(engine: Any, record_id: str) -> str | None:
    """For A7 (records.register_resolver): the current content hash of a saved scenario,
    recomputed from the stored row, so a signature on changed content shows as invalid."""
    with Session(engine) as s:
        row = s.get(ScenarioRow, record_id)
        return scenario_hash(row) if row else None


def _new_row(
    *, ident: Identity, name: str, description: str | None, design_id: str,
    design_version: int, design_hash: str, levers: Levers, seed: int, draws: int,
    result: ScenarioResult, lineage_id: str | None, version: int, parent_id: str | None,
) -> ScenarioRow:
    sid = str(uuid.uuid4())
    row = ScenarioRow(
        id=sid, lineage_id=lineage_id or sid, version=version, parent_id=parent_id, name=name,
        description=description, design_id=design_id, design_version=design_version,
        design_hash=design_hash, levers=canonical_json(levers), seed=seed, draws=draws,
        result=canonical_json(result), parameter_set_version=result.parameter_set_version,
        record_hash="", author=ident.user, author_role=ident.role, status="draft",
        created_at=utcnow_iso(),
    )
    row.record_hash = scenario_hash(row)
    return row


def _recompute_from(
    svc: Any, session: Session, base: ScenarioRow, body: ScenarioPatch
) -> tuple[DesignRow, Levers, int, int, ScenarioResult, Any]:
    """Recompute `base` with what `body` sends; every field it omits keeps the base row's value
    (the design version too: it never jumps to the latest design)."""
    drow, design = load_design(session, base.design_id, body.design_version or base.design_version)
    levers = (Levers.model_validate(body.levers.model_dump()) if body.levers is not None
              else Levers.model_validate_json(base.levers))
    seed, draws = _seed_draws(svc, body.seed if body.seed is not None else base.seed,
                              body.draws if body.draws is not None else base.draws)
    result, outcome = _compute(svc, design, levers, seed, draws, drow.version)
    return drow, levers, seed, draws, result, outcome


def _set_compute_headers(response: Response, outcome: Any, result: ScenarioResult) -> None:
    response.headers["X-Compute-Ms"] = f"{outcome.compute_ms:.1f}"
    response.headers["X-Queue-Ms"] = f"{outcome.queue_ms:.1f}"
    response.headers["X-Cache"] = "hit" if outcome.cache_hit else "miss"
    response.headers["X-Parameter-Set-Version"] = result.parameter_set_version


def _set_design_pin(response: Response, version: int | None, design_hash: str | None) -> None:
    """The version and hash this response was computed from. Save must send the version."""
    if version is not None:
        response.headers["X-Design-Version"] = str(version)
    if design_hash:
        response.headers["ETag"] = f'"{design_hash}"'


# ------------------------------------------------------------------------------------------
# Stateless computation
# ------------------------------------------------------------------------------------------
@router.post("/compute", response_model=ScenarioResult)
def compute(
    req: ComputeRequest,
    response: Response,
    session: Session = Depends(get_session),
    svc: Any = Depends(services),
) -> ScenarioResult:
    """`{design_id | design, design_version?, levers, seed?, draws?}` -> ScenarioResult.

    `design_version` is required with a stored design. Headers: X-Compute-Ms,
    X-Cache (hit|miss), X-Parameter-Set-Version,
    and for a stored design `X-Design-Version` plus `ETag` (the design hash).
    """
    design, version, design_hash = _resolve_design(session, req)
    seed, draws = _seed_draws(svc, req.seed, req.draws)
    result, outcome = _compute(svc, design, req.levers, seed, draws, version)
    _set_compute_headers(response, outcome, result)
    _set_design_pin(response, version, design_hash)
    return result


def _drivers_out(
    svc: Any, design: TrialDesign, levers: Levers, params: dict[str, Parameter], version: str,
    metric: str, top: int, seed: int, draws: int, warnings: list[str],
) -> DriversOut:
    if metric not in METRICS and not metric.startswith(("cost_usd.", "co2e_kg.")):
        raise ApiError(422, "invalid_metric",
                       f"metric must be one of {', '.join(METRICS)} (or cost_usd.<module> / "
                       "co2e_kg.<module>).", {"metric": metric})
    validate_levers(design, levers)
    plain = Levers.model_validate(levers.model_dump())
    pairs, engine_warnings = svc.engine.drivers(design, plain, params, metric, top, seed, draws)
    warnings = [*warnings, *engine_warnings]
    out: list[Driver] = []
    for pid, share in pairs:
        p = params.get(pid)
        out.append(Driver(parameter_id=pid, share=share, **({
            "label": p.label, "unit": p.unit, "value_low": p.value_low, "value_mid": p.value_mid,
            "value_high": p.value_high, "source_title": p.source_title,
            "source_url": p.source_url, "source_year": p.source_year,
            "assumption": p.assumption,
        } if p else {})))
    return DriversOut(metric=metric, parameter_set_version=version, drivers=out,
                      warnings=warnings)


@router.post("/drivers", response_model=DriversOut)
def drivers_unsaved(
    req: DriversRequest, session: Session = Depends(get_session), svc: Any = Depends(services)
) -> DriversOut:
    """Top parameters by contribution to the variance of `metric`, for an unsaved scenario."""
    design, _, _ = _resolve_design(session, req)
    seed, draws = _seed_draws(svc, req.seed, req.draws)
    snap = _params_snapshot(svc)
    return _drivers_out(svc, design, req.levers, snap.params, snap.version, req.metric, req.top,
                        seed, draws, [])


@router.post("/compare", response_model=CompareOut)
def compare(
    req: CompareRequest, session: Session = Depends(get_session), svc: Any = Depends(services)
) -> CompareOut:
    """Deltas b − a between two saved scenarios on the same design version, computed per draw
    with common random numbers (both lever sets are recomputed with A's seed and draws)."""
    a, b = _get_row(session, req.a_id), _get_row(session, req.b_id)
    if (a.design_id, a.design_version) != (b.design_id, b.design_version):
        raise ApiError(422, "compare_needs_same_design",
                       "Per-draw comparison needs both scenarios on the same trial design version "
                       f"({a.design_id} v{a.design_version} vs {b.design_id} v{b.design_version}).",
                       {"a": [a.design_id, a.design_version], "b": [b.design_id, b.design_version]})
    ra = ScenarioResult.model_validate_json(a.result)
    rb = ScenarioResult.model_validate_json(b.result)
    warnings: list[str] = []
    same = a.parameter_set_version == b.parameter_set_version
    stored = svc.params.params_for_set(a.parameter_set_version) if same else None
    if stored is not None:
        params, version = {p.id: p for p in stored}, a.parameter_set_version
    else:
        snap = _params_snapshot(svc)
        params, version = snap.params, snap.version
        warnings.append("The two scenarios were saved with different (or unknown) parameter sets "
                        f"({a.parameter_set_version} vs {b.parameter_set_version}); the deltas use "
                        f"the current set {version}, so they may not match the saved results.")
    if (a.seed, a.draws) != (b.seed, b.draws):
        warnings.append(f"Scenario B was saved with seed {b.seed} / {b.draws} draws; the per-draw "
                        f"deltas use A's seed {a.seed} / {a.draws} draws for both.")
    _, design = load_design(session, a.design_id, a.design_version)
    deltas, engine_warnings = svc.engine.compare(
        design, Levers.model_validate_json(a.levers), Levers.model_validate_json(b.levers),
        params, a.seed, a.draws)
    return CompareOut(a_id=a.id, b_id=b.id, deltas=deltas, seed=a.seed, draws=a.draws,
                      parameter_set_version=version, a_metrics=_metrics(ra),
                      b_metrics=_metrics(rb), same_parameter_set=same,
                      warnings=[*warnings, *engine_warnings])


# ------------------------------------------------------------------------------------------
# Saved scenarios
# ------------------------------------------------------------------------------------------
@router.post("", response_model=ScenarioOut, status_code=201)
def save_scenario(
    body: ScenarioCreate,
    response: Response,
    ident: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
    svc: Any = Depends(services),
) -> ScenarioOut:
    """Compute and save a new scenario (version 1 of a new lineage) as a draft.

    `design_version` is required. The save recomputes that exact version, so the stored
    record cannot move onto a design version newer than the one on screen.
    """
    if body.design_version is None:
        latest = latest_design_row(session, body.design_id)
        raise ApiError(
            422, "design_version_required",
            "Send design_version: the version on screen (the X-Design-Version header from "
            f"compute). Saving without it would use the latest version (v{latest.version}), "
            "which can differ from the one you reviewed.",
            {
                "design_id": body.design_id, "latest_version": latest.version,
                "latest_design_hash": latest.design_hash, "etag": f'"{latest.design_hash}"',
            },
        )
    drow, design = load_design(session, body.design_id, body.design_version)
    seed, draws = _seed_draws(svc, body.seed, body.draws)
    result, outcome = _compute(svc, design, body.levers, seed, draws, drow.version)
    row = _new_row(
        ident=ident, name=body.name, description=body.description,
        design_id=drow.design_id, design_version=drow.version, design_hash=drow.design_hash,
        levers=Levers.model_validate(body.levers.model_dump()), seed=seed, draws=draws,
        result=result, lineage_id=None, version=1, parent_id=None,
    )
    svc.audited_write(session, ident, "scenario.create", "scenario", row.id, None,
                      row.record_hash, lambda s: s.add(row))
    session.refresh(row)
    _set_compute_headers(response, outcome, result)
    _set_design_pin(response, drow.version, drow.design_hash)
    response.headers["Location"] = f"/api/scenarios/{row.id}"
    return _out(row)


@router.get("", response_model=list[ScenarioSummary])
def list_scenarios(
    design_id: str | None = None,
    lineage_id: str | None = None,
    status: Status | None = None,
    latest_only: bool = Query(default=False, description="Only the newest version per lineage"),
    session: Session = Depends(get_session),
    svc: Any = Depends(services),
) -> list[ScenarioSummary]:
    q = select(ScenarioRow)
    if design_id:
        q = q.where(ScenarioRow.design_id == design_id)
    if lineage_id:
        q = q.where(ScenarioRow.lineage_id == lineage_id)
    rows = list(session.exec(q.order_by(col(ScenarioRow.created_at).desc())).all())
    _sync_submitted(svc, session, rows)
    if status:
        rows = [r for r in rows if r.status == status]
    if latest_only:
        seen: set[str] = set()
        newest: list[ScenarioRow] = []
        for r in sorted(rows, key=lambda r: (r.lineage_id, -r.version)):
            if r.lineage_id not in seen:
                seen.add(r.lineage_id)
                newest.append(r)
        rows = sorted(newest, key=lambda r: r.created_at, reverse=True)
    return [_summary(r) for r in rows]


@router.get("/{scenario_id}", response_model=ScenarioOut)
def get_scenario(
    scenario_id: str, session: Session = Depends(get_session), svc: Any = Depends(services)
) -> ScenarioOut:
    row = _get_row(session, scenario_id)
    approval = sync_status(svc, session, row)
    return _out(row, approval)


@router.get("/{scenario_id}/versions", response_model=list[ScenarioSummary])
def scenario_versions(
    scenario_id: str, session: Session = Depends(get_session), svc: Any = Depends(services)
) -> list[ScenarioSummary]:
    row = _get_row(session, scenario_id)
    rows = list(session.exec(
        select(ScenarioRow).where(ScenarioRow.lineage_id == row.lineage_id)
        .order_by(col(ScenarioRow.version))
    ).all())
    _sync_submitted(svc, session, rows)
    return [_summary(r) for r in rows]


@router.patch("/{scenario_id}", response_model=ScenarioOut)
def edit_draft(
    scenario_id: str,
    body: ScenarioPatch,
    response: Response,
    ident: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
    svc: Any = Depends(services),
) -> ScenarioOut:
    """Edit a DRAFT in place (author or admin). Submitted/approved -> 409 `scenario_immutable`."""
    row = _get_row(session, scenario_id)
    if row.status != "draft":
        raise ApiError(409, "scenario_immutable",
                       f"This scenario is {row.status} and can no longer change. Create a new "
                       f"version instead: POST /api/scenarios/{row.id}/versions.",
                       {"status": row.status, "scenario_id": row.id})
    if ident.user != row.author and ident.role != "admin":
        raise ApiError(403, "not_author", "Only the author can edit a draft scenario.",
                       {"author": row.author})
    before = row.record_hash
    drow, levers, seed, draws, result, outcome = _recompute_from(svc, session, row, body)
    row.name = body.name if body.name is not None else row.name
    row.description = body.description if body.description is not None else row.description
    row.design_version, row.design_hash = drow.version, drow.design_hash
    row.levers, row.seed, row.draws = canonical_json(levers), seed, draws
    row.result, row.parameter_set_version = canonical_json(result), result.parameter_set_version
    row.record_hash = scenario_hash(row)
    values = {k: getattr(row, k) for k in (
        "name", "description", "design_version", "design_hash", "levers", "seed", "draws",
        "result", "parameter_set_version", "record_hash")}
    rid = row.id

    def write(s: Session) -> None:
        res = s.execute(update(ScenarioRow).where(
            col(ScenarioRow.id) == rid, col(ScenarioRow.status) == "draft").values(**values))
        if res.rowcount != 1:  # type: ignore[attr-defined]
            raise ApiError(409, "scenario_immutable",
                           "The scenario was submitted meanwhile; create a new version.")

    session.expunge(row)
    svc.audited_write(session, ident, "scenario.update", "scenario", rid, before,
                      values["record_hash"], write)
    fresh = _get_row(session, rid)
    _set_compute_headers(response, outcome, result)
    _set_design_pin(response, drow.version, drow.design_hash)
    return _out(fresh)


@router.post("/{scenario_id}/versions", response_model=ScenarioOut, status_code=201)
def new_version(
    scenario_id: str,
    response: Response,
    body: ScenarioPatch = Body(default_factory=ScenarioPatch),
    ident: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
    svc: Any = Depends(services),
) -> ScenarioOut:
    """New draft version of any scenario (the base row is never modified). Recomputed with the
    current parameter library."""
    base = _get_row(session, scenario_id)
    drow, levers, seed, draws, result, outcome = _recompute_from(svc, session, base, body)
    top = session.exec(
        select(ScenarioRow.version).where(ScenarioRow.lineage_id == base.lineage_id)
        .order_by(col(ScenarioRow.version).desc())
    ).first()
    row = _new_row(
        ident=ident, name=body.name or base.name,
        description=body.description if body.description is not None else base.description,
        design_id=drow.design_id, design_version=drow.version, design_hash=drow.design_hash,
        levers=levers, seed=seed, draws=draws, result=result, lineage_id=base.lineage_id,
        version=(top or base.version) + 1, parent_id=base.id,
    )
    svc.audited_write(session, ident, "scenario.version", "scenario", row.id, base.record_hash,
                      row.record_hash, lambda s: s.add(row),
                      reason=f"new version of {base.id} (v{base.version})")
    session.refresh(row)
    _set_compute_headers(response, outcome, result)
    _set_design_pin(response, drow.version, drow.design_hash)
    response.headers["Location"] = f"/api/scenarios/{row.id}"
    return _out(row)


@router.post("/{scenario_id}/submit", response_model=ScenarioOut)
def submit(
    scenario_id: str,
    body: ReasonBody = Body(default_factory=ReasonBody),
    ident: Identity = Depends(require_editor),
    session: Session = Depends(get_session),
    svc: Any = Depends(services),
) -> ScenarioOut:
    """Submit a draft for approval: freezes it and creates an ApprovalRequest (A7)."""
    row = _get_row(session, scenario_id)
    if row.status != "draft":
        raise ApiError(409, "already_submitted",
                       f"This scenario is already {row.status}; it cannot be submitted again.",
                       {"status": row.status, "approval_id": row.approval_id})
    # Author only, no admin bypass: admin holds no approval.submit permission, and the approval
    # request is filed under the author (its segregation-of-duties key) whoever calls this.
    if ident.user != row.author:
        raise ApiError(403, "not_author", "Only the author can submit a scenario for approval.",
                       {"author": row.author})
    rid, record_hash, author = row.id, row.record_hash, row.author
    approval = svc.compliance.create_approval(
        "scenario", rid, record_hash, author, title=row.name, reason=body.reason)
    now = utcnow_iso()

    def write(s: Session) -> None:
        res = s.execute(update(ScenarioRow).where(
            col(ScenarioRow.id) == rid, col(ScenarioRow.status) == "draft"
        ).values(status="submitted", approval_id=approval.id, submitted_at=now))
        if res.rowcount != 1:  # type: ignore[attr-defined]
            raise ApiError(409, "already_submitted", "This scenario was submitted meanwhile.")

    session.expunge(row)
    svc.audited_write(session, ident, "scenario.submit", "scenario", rid, record_hash,
                      record_hash, write, reason=body.reason or f"approval request {approval.id}")
    return _out(_get_row(session, rid), approval)


@router.get("/{scenario_id}/drivers", response_model=DriversOut)
def scenario_drivers(
    scenario_id: str,
    metric: str = Query(default="co2e_kg"),
    top: int = Query(default=5, ge=1, le=25),
    session: Session = Depends(get_session),
    svc: Any = Depends(services),
) -> DriversOut:
    """Top drivers of `metric` for a saved scenario, using the parameters it was computed with."""
    row = _get_row(session, scenario_id)
    _, design = load_design(session, row.design_id, row.design_version)
    warnings: list[str] = []
    stored = svc.params.params_for_set(row.parameter_set_version)
    if stored is not None:
        params, version = {p.id: p for p in stored}, row.parameter_set_version
    else:
        snap = _params_snapshot(svc)
        params, version = snap.params, snap.version
        warnings.append(f"Parameter set {row.parameter_set_version} is not stored; drivers use "
                        f"the current set {version}.")
    return _drivers_out(svc, design, Levers.model_validate_json(row.levers), params, version,
                        metric, top, row.seed, row.draws, warnings)

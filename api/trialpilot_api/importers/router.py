"""FastAPI router for the importers (A5 mounts it at `/api/import`).

POST /ctgov/{nct_id}            ClinicalTrials.gov study -> TrialDesign (+ notes on every assumption)
GET  /ctgov                     studies available in the local cache (offline demo list)
GET  /procedure-codes           generic label for each procedure code (not one member assessment)
POST /protocol                  protocol PDF (multipart `file`, or form `nct_id`) -> candidate visits
POST /protocol/apply            human-accepted visits + design -> updated design (never automatic)
POST /protocol/review           log how many candidates a human accepted / edited / rejected
GET  /protocol/review/stats     running totals of those reviews (not a live-model accuracy)

Errors use the shared shape {"error", "message", "details"}. Every successful import, apply and
review writes an audit entry (A5's compliance adapter when mounted in the app, else A7's
`compliance.audit.append`); if the audit trail cannot be written the request fails.

Identity (URS-023): inside A5's app the role comes from A7's user registry via A5's
`deps.resolve_identity`, never from `X-Role`. Importing and extracting read public data, so anonymous
callers may do them (audited as anonymous); apply and review are human confirmations and need a
registered person who may change data (not a viewer, never an `ai:` actor).
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ._contracts import TrialDesign, Visit
from .ctgov import (
    TIMEOUT_S,
    USER_AGENT,
    CtgovError,
    FieldNote,
    cached_study_ids,
    design_id_for,
    fetch_study_result,
    map_study_report,
    normalize_nct,
    note_payload,
    protocol_documents,
)
from .endpoints import link_visits
from .paths import demo_offline, protocols_dir, runtime_cache_dir
from .procedures import default_vocabulary
from .protocol_extract import (
    ExtractionFailed,
    ExtractionResult,
    extract_schedule,
    load_cached,
    pdf_sha256,
)

router = APIRouter(tags=["import"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
LLM_ACCURACY = "unmeasured"
LLM_ACCURACY_NOTE = "Real LLM accuracy was not measured."
_ROLES = {"author", "reviewer", "qa", "admin", "viewer"}
_AI_ACTOR_PREFIX = "ai:"  # same convention as A7 (compliance/config.py)
_sha_locks: dict[str, threading.Lock] = {}
_sha_locks_guard = threading.Lock()


# ---------------------------------------------------------------- helpers
def _error(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message, "details": details or {}})


def record_hash(obj: Any) -> str:
    try:  # A7's canonical hash, so audit hashes match the rest of the system
        from trialpilot_api.compliance import hashing

        return str(hashing.record_hash(obj))
    except Exception:
        data = obj.model_dump(mode="json") if hasattr(obj, "model_dump") else obj
        return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


AuditFn = Callable[..., Any]
_memory_audit_log: list[dict[str, Any]] = []


def _memory_audit(actor: str, role: str, action: str, object_type: str, object_id: str,
                  before_hash: str | None, after_hash: str | None, reason: str | None = None) -> dict[str, Any]:
    entry = {"actor": actor, "role": role, "action": action, "object_type": object_type, "object_id": object_id,
             "before_hash": before_hash, "after_hash": after_hash, "reason": reason}
    _memory_audit_log.append(entry)
    return entry


def get_auditor(request: Request) -> AuditFn:
    """A5's adapter if the app provides one, else A7's audit module, else an in-memory stub (standalone use)."""
    services = getattr(request.app.state, "services", None)
    comp = getattr(services, "compliance", None)
    if comp is not None and callable(getattr(comp, "append", None)):
        return comp.append  # type: ignore[no-any-return]
    try:
        from trialpilot_api.compliance import audit

        return audit.append  # type: ignore[no-any-return]
    except Exception:
        return _memory_audit


def get_actor(request: Request, x_user: str | None = Header(default=None),
              x_role: str | None = Header(default=None)) -> tuple[str, str]:
    """(user, role). In A5's app: A5's resolver (registry role; its ApiError -> 400/403 in the shared shape).
    Standalone (no app services, e.g. this package's tests): the demo headers as given."""
    if getattr(request.app.state, "services", None) is not None:
        try:
            from trialpilot_api.deps import resolve_identity
        except ImportError:
            pass
        else:
            ident = resolve_identity(request, x_user, x_role)
            return ("anonymous", "viewer") if ident is None else (ident.user, ident.role)
    if not x_user:
        return "anonymous", "viewer"
    role = (x_role or "author").strip().lower()
    return x_user.strip()[:64], role if role in _ROLES else "viewer"


def get_offline(request: Request) -> bool:
    """A5's `Settings.demo_offline` when mounted (the flag /api/health reports), else `DEMO_OFFLINE`."""
    offline = getattr(getattr(request.app.state, "settings", None), "demo_offline", None)
    return demo_offline() if offline is None else bool(offline)


def _require_confirmer(actor: tuple[str, str]) -> JSONResponse | None:
    """Accepting extracted candidates is a human decision: a registered, non-viewer, non-AI identity."""
    user, role = actor
    if user == "anonymous":
        return _error(401, "identity_required", "Send the demo identity header X-User to confirm a schedule.")
    if user.startswith(_AI_ACTOR_PREFIX):
        return _error(403, "ai_confirmation_forbidden",
                      "AI actors may draft candidates but never confirm them; a person must.", {"user": user})
    if role == "viewer":
        return _error(403, "forbidden_role", "The viewer role cannot change data.", {"role": role})
    return None


def _audit(audit: AuditFn, actor: tuple[str, str], action: str, object_type: str, object_id: str,
           before: str | None, after: str | None, reason: str | None) -> JSONResponse | None:
    try:
        audit(actor[0], actor[1], action, object_type, object_id, before, after, reason)
    except Exception as exc:
        return _error(503, "audit_unavailable", "The audit trail could not be written, so the result was not returned.",
                      {"cause": type(exc).__name__})
    return None


def _with_group_labels(node: Any) -> Any:
    """Add each procedure's category name. The shared Procedure model does not store it; A5 drops it on save."""
    labels = default_vocabulary().group_label_map()
    if isinstance(node, dict):
        code = node.get("code")
        if isinstance(code, str) and code in labels and "label" in node:
            node["group_label"] = labels[code]
        for value in node.values():
            _with_group_labels(value)
    elif isinstance(node, list):
        for value in node:
            _with_group_labels(value)
    return node


def _stored_design(request: Request, design_id: str | None) -> TrialDesign | None:
    """Read existing human annotations when mounted in the app; standalone has no store."""
    services = getattr(request.app.state, "services", None)
    if services is None or not design_id:
        return None
    from sqlmodel import Session

    from trialpilot_api.errors import ApiError
    from trialpilot_api.routes_designs import load_design

    with Session(services.db_engine) as session:
        try:
            return load_design(session, design_id)[1]
        except ApiError as exc:
            if exc.status_code != 404:
                raise
    return None


def _cached_outcomes(registry_id: str | None) -> dict[str, Any]:
    """An upload without registry metadata stays unknown; never invent links from the PDF."""
    if not registry_id or not registry_id.strip().upper().startswith("NCT"):
        return {}
    try:
        raw = fetch_study_result(registry_id, offline=True).raw
    except CtgovError:
        return {}
    return (raw.get("protocolSection") or {}).get("outcomesModule") or {}


def _lock_for(sha: str) -> threading.Lock:
    with _sha_locks_guard:
        return _sha_locks.setdefault(sha, threading.Lock())


def known_protocols() -> dict[str, dict[str, Any]]:
    """NCT -> protocol document info from the committed transcriptions (sha256 lets us find cached extractions)."""
    out: dict[str, dict[str, Any]] = {}
    for p in sorted(protocols_dir().glob("*_soa_transcription.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        out[doc["nct_id"]] = dict(doc["document"])
    return out


# ---------------------------------------------------------------- ClinicalTrials.gov
@router.get("/ctgov")
def list_cached_studies(offline: bool = Depends(get_offline)) -> Any:
    known = known_protocols()
    items = []
    for nct in cached_study_ids():
        try:
            r = fetch_study_result(nct, offline=True)
            rep = map_study_report(r.raw, meta=r.meta)
        except Exception:  # a broken cache file must not hide the others
            continue
        d = rep.design
        items.append({
            "nct_id": nct, "title": d.title, "acronym": rep.acronym, "phase": d.phase, "drug_type": d.drug_type,
            "sites": len(d.sites), "enrollment": d.enrollment_target, "sponsor": rep.sponsor,
            "conditions": d.conditions, "protocol_extraction_cached": bool(
                nct in known and load_cached(known[nct]["sha256"]) is not None),
        })
    return {"studies": items, "offline": offline}


@router.get("/procedure-codes")
def list_procedure_codes() -> Any:
    """One readable name per code. A code can cover many assessments, so the name is the category."""
    return default_vocabulary().catalog()


@router.post("/ctgov/{nct_id}")
def import_ctgov(
    nct_id: str,
    request: Request,
    refresh: bool = Query(False, description="Re-download even if cached (falls back to cache on network failure)."),
    actor: tuple[str, str] = Depends(get_actor),
    audit: AuditFn = Depends(get_auditor),
    offline: bool = Depends(get_offline),
) -> Any:
    try:
        res = fetch_study_result(nct_id, refresh=refresh, offline=offline)
        rep = map_study_report(res.raw, meta=res.meta)
    except CtgovError as exc:
        return _error(exc.status, exc.code, exc.message, exc.details)
    d = rep.design
    stored = _stored_design(request, d.id)
    d.visits = link_visits(d.visits, (res.raw.get("protocolSection") or {}).get("outcomesModule") or {},
                          stored.visits if stored else None)
    known = known_protocols()
    docs = []
    for doc in rep.documents:
        k = known.get(d.registry_id or "", {})
        cached = bool(doc["has_protocol"] and k.get("filename") == doc["filename"] and load_cached(k["sha256"]))
        docs.append({**doc, "extraction_cached": cached})
    field_notes = list(rep.field_notes)
    if res.stale_fallback:
        fetched = res.meta.get("fetched_at", "an earlier fetch")
        field_notes.insert(0, FieldNote(
            "ClinicalTrials.gov could not be reached; the cached copy from "
            f"{fetched} was used.",
            None, "fact",
        ))
    if (err := _audit(audit, actor, "import.ctgov", "trial_design", d.id, None, record_hash(d),
                      f"Imported {d.registry_id} from ClinicalTrials.gov ({'cache' if res.cached else 'live'})")):
        return err
    return {
        "design": _with_group_labels(d.model_dump(mode="json")),
        "raw_cached": res.cached,
        "stale_fallback": res.stale_fallback,
        "missing_fields": d.missing_fields,
        **note_payload(field_notes),
        "procedure_group_labels": default_vocabulary().group_label_map(),
        "field_sources": rep.field_sources,
        "enrollment_type": rep.enrollment_type,
        "drug_type_basis": rep.drug_type_basis,
        "visit_template_id": rep.visit_template_id,
        "geocoded_site_ids": rep.geocoded_site_ids,
        "unresolved_site_ids": rep.unresolved_site_ids,
        "sponsor": rep.sponsor,
        "collaborators": rep.collaborators,
        "overall_status": rep.overall_status,
        "acronym": rep.acronym,
        "dates": rep.dates,
        "documents": docs,
        "source": {"name": "ClinicalTrials.gov", "simulated": False, "fetched_at": res.meta.get("fetched_at"),
                   "data_timestamp": res.meta.get("data_timestamp"), "api_version": res.meta.get("api_version")},
        "attribution": rep.attribution,
    }


# ---------------------------------------------------------------- protocol PDF
def _download_protocol(nct: str, offline: bool) -> tuple[bytes, dict[str, Any]]:
    """Protocol PDF for a cached study: runtime cache first (gitignored), else the ClinicalTrials.gov CDN."""
    res = fetch_study_result(nct, offline=offline)
    docs = [d for d in protocol_documents(res.raw) if d["has_protocol"]]
    if not docs:
        raise ExtractionFailed(404, "no_protocol_document", f"{nct} has no protocol document on ClinicalTrials.gov.")
    doc = docs[0]
    path = runtime_cache_dir() / f"{nct}_{doc['filename']}"
    if path.exists():
        return path.read_bytes(), doc
    if offline:
        raise ExtractionFailed(503, "offline_cache_miss", f"Offline demo mode: the protocol PDF for {nct} is not cached.")
    if (doc.get("size_bytes") or 0) > MAX_UPLOAD_BYTES:
        raise ExtractionFailed(413, "payload_too_large", "The protocol PDF is larger than 20 MB.", {"size_bytes": doc["size_bytes"]})
    try:
        with httpx.Client(timeout=max(TIMEOUT_S, 60.0), headers={"User-Agent": USER_AGENT}, follow_redirects=True) as c:
            r = c.get(doc["url"])
    except httpx.TransportError as exc:
        raise ExtractionFailed(503, "registry_unavailable", "The protocol PDF could not be downloaded.",
                               {"url": doc["url"], "cause": type(exc).__name__}) from exc
    if r.status_code != 200 or not r.content.startswith(b"%PDF"):
        raise ExtractionFailed(502, "protocol_download_failed", f"Downloading the protocol returned HTTP {r.status_code}.",
                               {"url": doc["url"]})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(r.content)
    return r.content, doc


def _annotated_candidates(request: Request, result: ExtractionResult, nct_id: str | None,
                          design_id: str | None) -> ExtractionResult:
    """A copy of `result` (cached extractions stay untouched) annotated from the registry cache and saved
    human decisions. `nct_id` is normalized; a stored design for another registry id gives way to the
    design imported from `nct_id`."""
    stored = _stored_design(request, design_id)
    registry_id = nct_id or (stored.registry_id if stored else None)
    if nct_id and (stored is None or stored.registry_id != nct_id):
        stored = _stored_design(request, design_id_for(nct_id))
    result = result.model_copy(deep=True)
    linked = link_visits(result.visits, _cached_outcomes(registry_id), stored.visits if stored else None)
    for candidate, visit in zip(result.candidates, linked, strict=True):
        candidate.visit = visit
    return result


@router.post("/protocol")
def import_protocol(
    request: Request,
    file: UploadFile | None = File(default=None),
    nct_id: str | None = Form(default=None),
    design_id: str | None = Form(default=None),
    refresh: bool = Form(default=False),
    actor: tuple[str, str] = Depends(get_actor),
    audit: AuditFn = Depends(get_auditor),
    offline: bool = Depends(get_offline),
) -> Any:
    clen = request.headers.get("content-length")
    if clen and clen.isdigit() and int(clen) > MAX_UPLOAD_BYTES + 64 * 1024:
        return _error(413, "payload_too_large", "The upload is larger than 20 MB.", {"limit_bytes": MAX_UPLOAD_BYTES})
    document: dict[str, Any] | None = None
    try:
        if nct_id:
            nct_id = normalize_nct(nct_id)
        if file is not None:
            data = file.file.read(MAX_UPLOAD_BYTES + 1)
            if len(data) > MAX_UPLOAD_BYTES:
                return _error(413, "payload_too_large", "The upload is larger than 20 MB.", {"limit_bytes": MAX_UPLOAD_BYTES})
            if not data:
                return _error(400, "empty_file", "The uploaded file is empty.")
            document = {"filename": file.filename, "size_bytes": len(data), "source": "upload"}
        elif nct_id:
            known = known_protocols().get(nct_id)
            if known and not refresh and (cached := load_cached(known["sha256"])) is not None:
                data = b""
                result = cached
                document = {**known, "source": "ctgov"}
            else:
                data, doc = _download_protocol(nct_id, offline)
                document = {**doc, "source": "ctgov"}
        else:
            return _error(400, "missing_input", "Send a protocol PDF as multipart field 'file', or a form field 'nct_id'.")
        if data:
            with _lock_for(pdf_sha256(data)):  # a double submit waits and then hits the cache
                result = extract_schedule(data, use_cache=not refresh, offline=offline)
    except CtgovError as exc:
        return _error(exc.status, exc.code, exc.message, exc.details)
    except ExtractionFailed as exc:
        return _error(exc.status, exc.code, exc.message, exc.details)

    result = _annotated_candidates(request, result, nct_id, design_id)
    candidates_hash = record_hash({"candidates": [c.model_dump(mode="json") for c in result.candidates]})
    if (err := _audit(audit, actor, "import.protocol.extract", "protocol_extraction", result.extraction_id, None,
                      candidates_hash, f"{len(result.candidates)} candidate visits ({result.method}"
                      f"{', cached' if result.from_cache else ''}); not applied to any design")):
        return err
    out = _with_group_labels(json.loads(result.model_dump_json()))
    out.update({
        "design_id": design_id,
        "document": document,
        "auto_applied": False,
        "procedure_group_labels": default_vocabulary().group_label_map(),
        "llm_accuracy": LLM_ACCURACY,
        "llm_accuracy_note": LLM_ACCURACY_NOTE,
    })
    return out


class ApplyRequest(BaseModel):
    design: TrialDesign
    visits: list[Visit] = Field(min_length=1)
    extraction_id: str | None = None
    reason: str | None = None


@router.post("/protocol/apply")
def apply_visits(body: ApplyRequest, actor: tuple[str, str] = Depends(get_actor),
                 audit: AuditFn = Depends(get_auditor)) -> Any:
    """Replace a design's visits with the schedule a human confirmed. Returns the new design; storing it is A5's job."""
    if (err := _require_confirmer(actor)):
        return err
    weeks =[v.week for v in sorted(body.visits, key=lambda v: v.number)]
    if weeks != sorted(weeks):
        return _error(422, "weeks_not_increasing", "Visit weeks must increase with the visit number.", {"weeks": weeks})
    if len({v.number for v in body.visits}) != len(body.visits):
        return _error(422, "duplicate_visit_numbers", "Each visit needs a unique number.")
    before = record_hash(body.design)
    cleared_fields = [f for f in body.design.missing_fields if f == "visits"]
    new = body.design.model_copy(update={
        "visits": link_visits(sorted(body.visits, key=lambda v: v.number),
                              _cached_outcomes(body.design.registry_id), body.design.visits),
        "missing_fields": [f for f in body.design.missing_fields if f != "visits"],
    })
    if (err := _audit(audit, actor, "import.protocol.apply", "trial_design", new.id, before, record_hash(new),
                      body.reason or f"Visit schedule confirmed by {actor[0]} from extraction {body.extraction_id or 'n/a'}")):
        return err
    return {
        "design": _with_group_labels(new.model_dump(mode="json")),
        "applied_by": actor[0],
        "visits": len(new.visits),
        "cleared_fields": cleared_fields,
    }


class ReviewLog(BaseModel):
    extraction_id: str
    design_id: str | None = None
    accepted: int = Field(ge=0)
    edited: int = Field(ge=0)
    rejected: int = Field(ge=0)
    added: int = Field(default=0, ge=0)          # visits/procedures the human added that the extractor missed
    unit: str = "visit"                          # "visit" or "procedure"
    # Rows accepted in one action, without opening them. Omitted means the log cannot say;
    # it is not stored as zero.
    bulk_accepted: int | None = Field(default=None, ge=0)


def _review_log_path() -> Path:
    return runtime_cache_dir() / "review_log.jsonl"


def _count(value: Any) -> int | None:
    """A JSON integer count. Booleans and anything else are not a count."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _known_bulk(entry: dict[str, Any]) -> int | None:
    """Rows this review bulk-accepted, or None when the line does not say (do not invent 0)."""
    if "bulk_accepted" not in entry or entry["bulk_accepted"] is None:
        return None
    bulk = _count(entry["bulk_accepted"])
    accepted = _count(entry.get("accepted", 0))
    if bulk is None or accepted is None or bulk < 0 or accepted < 0 or bulk > accepted:
        return None
    return bulk


def review_stats() -> dict[str, Any]:
    """Operational counts over every line. The unchanged-accept share ignores bulk accepts.

    A line with no `bulk_accepted` value (logs written before the field existed, or a client
    that still omits it) is unknown. Those lines stay in the operational totals and are not
    rewritten, and they make the share null rather than a guessed rate.
    """
    tot = {"reviews": 0, "accepted": 0, "edited": 0, "rejected": 0, "added": 0}
    unknown = 0
    known_individual = 0
    known_edited = 0
    known_rejected = 0
    known_bulk = 0
    p = _review_log_path()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            tot["reviews"] += 1
            for k in ("accepted", "edited", "rejected", "added"):
                tot[k] += int(r.get(k, 0) or 0)
            bulk = _known_bulk(r)
            if bulk is None:
                unknown += 1
                continue
            known_bulk += bulk
            known_individual += int(r.get("accepted", 0)) - bulk
            known_edited += int(r.get("edited", 0) or 0)
            known_rejected += int(r.get("rejected", 0) or 0)
    judged = known_individual + known_edited + known_rejected
    if tot["reviews"] == 0:
        status, share = "no_reviews", None
        bulk_total: int | None = 0
        individual: int | None = 0
    elif unknown:
        status, share = "unknown", None
        bulk_total, individual = None, None
    elif judged == 0:
        status, share = "no_individual_review", None
        bulk_total, individual = known_bulk, known_individual
    else:
        status, share = "review_log_only", round(known_individual / judged, 3)
        bulk_total, individual = known_bulk, known_individual
    tot.update({
        "bulk_accepted": bulk_total,
        "individually_accepted": individual,
        "accepted_unchanged_share": share,
        "accepted_unchanged_share_status": status,
        "accuracy_unknown_reviews": unknown,
        "llm_accuracy": LLM_ACCURACY,
        "llm_accuracy_note": LLM_ACCURACY_NOTE,
    })
    return tot


@router.post("/protocol/review")
def log_review(body: ReviewLog, actor: tuple[str, str] = Depends(get_actor), audit: AuditFn = Depends(get_auditor)) -> Any:
    if (err := _require_confirmer(actor)):
        return err
    if body.bulk_accepted is not None and body.bulk_accepted > body.accepted:
        return _error(422, "bulk_accepted_exceeds_accepted",
                      "bulk_accepted counts rows already included in accepted, so it cannot be larger.",
                      {"accepted": body.accepted, "bulk_accepted": body.bulk_accepted})
    entry = {**body.model_dump(), "actor": actor[0], "at": datetime.now(UTC).isoformat(timespec="seconds")}
    if (err := _audit(audit, actor, "import.protocol.review", "protocol_extraction", body.extraction_id, None,
                      record_hash(entry), f"accepted {body.accepted}, edited {body.edited}, rejected {body.rejected}")):
        return err
    p = _review_log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(entry) + "\n")
    return review_stats()


@router.get("/protocol/review/stats")
def get_review_stats() -> Any:
    return review_stats()

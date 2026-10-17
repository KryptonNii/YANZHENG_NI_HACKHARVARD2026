"""ClinicalTrials.gov API v2: fetch (disk-cached, offline-capable) and map a study to `TrialDesign`.

Field paths were checked against the official OpenAPI spec (https://clinicaltrials.gov/api/oas/v2,
API version 2.0.5) and against the saved real responses in `data/fixtures/ctgov/`.

Data terms (https://clinicaltrials.gov/about-site/terms-conditions): attribute ClinicalTrials.gov,
show the date the data were processed, and state modifications. `ImportReport.attribution` and
`ImportReport.notes` carry exactly that.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from ._contracts import Site, TrialDesign, Visit
from .geocode import Geocoder, default_geocoder
from .paths import ctgov_read_dirs, ctgov_write_dir, demo_offline
from .templates import TemplateLibrary, default_templates, treatment_weeks_from_registry

API_BASE = "https://clinicaltrials.gov/api/v2"
STUDY_PAGE = "https://clinicaltrials.gov/study/{nct}"
LARGE_DOC_URL = "https://cdn.clinicaltrials.gov/large-docs/{last2}/{nct}/{filename}"
USER_AGENT = "TrialPilot/0.1 (open-source trial scenario simulator; HackHarvard 2026)"
TIMEOUT_S = 15.0
# The API docs publish no rate limit; we self-limit to <= 50 requests/minute and back off on 429.
MIN_INTERVAL_S = 1.2
NCT_RE = re.compile(r"^NCT\d{8}$")
_NS = uuid.UUID("6f1c3c3e-8a43-4d0e-9b55-1f2a5e0c7a11")  # TrialPilot importer namespace (uuid5 ids)
_DAYS_PER_MONTH = 365.25 / 12


# ---------------------------------------------------------------- errors
class CtgovError(Exception):
    status = 500
    code = "ctgov_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class InvalidRegistryId(CtgovError):
    status, code = 400, "invalid_registry_id"


class StudyNotFound(CtgovError):
    status, code = 404, "study_not_found"


class RegistryUnavailable(CtgovError):
    status, code = 503, "registry_unavailable"


class OfflineCacheMiss(CtgovError):
    status, code = 503, "offline_cache_miss"


class InsufficientRegistryData(CtgovError):
    status, code = 422, "insufficient_registry_data"


def normalize_nct(nct_id: str) -> str:
    s = (nct_id or "").strip().upper()
    if not NCT_RE.match(s):
        raise InvalidRegistryId(
            f"'{nct_id}' is not a ClinicalTrials.gov ID. Expected NCT followed by 8 digits, e.g. NCT03930732.",
            {"nct_id": nct_id},
        )
    return s


# ---------------------------------------------------------------- fetch + cache
@dataclass
class FetchResult:
    raw: dict[str, Any]
    cached: bool  # served from disk without contacting the registry
    meta: dict[str, Any]
    stale_fallback: bool = False  # network failed, older cached copy served


_rate_lock = threading.Lock()
_last_request_at = 0.0


def _polite_wait() -> None:
    global _last_request_at
    with _rate_lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _get_json(client: httpx.Client, url: str, params: dict[str, str] | None = None) -> httpx.Response:
    """GET with timeout and exactly one retry on transport errors, 5xx and 429."""
    last_exc: Exception | None = None
    for attempt in (1, 2):
        _polite_wait()
        try:
            resp = client.get(url, params=params)
        except httpx.TransportError as exc:  # timeouts, DNS, refused connections
            last_exc = exc
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            last_exc = RuntimeError(f"HTTP {resp.status_code}")
            if attempt == 1:
                retry_after = resp.headers.get("Retry-After", "")
                time.sleep(min(float(retry_after), 5.0) if retry_after.isdigit() else 1.0)
            continue
        return resp
    raise RegistryUnavailable(
        "ClinicalTrials.gov could not be reached (timed out or returned an error twice). "
        "Try again, or run with DEMO_OFFLINE=1 to use cached studies.",
        {"cause": f"{type(last_exc).__name__}: {last_exc}"},
    )


def _cache_paths(nct: str, cache_dir: Path) -> tuple[Path, Path]:
    return cache_dir / f"{nct}.json", cache_dir / f"{nct}.meta.json"


def _read_dirs(cache_dir: Path | None) -> list[Path]:
    return [cache_dir] if cache_dir is not None else ctgov_read_dirs()


def _read_cache(nct: str, cache_dir: Path | None) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Writable runtime cache first, then the committed fixtures."""
    for d in _read_dirs(cache_dir):
        raw_p, meta_p = _cache_paths(nct, d)
        if raw_p.exists():
            raw = json.loads(raw_p.read_text(encoding="utf-8"))
            meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
            return raw, meta
    return None


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")  # LF on every OS (repo is eol=lf)
    os.replace(tmp, path)


def fetch_study_result(
    nct_id: str,
    *,
    refresh: bool = False,
    client: httpx.Client | None = None,
    cache_dir: Path | None = None,
    offline: bool | None = None,
) -> FetchResult:
    """Cache-first fetch. `refresh=True` re-downloads (falls back to the cache if the network fails).

    Offline (`DEMO_OFFLINE=1`): cache only, never touches the network.
    """
    nct = normalize_nct(nct_id)
    offline = demo_offline() if offline is None else offline
    cached = _read_cache(nct, cache_dir)
    if offline:
        if cached is None:
            raise OfflineCacheMiss(
                f"Offline demo mode: {nct} is not in the local cache. Cached studies: "
                + ", ".join(cached_study_ids(cache_dir)) + ".",
                {"nct_id": nct, "cached": cached_study_ids(cache_dir)},
            )
        return FetchResult(cached[0], True, cached[1])
    if cached is not None and not refresh:
        return FetchResult(cached[0], True, cached[1])

    own_client = client is None
    client = client or httpx.Client(
        timeout=TIMEOUT_S, headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )
    try:
        try:
            resp = _get_json(client, f"{API_BASE}/studies/{nct}", {"format": "json"})
        except RegistryUnavailable:
            if cached is not None:
                return FetchResult(cached[0], True, cached[1], stale_fallback=True)
            raise
        if resp.status_code == 404:
            raise StudyNotFound(f"{nct} was not found on ClinicalTrials.gov.", {"nct_id": nct})
        if resp.status_code != 200:
            raise RegistryUnavailable(
                f"ClinicalTrials.gov answered HTTP {resp.status_code} for {nct}.",
                {"nct_id": nct, "status": resp.status_code},
            )
        raw = resp.json()
        version: dict[str, Any] = {}
        try:
            v = _get_json(client, f"{API_BASE}/version")
            version = v.json() if v.status_code == 200 else {}
        except (RegistryUnavailable, ValueError):
            version = {}
    finally:
        if own_client:
            client.close()

    got = raw.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
    meta = {
        "nct_id": got or nct,
        "requested_id": nct,
        "source_url": f"{API_BASE}/studies/{nct}?format=json",
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "api_version": version.get("apiVersion"),
        "data_timestamp": version.get("dataTimestamp"),
        "attribution": "ClinicalTrials.gov, U.S. National Library of Medicine",
    }
    raw_p, meta_p = _cache_paths(nct, cache_dir or ctgov_write_dir())
    _atomic_write(raw_p, json.dumps(raw, ensure_ascii=False, indent=1))
    _atomic_write(meta_p, json.dumps(meta, indent=2))
    return FetchResult(raw, False, meta)


def fetch_study(nct_id: str) -> dict[str, Any]:
    """The raw study JSON (cache-first; `DEMO_OFFLINE=1` -> cache only)."""
    return fetch_study_result(nct_id).raw


def cached_study_ids(cache_dir: Path | None = None) -> list[str]:
    return sorted({p.stem for d in _read_dirs(cache_dir) for p in d.glob("NCT*.json") if NCT_RE.match(p.stem)})


# ---------------------------------------------------------------- mapping helpers
_PHASE_LABELS = {
    "EARLY_PHASE1": "Early Phase 1", "PHASE1": "Phase 1", "PHASE2": "Phase 2",
    "PHASE3": "Phase 3", "PHASE4": "Phase 4", "NA": "Not Applicable",
}


def map_phase(phases: list[str] | None) -> str | None:
    if not phases:
        return None
    labels = [_PHASE_LABELS.get(p, p) for p in phases]
    if len(labels) == 2 and all(lbl.startswith("Phase ") for lbl in labels):
        return f"{labels[0]}/{labels[1].removeprefix('Phase ')}"  # "Phase 2/3"
    return "/".join(labels)


def parse_partial_date(s: str | None) -> tuple[date | None, bool]:
    """'yyyy', 'yyyy-MM' or 'yyyy-MM-dd' -> (date, was_partial). Partial dates use day/month 1."""
    if not s:
        return None, False
    parts = s.split("-")
    try:
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2])), False
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1), True
        return date(int(parts[0]), 1, 1), True
    except ValueError:
        return None, False


# WHO INN stems for biologics. Checked in the opened sources:
#  - WHO, "The use of stems in the selection of INN for pharmaceutical substances" (2018),
#    https://www.who.int/docs/default-source/international-nonproprietary-names-(inn)/stembook-2018.pdf
#    "-mab: monoclonal antibodies"; "-cept: receptor molecules or membrane ligands" (lists aflibercept).
#  - WHO, 73rd INN Consultation executive summary (2021), https://www.who.int/publications/m/item/inn-21-533
#    new antibody suffixes -tug, -bart, -mig, -ment replace -mab.
_BIOLOGIC_STEMS = {
    "mab": "monoclonal antibody", "cept": "receptor molecule / fusion protein",
    "tug": "monoclonal antibody", "bart": "engineered antibody",
    "mig": "multispecific immunoglobulin", "ment": "antibody fragment",
}
_BIOLOGIC_STEM_RE = re.compile(r"\b[a-z]{3,}(" + "|".join(_BIOLOGIC_STEMS) + r")\b", re.I)
_NOT_INN = {"treatment", "supplement", "management", "placement", "assessment", "comment", "element", "segment", "concept", "accept", "except"}


def _inn_biologic_stem(name: str) -> str | None:
    for m in _BIOLOGIC_STEM_RE.finditer(name):
        word = m.group(0).lower()
        if word not in _NOT_INN:
            stem = m.group(1).lower()
            return f"{word} (-{stem}: {_BIOLOGIC_STEMS[stem]})"
    return None


def _investigational_interventions(arms_mod: dict[str, Any]) -> list[dict[str, Any]]:
    """Interventions given in an EXPERIMENTAL arm and not in every arm (i.e. not background therapy)."""
    interventions = [iv for iv in arms_mod.get("interventions", []) if "placebo" not in (iv.get("name") or "").lower()]
    arms = arms_mod.get("armGroups", [])
    if not arms:
        return interventions

    def key(iv: dict[str, Any]) -> str:
        return f"{iv.get('type', '').replace('_', ' ').title()}: {iv.get('name')}".lower()

    arm_sets = [{n.lower() for n in a.get("interventionNames", [])} for a in arms]
    exp_sets = [s for a, s in zip(arms, arm_sets, strict=True) if a.get("type") == "EXPERIMENTAL"]
    if not exp_sets:
        return interventions
    in_exp = [iv for iv in interventions if any(key(iv) in s for s in exp_sets)]
    in_all = {key(iv) for iv in interventions if all(key(iv) in s for s in arm_sets)} if len(arm_sets) > 1 else set()
    picked = [iv for iv in in_exp if key(iv) not in in_all]
    return picked or in_exp or interventions


def classify_drug_type(arms_mod: dict[str, Any]) -> tuple[str, str]:
    """-> (drug_type, plain-English basis). Registry type first, then WHO INN stems for DRUG entries."""
    inv = _investigational_interventions(arms_mod)
    if not inv:
        return "unknown", "no interventions listed in the registry"
    names = ", ".join(iv.get("name", "?") for iv in inv)
    types = {iv.get("type") for iv in inv}
    if "BIOLOGICAL" in types:
        return "biologic", f"registry intervention type BIOLOGICAL ({names})"
    for iv in inv:
        if iv.get("type") in {"DRUG", "COMBINATION_PRODUCT", None}:
            for n in [iv.get("name") or ""] + list(iv.get("otherNames") or []):
                stem = _inn_biologic_stem(n)
                if stem:
                    return "biologic", (
                        f"registry type {iv.get('type')}, but the INN stem marks a biologic: {stem} "
                        "(WHO INN stem book)"
                    )
    if "DRUG" in types:
        return "small_molecule", f"registry intervention type DRUG with no biologic INN stem ({names})"
    if "DEVICE" in types:
        return "device", f"registry intervention type DEVICE ({names})"
    if types <= {"BEHAVIORAL", "PROCEDURE", "OTHER", "DIETARY_SUPPLEMENT", "RADIATION", "DIAGNOSTIC_TEST"}:
        return "none", f"no drug or device intervention (types: {', '.join(sorted(t for t in types if t))})"
    return "unknown", f"intervention types {sorted(t for t in types if t)} not mapped"


def _n(k: int, word: str) -> str:
    return f"{k} {word}{'' if k == 1 else 's'}"


def _site_key(loc: dict[str, Any]) -> str:
    return "|".join(str(loc.get(k) or "") for k in ("facility", "city", "state", "zip", "country"))


def protocol_documents(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Study documents attached on ClinicalTrials.gov (URL only; the PDFs are third-party copyright)."""
    nct = raw["protocolSection"]["identificationModule"]["nctId"]
    docs = raw.get("documentSection", {}).get("largeDocumentModule", {}).get("largeDocs", [])
    return [
        {
            "label": d.get("label"),
            "type": d.get("typeAbbrev"),
            "has_protocol": bool(d.get("hasProtocol")),
            "date": d.get("date"),
            "filename": d.get("filename"),
            "size_bytes": d.get("size"),
            "url": LARGE_DOC_URL.format(last2=nct[-2:], nct=nct, filename=d.get("filename")),
        }
        for d in docs
        if d.get("filename")
    ]


# ---------------------------------------------------------------- mapping
NoteKind = Literal["fact", "missing", "assumption"]
# Notes that are not about one TrialDesign field (a failed live fetch, for example).
UNSCOPED_NOTE_FIELD = "_unscoped"


@dataclass(frozen=True)
class FieldNote:
    """One import note, tied to the design field it explains.

    `kind` is `fact` (what the registry states), `missing` (a field left empty) or `assumption`
    (a labelled fill-in). `clears_when_present` is true only while `field` sits in
    `missing_fields`: once that field is filled, the note no longer applies.
    """

    text: str
    field: str | None
    kind: NoteKind
    clears_when_present: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "kind": self.kind,
            # Boolean A8 already reads. True only for a labelled fill-in, not for a fact or a gap.
            "assumption": self.kind == "assumption",
            "text": self.text,
            "clears_when_present": self.clears_when_present,
        }


def note_payload(field_notes: list[FieldNote]) -> dict[str, Any]:
    """`notes` (plain strings, old clients) plus the same notes as objects, grouped by field."""
    rows = [n.as_dict() for n in field_notes]
    by_field: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        key = row["field"] if row["field"] else UNSCOPED_NOTE_FIELD
        by_field.setdefault(key, []).append(row)
    return {"notes": [row["text"] for row in rows], "field_notes": rows, "notes_by_field": by_field}


@dataclass
class ImportReport:
    design: TrialDesign
    field_notes: list[FieldNote] = field(default_factory=list)
    field_sources: dict[str, str] = field(default_factory=dict)  # TrialDesign field -> registry path or rule

    @property
    def notes(self) -> list[str]:
        return [n.text for n in self.field_notes]
    enrollment_type: str | None = None                      # "ACTUAL" | "ESTIMATED"
    drug_type_basis: str = ""
    visit_template_id: str | None = None
    geocoded_site_ids: list[str] = field(default_factory=list)
    unresolved_site_ids: list[str] = field(default_factory=list)
    sponsor: str | None = None
    collaborators: list[str] = field(default_factory=list)
    overall_status: str | None = None
    acronym: str | None = None
    dates: dict[str, str | None] = field(default_factory=dict)
    documents: list[dict[str, Any]] = field(default_factory=list)
    attribution: str = ""


def design_id_for(nct: str) -> str:
    return str(uuid.uuid5(_NS, f"ctgov:{nct}"))


def map_study_report(
    raw: dict[str, Any],
    *,
    geocoder: Geocoder | None = None,
    templates: TemplateLibrary | None = None,
    visits: list[Visit] | None = None,
    meta: dict[str, Any] | None = None,
) -> ImportReport:
    """Map a raw API v2 study to a `TrialDesign` plus a report of every assumption made.

    `visits`: a human-confirmed schedule (e.g. accepted protocol extraction). Without it, a
    default template is used and "visits" is listed in `missing_fields`.
    """
    ps = raw.get("protocolSection") or {}
    idm = ps.get("identificationModule") or {}
    nct = idm.get("nctId")
    if not nct:
        raise InsufficientRegistryData("The registry record has no NCT ID.")
    status = ps.get("statusModule") or {}
    design_mod = ps.get("designModule") or {}
    sponsor_mod = ps.get("sponsorCollaboratorsModule") or {}
    field_notes: list[FieldNote] = []

    def add(text: str, note_field: str | None, kind: NoteKind, *, clears: bool = False) -> None:
        field_notes.append(FieldNote(text, note_field, kind, clears))

    missing: list[str] = []
    src: dict[str, str] = {
        "registry_id": "protocolSection.identificationModule.nctId",
        "title": "protocolSection.identificationModule.briefTitle (+ acronym)",
    }

    title = idm.get("briefTitle") or idm.get("officialTitle") or nct
    acronym = idm.get("acronym")
    if acronym and acronym.lower() not in title.lower():
        title = f"{acronym}: {title}"

    phase = map_phase(design_mod.get("phases"))
    src["phase"] = "protocolSection.designModule.phases"
    if phase is None:
        missing.append("phase")
        add("Phase not given in the registry.", "phase", "missing", clears=True)

    conditions = list((ps.get("conditionsModule") or {}).get("conditions") or [])
    src["conditions"] = "protocolSection.conditionsModule.conditions"

    enr = design_mod.get("enrollmentInfo") or {}
    if enr.get("count") is None:
        raise InsufficientRegistryData(
            f"{nct} has no enrollment count in the registry; enter the target enrollment manually.",
            {"nct_id": nct},
        )
    enrollment = int(enr["count"])
    enrollment_type = enr.get("type")
    src["enrollment_target"] = f"protocolSection.designModule.enrollmentInfo.count ({enrollment_type or 'type not given'})"
    if enrollment_type == "ESTIMATED":
        add(
            f"Enrollment {enrollment} is the sponsor's anticipated target (ESTIMATED), not an actual count.",
            "enrollment_target", "fact",
        )
    elif enrollment_type == "ACTUAL":
        add(
            f"Enrollment {enrollment} is the actual number enrolled (ACTUAL).",
            "enrollment_target", "fact",
        )

    # --- dates -> duration
    start, start_partial = parse_partial_date((status.get("startDateStruct") or {}).get("date"))
    pcd, _ = parse_partial_date((status.get("primaryCompletionDateStruct") or {}).get("date"))
    end, end_partial = parse_partial_date((status.get("completionDateStruct") or {}).get("date"))
    end_field = "completionDateStruct"
    if end is None and pcd is not None:
        end, end_field = pcd, "primaryCompletionDateStruct"
        add(
            "No study completion date; duration uses the primary completion date.",
            "duration_months", "assumption",
        )
    dates = {
        "start": (status.get("startDateStruct") or {}).get("date"),
        "start_type": (status.get("startDateStruct") or {}).get("type"),
        "primary_completion": (status.get("primaryCompletionDateStruct") or {}).get("date"),
        "primary_completion_type": (status.get("primaryCompletionDateStruct") or {}).get("type"),
        "completion": (status.get("completionDateStruct") or {}).get("date"),
        "completion_type": (status.get("completionDateStruct") or {}).get("type"),
    }

    # --- per-patient schedule
    tw, tw_basis = treatment_weeks_from_registry(raw)
    template_id: str | None = None
    if visits is None:
        lib = templates or default_templates()
        sched = lib.build(phase, tw, tw_basis)
        visits = sched.visits
        template_id = sched.template_id
        missing.append("visits")
        add(
            f"Visit schedule is NOT in the registry: filled with assumed template '{sched.template_id}' "
            f"({len(visits)} visits over {sched.treatment_weeks:g} treatment weeks; length basis: "
            f"{sched.treatment_weeks_basis}). {sched.rationale} Import the protocol to replace it.",
            "visits", "assumption", clears=True,
        )
        src["visits"] = f"assumption: data/fixtures/visit_templates.yaml#{sched.template_id}"
    else:
        src["visits"] = "human-confirmed schedule (protocol extraction)"

    if start is not None and end is not None and end > start:
        duration = round((end - start).days / _DAYS_PER_MONTH, 1)
        src["duration_months"] = f"statusModule.startDateStruct -> statusModule.{end_field}"
        kinds = f"start {dates['start_type'] or '?'}, end {(status.get(end_field) or {}).get('type') or '?'}"
        add(
            f"Duration {duration} months = {start.isoformat()} to {end.isoformat()} ({kinds}).",
            "duration_months", "fact",
        )
        if start_partial or end_partial:
            add(
                "A registry date gave only year/month; the 1st of the month was assumed.",
                "duration_months", "assumption",
            )
    else:
        last_week = max((v.week for v in visits), default=0.0)
        duration = round(max(last_week, 1.0) / (52.1775 / 12), 1)
        missing.append("duration_months")
        src["duration_months"] = "assumption: per-patient schedule length (no usable registry dates)"
        add(
            f"No usable start/completion dates; duration set to the per-patient schedule length "
            f"({duration} months), which ignores the enrollment period.",
            "duration_months", "assumption", clears=True,
        )

    # --- intervention -> drug_type
    drug_type, basis = classify_drug_type(ps.get("armsInterventionsModule") or {})
    src["drug_type"] = "protocolSection.armsInterventionsModule.interventions (+ WHO INN stems)"
    if drug_type == "unknown":
        missing.append("drug_type")
        add(f"Drug type '{drug_type}': {basis}.", "drug_type", "missing", clears=True)
    else:
        add(f"Drug type '{drug_type}': {basis}.", "drug_type", "fact")

    # --- sites
    geocoder = geocoder or default_geocoder()
    locations = (ps.get("contactsLocationsModule") or {}).get("locations") or []
    sites: list[Site] = []
    geocoded: list[str] = []
    unresolved: list[str] = []
    precision_admin1 = 0
    seen: dict[str, int] = {}
    for i, loc in enumerate(locations):
        k = _site_key(loc)
        seen[k] = seen.get(k, 0) + 1
        sid = str(uuid.uuid5(_NS, f"ctgov:{nct}:site:{k}#{seen[k]}"))
        country = loc.get("country") or "Unknown"
        lat = lon = None
        gp = loc.get("geoPoint")
        if gp and gp.get("lat") is not None and gp.get("lon") is not None:
            lat, lon = float(gp["lat"]), float(gp["lon"])
        else:
            hit = geocoder.lookup(loc.get("city"), country, loc.get("state"))
            if hit is not None:
                lat, lon = hit.lat, hit.lon
                geocoded.append(sid)
                precision_admin1 += hit.precision == "admin1"
            else:
                unresolved.append(sid)
        sites.append(Site(
            id=sid,
            name=loc.get("facility") or f"Site {i + 1} ({loc.get('city') or country})",
            city=loc.get("city"),
            country=country,
            lat=lat,
            lon=lon,
            expected_enrollment=None,
        ))
    src["sites"] = "protocolSection.contactsLocationsModule.locations (facility, city, country, geoPoint)"
    if not sites:
        missing.append("sites")
        add("The registry lists no study locations.", "sites", "missing", clears=True)
    else:
        with_point = len(sites) - len(geocoded) - len(unresolved)
        add(
            f"{_n(len(sites), 'site')} from the registry; {with_point} with registry geoPoints.",
            "sites", "fact",
        )
        missing.append("sites.expected_enrollment")
        add(
            "Per-site enrollment is not in the registry (expected_enrollment left empty).",
            "sites.expected_enrollment", "missing", clears=True,
        )
    if geocoded:
        state_only = f"; {precision_admin1} only to state level" if precision_admin1 else ""
        add(
            f"{_n(len(geocoded), 'site')} had no registry geoPoint and were placed from city/state/country with the "
            f"offline GeoNames index (CC BY 4.0){state_only}.",
            "sites.lat_lon", "assumption",
        )
    if unresolved:
        missing.append("sites.lat_lon")
        add(
            f"{_n(len(unresolved), 'site')} could not be placed (no geoPoint, city not found); lat/lon left empty.",
            "sites.lat_lon", "missing", clears=True,
        )

    design = TrialDesign(
        id=design_id_for(nct),
        source="ctgov",
        registry_id=nct,
        title=title,
        phase=phase,
        conditions=conditions,
        enrollment_target=enrollment,
        duration_months=duration,
        sites=sites,
        visits=visits,
        drug_type=drug_type,  # type: ignore[arg-type]
        missing_fields=missing,
    )
    meta = meta or {}
    processed = meta.get("data_timestamp") or "unknown (not recorded at fetch time)"
    attribution = (
        f"Source: ClinicalTrials.gov ({STUDY_PAGE.format(nct=nct)}), U.S. National Library of Medicine. "
        f"Data processed by ClinicalTrials.gov: {processed}; fetched {meta.get('fetched_at', 'unknown')}. "
        "Modified by TrialPilot: mapped to a TrialDesign; visit schedule, per-site enrollment and missing "
        "coordinates are assumptions listed in the notes."
    )
    return ImportReport(
        design=design,
        field_notes=field_notes,
        field_sources=src,
        enrollment_type=enrollment_type,
        drug_type_basis=basis,
        visit_template_id=template_id,
        geocoded_site_ids=geocoded,
        unresolved_site_ids=unresolved,
        sponsor=(sponsor_mod.get("leadSponsor") or {}).get("name"),
        collaborators=[c.get("name") for c in sponsor_mod.get("collaborators", []) if c.get("name")],
        overall_status=status.get("overallStatus"),
        acronym=acronym,
        dates=dates,
        documents=protocol_documents(raw),
        attribution=attribution,
    )


def map_study(raw: dict[str, Any], **kwargs: Any) -> TrialDesign:
    return map_study_report(raw, **kwargs).design

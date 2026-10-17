"""Extract only repository CT.gov JSON; no importer, network or external dataset.

Sources are the importer's ctgov cache plus any records in peers/registry.
Requests re-read those original sources, so an empty registry directory is valid
and a stale derived snapshot never supplies a count.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from statistics import median

from ..errors import ApiError
from ..settings import REPO_ROOT
from .models import CohortRecord, Metric, PeerRow, RegistryCounts

FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"
CACHE_DIR = FIXTURES_DIR / "ctgov"
REGISTRY_DIR = FIXTURES_DIR / "peers" / "registry"
COHORT_FILE = FIXTURES_DIR / "peers" / "cohort.json"

MIN_PERCENTILE_PEERS = 5
CONDITION_ALIASES = {
    "copd": "copd",
    "chronic obstructive pulmonary disease": "copd",
    "chronic obstructive pulmonary disease copd": "copd",
    "copd chronic obstructive pulmonary disease": "copd",
    "pulmonary disease chronic obstructive": "copd",
    "pulmonary disease chronic obstructive copd": "copd",
    "copd pulmonary disease chronic obstructive": "copd",
    "dme": "diabetic_macular_edema",
    "diabetic macular edema": "diabetic_macular_edema",
    "diabetic macular edema dme": "diabetic_macular_edema",
}

LABELS: dict[Metric, str] = {
    "primary_outcomes": "Primary outcomes",
    "total_outcomes": "All outcomes",
    "inclusion_criteria": "Inclusion criteria lines",
    "exclusion_criteria": "Exclusion criteria lines",
    "eligibility_criteria": "All eligibility lines",
    "countries": "Countries",
    "sites": "Sites",
    "enrollment_target": "Target enrollment",
}
METHODS = {
    "source": "Only cached registry records: data/fixtures/ctgov/NCT*.json and "
              "data/fixtures/peers/registry/NCT*.json; .meta.json files are excluded. "
              "When an NCT is in both, the ctgov file is used. Counts describe the cached "
              "registry record, not edits to the saved design. An empty registry directory "
              "adds no peers; the local cache is not a complete registry population.",
    "cohort": "Exact normalized phase and condition_group of the saved design. Exclude its "
              "registry_id; count each other registry_id once. Unknown phase or condition has no peers.",
    "phase": "Normalize phase labels and Roman numerals; retain combined phases (Phase 2/3 is "
             "PHASE2/PHASE3, never PHASE3 alone).",
    "condition_group": "Use the first non-empty listed condition; normalize Unicode, case, "
                       "punctuation and whitespace. Map COPD, Chronic Obstructive Pulmonary "
                       "Disease, Pulmonary Disease, Chronic Obstructive and their combined "
                       "COPD spellings to copd; DME and Diabetic Macular Edema to "
                       "diabetic_macular_edema. No other condition (emphysema, pulmonary "
                       "hypertension, heart failure, ...) is merged into copd. Do not infer "
                       "disease from titles, eligibility text or sponsor.",
    "outcomes": "Count entries in primaryOutcomes; all outcomes = primaryOutcomes + "
                "secondaryOutcomes + otherOutcomes. A missing outcomesModule is unknown.",
    "eligibility": "Split eligibilityCriteria with splitlines(), trim each line, discard empty "
                   "lines. Exclude section headings beginning with optional 'Key' then "
                   "'Inclusion Criteria' or 'Exclusion Criteria'; headings set the section, "
                   "including repeated randomization sections. Count every remaining non-empty "
                   "line once in that section. Sub-bullets, continuation lines and internal "
                   "subheadings count separately. Total includes unsectioned lines. A missing "
                   "section is unknown, not zero. These are text-line counts, not adjudicated criteria.",
    "locations": "Sites = number of location entries, without deduplication. Countries = distinct "
                 "non-empty trimmed, case-folded location country strings. Missing locations are "
                 "unknown; countries are unknown if any listed location lacks a country.",
    "enrollment": "enrollment_reported is enrollmentInfo.count with its enrollment_type. "
                  "enrollment_target uses only ESTIMATED counts. ACTUAL counts are displayed "
                  "separately and never treated as planned targets; missing targets are null.",
    "comparison": "More/fewer/same compares the record count to the median of reported peer "
                  "counts, even in a small cohort. cohort_n is all matched peers; available_n "
                  "is peers reporting this metric. This is a descriptive comparison, not a quality score.",
    "percentile": "100 * (peers below + 0.5 * peers tied) / available_n. Return null and "
                  "insufficient_peers if cohort_n < 5 or available_n < 5; never interpret as quality.",
}
INTERPRETATION = "What might explain these differences? Complexity can have scientific reasons."


def normalize_phase(value: str | list[str] | None) -> str | None:
    if not value:
        return None
    if isinstance(value, list):
        value = "/".join(value)
    compact = re.sub(r"[\s_-]+", "", value).upper()
    if compact in {"NA", "NOTAPPLICABLE"}:
        return "NA"
    if compact in {"EARLYPHASE1", "EARLYPHASEI"}:
        return "EARLY_PHASE1"
    parts = compact.replace("PHASE", "").split("/")
    roman = {"I": "1", "II": "2", "III": "3", "IV": "4"}
    numbers = {roman.get(part, part) for part in parts}
    if numbers and numbers <= {"1", "2", "3", "4"}:
        return "/".join(f"PHASE{n}" for n in sorted(numbers))
    return None


def condition_group(conditions: list[str]) -> str | None:
    """Match explicit aliases of the first listed disease, never a later diagnosis."""
    first = next((c for c in conditions if c.strip()), None)
    if first is None:
        return None
    key = " ".join(re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", first).casefold()))
    return CONDITION_ALIASES.get(key, key.replace(" ", "_")) or None


def eligibility_counts(text: str | None) -> tuple[int | None, int | None, int | None]:
    if not text or not text.strip():
        return None, None, None
    counts: dict[str, int | None] = {"inclusion": None, "exclusion": None}
    section: str | None = None
    total = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        heading = re.match(r"^(?:key\s+)?(inclusion|exclusion)\s+criteria\b", line, re.I)
        if heading:
            section = heading.group(1).lower()
            if counts[section] is None:
                counts[section] = 0
            continue
        total += 1
        if section is not None:
            counts[section] = (counts[section] or 0) + 1
    return counts["inclusion"], counts["exclusion"], total


def source_label(path: Path) -> str:
    """ctgov files keep their bare name; other caches are named relative to data/fixtures."""
    if path.parent == CACHE_DIR or not path.is_relative_to(FIXTURES_DIR):
        return path.name
    return path.relative_to(FIXTURES_DIR).as_posix()


def source_paths(source_dirs: tuple[Path, ...] | None = None) -> list[Path]:
    """One registry file per NCT; the first directory listing an NCT wins."""
    if source_dirs is None:
        # Resolve at call time so isolated caches can exercise the same default path.
        source_dirs = (CACHE_DIR, REGISTRY_DIR)
    chosen: dict[str, Path] = {}
    for directory in source_dirs:
        for path in sorted(directory.glob("NCT*.json")):
            if re.fullmatch(r"NCT\d{8}\.json", path.name):
                chosen.setdefault(path.stem, path)
    return [chosen[stem] for stem in sorted(chosen)]


def read_record(path: Path) -> CohortRecord:
    """Extract one selected original, retaining its file hash and missing values."""
    try:
        source = path.read_bytes()
        ps = json.loads(source)["protocolSection"]
        registry_id = ps["identificationModule"]["nctId"]
        if registry_id != path.stem:
            raise ValueError("registry_id does not match source filename")
        design = ps.get("designModule") or {}
        outcomes = ps.get("outcomesModule")
        inclusion, exclusion, eligibility = eligibility_counts(
            (ps.get("eligibilityModule") or {}).get("eligibilityCriteria")
        )
        locations = (ps.get("contactsLocationsModule") or {}).get("locations")
        enrollment = design.get("enrollmentInfo") or {}
        countries = {loc["country"].strip().casefold() for loc in (locations or [])
                     if loc.get("country", "").strip()}
        return CohortRecord(
            registry_id=registry_id, source_file=source_label(path),
            source_sha256=hashlib.sha256(source).hexdigest(),
            phase=normalize_phase(design.get("phases")),
            condition_group=condition_group(
                (ps.get("conditionsModule") or {}).get("conditions") or []),
            counts=RegistryCounts(
                primary_outcomes=(len(outcomes.get("primaryOutcomes") or [])
                                  if outcomes is not None else None),
                total_outcomes=(sum(len(outcomes.get(key) or []) for key in (
                    "primaryOutcomes", "secondaryOutcomes", "otherOutcomes"))
                    if outcomes is not None else None),
                inclusion_criteria=inclusion, exclusion_criteria=exclusion,
                eligibility_criteria=eligibility,
                countries=(len(countries) if locations is not None and all(
                    loc.get("country", "").strip() for loc in locations) else None),
                sites=len(locations) if locations is not None else None,
                enrollment_target=(enrollment.get("count")
                                   if enrollment.get("type") == "ESTIMATED" else None),
            ),
            enrollment_reported=enrollment.get("count"),
            enrollment_type=enrollment.get("type"),
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ApiError(503, "peer_cache_invalid", "A cached registry record cannot be read.",
                       {"source_file": source_label(path)}) from exc


def load_cohort(source_dirs: tuple[Path, ...] | None = None) -> list[CohortRecord]:
    records = [read_record(path) for path in source_paths(source_dirs)]
    sizes = Counter((record.phase, record.condition_group) for record in records)
    for record in records:
        if record.phase is not None and record.condition_group is not None:
            record.cohort_n = sizes[record.phase, record.condition_group] - 1
    return records


def matching_peers(
    records: list[CohortRecord], phase: str | None, group: str | None,
    registry_id: str | None,
) -> list[CohortRecord]:
    if phase is None or group is None:
        return []
    return [record for record in records if record.registry_id != registry_id
            and record.phase == phase and record.condition_group == group]


def comparison_rows(
    subject: CohortRecord | None, peers: list[CohortRecord],
    phase: str | None, group: str | None,
) -> list[PeerRow]:
    rows = []
    for metric, label in LABELS.items():
        own = getattr(subject.counts, metric) if subject else None
        values = [value for peer in peers if (value := getattr(peer.counts, metric)) is not None]
        peer_median = float(median(values)) if values else None
        direction = None
        if own is not None and peer_median is not None:
            direction = "more" if own > peer_median else "fewer" if own < peer_median else "same"
        percentile = None
        if len(peers) < MIN_PERCENTILE_PEERS or len(values) < MIN_PERCENTILE_PEERS:
            status = "insufficient_peers"
            note = (f"{len(peers)} matched cached peers; {len(values)} report this metric. "
                    f"At least {MIN_PERCENTILE_PEERS} are required for a percentile.")
        elif subject is None:
            status, note = "record_not_cached", "No matching registry record exists in the cache."
        elif own is None:
            status, note = "not_reported", "This count is not reported in the cached record."
        else:
            status, note = "ok", "Descriptive position within the cached peers."
            percentile = 100 * (sum(v < own for v in values)
                                + 0.5 * sum(v == own for v in values)) / len(values)
        if own is None:
            note += " This record's count is unavailable."
        rows.append(PeerRow(
            metric=metric, label=label, own_count=own, cohort_n=len(peers),
            available_n=len(values), phase=phase, condition_group=group,
            source_file=subject.source_file if subject else None,
            peer_source_files=[p.source_file for p in peers], status=status,
            peer_median=peer_median, percentile=percentile, comparison=direction,
            question=f"Does this record list more or fewer {label.lower()} than the cached "
                     "peers in this phase and condition?", note=note,
        ))
    return rows


def snapshot() -> dict:
    return {"source_kind": "cached_registry", "methods": METHODS,
            "records": [record.model_dump() for record in load_cohort()]}


if __name__ == "__main__":
    COHORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    COHORT_FILE.write_text(json.dumps(snapshot(), indent=2) + "\n", encoding="utf-8")

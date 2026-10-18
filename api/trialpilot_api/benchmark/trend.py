"""Sponsor protocol-complexity trend: observed vs expected against industry, by 3-year start block.

Answers the "How Extra Is Your Trial?" starter sheet's pro-tip: compare one sponsor's registered
trials with what is expected for the same phase and disease area, block by block, instead of
comparing raw counts. Expected = industry median for the same phase and MeSH disease category,
computed from industry-led trials that do not involve the sponsor.

`fetch` downloads one public ClinicalTrials.gov v2 snapshot and writes a compact per-trial table
(raw pages stay in var/, which Git ignores). `analyze` is offline and deterministic. Registry
fields are sponsor-reported; this is a descriptive mirror, never a quality ranking.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import re
import time
import urllib.parse
import urllib.request
import zlib
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

import numpy as np

from ..settings import REPO_ROOT
from .cohort import eligibility_counts, normalize_phase

API = "https://clinicaltrials.gov/api/v2"
QUERY = ("AREA[LeadSponsorClass]INDUSTRY AND AREA[StudyType]INTERVENTIONAL AND "
         "(AREA[Phase]PHASE2 OR AREA[Phase]PHASE3) AND AREA[StartDate]RANGE[2010-01-01,2024-12-31]")
FIELDS = ("NCTId,Phase,StartDate,OverallStatus,LeadSponsorName,CollaboratorName,EnrollmentCount,"
          "PrimaryOutcomeMeasure,SecondaryOutcomeMeasure,OtherOutcomeMeasure,EligibilityCriteria,"
          "LocationCountry,ConditionMeshTerm,ConditionAncestorTerm")
PAGE_SIZE = 1000

RAW_DIR = REPO_ROOT / "var" / "complexity_raw"
TABLE = REPO_ROOT / "data" / "fixtures" / "complexity" / "industry_phase23_2010_2024.jsonl.gz"
META = TABLE.with_name("download_meta.json")
OUT_JSON = REPO_ROOT / "docs" / "complexity" / "complexity_trend.json"

SPONSOR = "Regeneron"
SPONSOR_PATTERN = re.compile(r"\bregeneron\b", re.I)
BLOCKS = ((2010, 2012), (2013, 2015), (2016, 2018), (2019, 2021), (2022, 2024))
# The registry query also matches Phase 1/2 records (they list PHASE2); they are left out.
PHASES = ("PHASE2", "PHASE2/PHASE3", "PHASE3")
DIMENSIONS = ("outcomes", "countries", "sites", "eligibility")
# Eligibility stays out of the composite: many sponsors register only "key" criteria.
COMPOSITE = ("outcomes", "countries", "sites")
GROUPS = ("industry", "sponsor_led", "sponsor_collaborator")
# Context only, never a reference: industry trials whose lead sponsor name has at least this many
# trials in the analysed window (raw names, not merged). Large sponsors run larger programmes.
LARGE_SPONSOR_MIN = 200
SUMMARY_GROUPS = ("industry", "large_sponsor_peers", "sponsor_led", "sponsor_collaborator")
MIN_CELL = 20          # reference trials needed for a phase x area median; else phase-only median
FEW_TRIALS = 10        # blocks below this are flagged, not hidden
BOOT = 2000
SEED = 7

# MeSH disease categories (tree C plus F03). C23 is attached to most records, so it only
# classifies a trial that has no other category.
MESH_AREAS = frozenset({
    "Infections", "Neoplasms", "Musculoskeletal Diseases", "Digestive System Diseases",
    "Stomatognathic Diseases", "Respiratory Tract Diseases", "Otorhinolaryngologic Diseases",
    "Nervous System Diseases", "Eye Diseases", "Urogenital Diseases", "Male Urogenital Diseases",
    "Female Urogenital Diseases and Pregnancy Complications", "Cardiovascular Diseases",
    "Hemic and Lymphatic Diseases",
    "Congenital, Hereditary, and Neonatal Diseases and Abnormalities",
    "Skin and Connective Tissue Diseases", "Nutritional and Metabolic Diseases",
    "Endocrine System Diseases", "Immune System Diseases", "Disorders of Environmental Origin",
    "Animal Diseases", "Occupational Diseases", "Chemically-Induced Disorders",
    "Wounds and Injuries", "Mental Disorders",
})
GENERIC_AREA = "Pathological Conditions, Signs and Symptoms"
UNCLASSIFIED = "Unclassified"
ABRIDGED = re.compile(r"\bkey\s+(?:inclusion|exclusion)\s+criteria\b|other\s+protocol[- ]defined",
                      re.I)


# ---------------------------------------------------------------- download

def _get(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json",
                                               "User-Agent": "TrialPilot complexity trend"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except OSError:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def fetch() -> dict[str, Any]:
    """Download every page of QUERY, keep raw pages in var/, write the compact table and meta."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    version = _get(f"{API}/version")
    started = datetime.now(UTC).isoformat(timespec="seconds")
    params = {"query.term": QUERY, "fields": FIELDS, "pageSize": PAGE_SIZE, "countTotal": "true"}
    total, token, page, studies = None, None, 0, []
    while True:
        query = dict(params, **({"pageToken": token} if token else {}))
        data = _get(f"{API}/studies?{urllib.parse.urlencode(query)}")
        total = data.get("totalCount", total)
        with gzip.open(RAW_DIR / f"page_{page:03d}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump(data, fh)
        studies.extend(data.get("studies", []))
        token, page = data.get("nextPageToken"), page + 1
        if not token:
            break
        time.sleep(0.3)
    end_version = _get(f"{API}/version")
    rows = [extract(s) for s in studies]
    write_table(rows)
    meta = {
        "query": QUERY, "fields": FIELDS, "endpoint": f"{API}/studies",
        "api_version": version.get("apiVersion"), "data_timestamp": version.get("dataTimestamp"),
        "data_timestamp_at_end": end_version.get("dataTimestamp"),
        "fetched_at": started, "total_count": total, "pages": page,
        "studies": len(studies), "unique_nct": len({r["nct"] for r in rows}),
    }
    META.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def write_table(rows: Iterable[dict[str, Any]]) -> None:
    TABLE.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: r["nct"])
    with gzip.GzipFile(TABLE, "wb", mtime=0) as raw:
        for row in ordered:
            raw.write((json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))


def read_table(path: Path = TABLE) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ---------------------------------------------------------------- per-trial counts

def disease_areas(meshes: list[str], ancestors: list[str]) -> list[str]:
    terms = set(meshes) | set(ancestors)
    areas = sorted(terms & MESH_AREAS)
    if areas:
        return areas
    return [GENERIC_AREA] if GENERIC_AREA in terms else [UNCLASSIFIED]


def extract(study: dict[str, Any]) -> dict[str, Any]:
    """Compact, registry-derived counts for one study. Unreported counts are None, never 0."""
    ps = study.get("protocolSection", {})
    cbm = study.get("derivedSection", {}).get("conditionBrowseModule", {})
    sponsors = ps.get("sponsorCollaboratorsModule", {})
    outcomes_module = ps.get("outcomesModule", {})
    n_outcomes = sum(len(outcomes_module.get(k) or [])
                     for k in ("primaryOutcomes", "secondaryOutcomes", "otherOutcomes"))
    text = ps.get("eligibilityModule", {}).get("eligibilityCriteria")
    _, _, n_criteria = eligibility_counts(text)
    locations = ps.get("contactsLocationsModule", {}).get("locations") or []
    countries = {loc["country"] for loc in locations if loc.get("country")}
    start = ps.get("statusModule", {}).get("startDateStruct", {}).get("date") or ""
    return {
        "nct": ps.get("identificationModule", {}).get("nctId"),
        "phase": normalize_phase(ps.get("designModule", {}).get("phases")),
        "start_year": int(start[:4]) if start[:4].isdigit() else None,
        "status": ps.get("statusModule", {}).get("overallStatus"),
        "lead": sponsors.get("leadSponsor", {}).get("name"),
        "collaborators": sorted(c["name"] for c in sponsors.get("collaborators") or []
                                if c.get("name")),
        "areas": disease_areas([m["term"] for m in cbm.get("meshes") or []],
                               [a["term"] for a in cbm.get("ancestors") or []]),
        "outcomes": n_outcomes or None,
        "eligibility": n_criteria or None,
        "eligibility_abridged": bool(text and ABRIDGED.search(text)),
        "sites": len(locations) or None,
        "countries": len(countries) or None,
    }


def group_of(row: dict[str, Any]) -> str:
    if SPONSOR_PATTERN.search(row.get("lead") or ""):
        return "sponsor_led"
    if any(SPONSOR_PATTERN.search(c) for c in row.get("collaborators") or []):
        return "sponsor_collaborator"
    return "industry"


def block_of(year: int | None) -> str | None:
    for lo, hi in BLOCKS:
        if year is not None and lo <= year <= hi:
            return f"{lo}-{hi}"
    return None


# ---------------------------------------------------------------- observed / expected

def reference_medians(rows: list[dict[str, Any]]) -> tuple[dict, dict]:
    """Industry (sponsor-free) medians per (phase, area, dim) with >= MIN_CELL trials, and per
    (phase, dim) as the fallback. A multi-area trial contributes to each of its areas."""
    cells: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    phases: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        if group_of(row) != "industry" or row["phase"] not in PHASES:
            continue
        for dim in DIMENSIONS:
            if row[dim] is None:
                continue
            phases[row["phase"], dim].append(row[dim])
            for area in row["areas"]:
                cells[row["phase"], area, dim].append(row[dim])
    cell_medians = {k: median(v) for k, v in cells.items() if len(v) >= MIN_CELL}
    phase_medians = {k: median(v) for k, v in phases.items() if v}
    return cell_medians, phase_medians


def expected(row: dict[str, Any], dim: str, cell_medians: dict,
             phase_medians: dict) -> tuple[float | None, bool]:
    """Mean of the phase x area medians over the trial's areas; phase median if none qualifies.
    Returns (expected, used_fallback)."""
    values = [cell_medians[k] for area in row["areas"]
              if (k := (row["phase"], area, dim)) in cell_medians]
    if values:
        return sum(values) / len(values), False
    return phase_medians.get((row["phase"], dim)), True


def ratios(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-trial observed/expected ratios plus the composite (geometric mean of COMPOSITE)."""
    cell_medians, phase_medians = reference_medians(rows)
    out = []
    for row in rows:
        block = block_of(row["start_year"])
        if block is None or row["phase"] not in PHASES:
            continue
        item = {"nct": row["nct"], "group": group_of(row), "lead": row["lead"], "block": block,
                "phase": row["phase"], "eligibility_abridged": row["eligibility_abridged"],
                "fallback": []}
        for dim in DIMENSIONS:
            exp, fell_back = expected(row, dim, cell_medians, phase_medians)
            obs = row[dim]
            item[dim] = obs / exp if obs is not None and exp else None
            if fell_back and item[dim] is not None:
                item["fallback"].append(dim)
        parts = [item[d] for d in COMPOSITE]
        item["composite"] = (math.exp(sum(math.log(p) for p in parts) / len(parts))
                             if all(p is not None for p in parts) else None)
        out.append(item)
    return out


# ---------------------------------------------------------------- summaries

def _rng(*key: str) -> np.random.Generator:
    return np.random.default_rng([SEED, zlib.crc32("|".join(key).encode("utf-8"))])


def median_ci(values: list[float], boot: int, *key: str) -> tuple[float, list[float] | None]:
    """Median and percentile-bootstrap 95% interval (seeded per key; boot=0 skips the interval)."""
    x = np.asarray(values, dtype=float)
    point = float(np.median(x))
    if boot <= 0 or x.size < 2:
        return point, None
    rng, meds = _rng(*key), []
    for start in range(0, boot, 250):
        idx = rng.integers(0, x.size, size=(min(250, boot - start), x.size))
        meds.append(np.median(x[idx], axis=1))
    lo, hi = np.percentile(np.concatenate(meds), [2.5, 97.5])
    return point, [float(lo), float(hi)]


def relative_ci(a: list[float], b: list[float], boot: int,
                *key: str) -> tuple[float, list[float] | None]:
    """Ratio of medians a/b with an independent two-sample bootstrap interval."""
    xa, xb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    point = float(np.median(xa) / np.median(xb))
    if boot <= 0 or xa.size < 2 or xb.size < 2:
        return point, None
    rng, rel = _rng(*key), []
    for start in range(0, boot, 250):
        k = min(250, boot - start)
        ma = np.median(xa[rng.integers(0, xa.size, size=(k, xa.size))], axis=1)
        mb = np.median(xb[rng.integers(0, xb.size, size=(k, xb.size))], axis=1)
        rel.append(ma / mb)
    lo, hi = np.percentile(np.concatenate(rel), [2.5, 97.5])
    return point, [float(lo), float(hi)]


def analyze(rows: list[dict[str, Any]], boot: int = BOOT) -> dict[str, Any]:
    items = ratios(rows)
    leads = Counter(it["lead"] for it in items if it["group"] == "industry")
    large = {lead for lead, n in leads.items() if n >= LARGE_SPONSOR_MIN}
    metrics = ("composite", *DIMENSIONS)
    blocks = [f"{lo}-{hi}" for lo, hi in BLOCKS]
    by: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    abridged: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for it in items:
        groups = [it["group"]] + (["large_sponsor_peers"] if it["lead"] in large else [])
        for group in groups:
            for period in (it["block"], "all"):
                abridged[group, period].append(it["eligibility_abridged"])
                for m in metrics:
                    if it[m] is not None:
                        by[group, period, m].append(it[m])
                        if m == "eligibility" and not it["eligibility_abridged"]:
                            by[group, period, "eligibility_full_only"].append(it[m])

    series, relative = [], []
    for group in SUMMARY_GROUPS:
        for period in (*blocks, "all"):
            for m in (*metrics, "eligibility_full_only"):
                vals = by.get((group, period, m), [])
                if not vals:
                    continue
                point, ci = median_ci(vals, boot, group, period, m)
                series.append({"group": group, "period": period, "metric": m, "n": len(vals),
                               "median_ratio": round(point, 4),
                               "ci95": [round(v, 4) for v in ci] if ci else None,
                               "few_trials": len(vals) < FEW_TRIALS})
                ref = by.get(("industry", period, m), [])
                if group != "industry" and ref:
                    rel, rci = relative_ci(vals, ref, boot, "rel", group, period, m)
                    relative.append({"group": group, "period": period, "metric": m,
                                     "n": len(vals), "n_industry": len(ref),
                                     "relative_to_industry": round(rel, 4),
                                     "ci95": [round(v, 4) for v in rci] if rci else None,
                                     "few_trials": len(vals) < FEW_TRIALS})
    counts = {g: sum(1 for it in items if it["group"] == g) for g in GROUPS}
    counts["large_sponsor_peers"] = sum(1 for it in items if it["lead"] in large)
    return {
        "sponsor": SPONSOR,
        "blocks": blocks,
        "phases": list(PHASES),
        "large_sponsor_peers": sorted(large),
        "trials_in_window": len(items),
        "trials_by_group": counts,
        "phase_area_cells_used": len(reference_medians(rows)[0]),
        "fallback_ratios": sum(len(it["fallback"]) for it in items),
        "eligibility_abridged_share": [
            {"group": g, "period": p, "n": len(v), "share": round(sum(v) / len(v), 4)}
            for (g, p), v in sorted(abridged.items()) if v],
        "series": series,
        "relative_to_industry": relative,
        "bootstrap": {"resamples": boot, "seed": SEED, "interval": "percentile 95%"},
    }


def build_report(rows: list[dict[str, Any]], meta: dict[str, Any],
                 boot: int = BOOT) -> dict[str, Any]:
    return {
        "generated_by": "python -m trialpilot_api.benchmark.trend analyze",
        "source": meta,
        "definitions": {
            "groups": {
                "industry": "Industry-led trials with no Regeneron lead or collaborator.",
                "sponsor_led": "Lead sponsor name contains 'Regeneron'.",
                "sponsor_collaborator": "Regeneron listed as collaborator, partner leads "
                                        "(for example Sanofi-led dupilumab trials).",
                "large_sponsor_peers": f"Context subset of industry: lead sponsors with >= "
                                       f"{LARGE_SPONSOR_MIN} analysed trials (raw names).",
            },
            "dimensions": {
                "outcomes": "Registered primary + secondary + other outcome measures.",
                "countries": "Distinct countries among registered locations.",
                "sites": "Registered location entries.",
                "eligibility": "Non-empty criteria lines (same rule as PeerMirror); "
                               "excluded from the composite because abridged 'key criteria' "
                               "postings undercount.",
            },
            "expected": f"Mean over the trial's MeSH disease categories of the industry median "
                        f"for the same phase and category (>= {MIN_CELL} reference trials); "
                        f"otherwise the industry median for the phase.",
            "ratio": "observed / expected; 1.0 = as expected for phase and disease area.",
            "composite": "Geometric mean of the outcomes, countries and sites ratios.",
            "periods": "3-year blocks by registered start date; 'all' pools 2010-2024.",
            "phases": "Phase 2, Phase 2/3 and Phase 3, each with its own expectation; "
                      "Phase 1/2 records matched by the query are excluded.",
        },
        "results": analyze(rows, boot),
        "caveats": [
            "Registry fields are sponsor-reported and incomplete; counts are proxies for "
            "protocol complexity, not the protocol itself.",
            "A ratio above 1 is a question for the design team, not a quality judgment; "
            "complexity can be scientifically justified.",
            "Phase and MeSH category do not capture indication severity, endpoint type or "
            "regional strategy; residual case-mix differences remain.",
            "Blocks with fewer than 10 trials are flagged; read their intervals, not points.",
        ],
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download the registry snapshot (network)")
    run = sub.add_parser("analyze", help="compute the report from the committed table")
    run.add_argument("--boot", type=int, default=BOOT)
    run.add_argument("--output", type=Path, default=OUT_JSON)
    args = parser.parse_args(argv)
    if args.cmd == "fetch":
        print(json.dumps(fetch(), indent=2))
        return
    meta = json.loads(META.read_text(encoding="utf-8"))
    report = build_report(read_table(), meta, args.boot)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output}")


if __name__ == "__main__":
    main()

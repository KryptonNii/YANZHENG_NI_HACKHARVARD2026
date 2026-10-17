"""Rebuild the published trials as TrialPilot `TrialDesign`s (source = "published_paper").

The YAML holds the design, an inputs ledger (paper vs assumption for every input) and trial-specific
activity reported by the paper (`activity_overrides`, applied as point parameters in the engine runs).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from trialpilot_contracts import Parameter, Procedure, Site, TrialDesign, Visit

PAPER_URL = "https://bmjopen.bmj.com/content/14/1/e075755"
PAPER_TITLE = "Griffiths J, Fox L, Williamson PR et al. BMJ Open 2024;14:e075755"

PROCEDURE_LABELS = {
    "drug_dispensing": "Study drug dispensing",
    "ct_scan": "CT scan",
    "blood_draw": "Research blood sample",
    "mammogram": "Mammogram",
}


@dataclass(frozen=True)
class DesignInput:
    field: str
    value: str
    origin: str  # "paper" | "assumption"
    ref: str


@dataclass(frozen=True)
class PublishedDesign:
    trial_id: str
    design: TrialDesign
    inputs: tuple[DesignInput, ...]
    activity_overrides: dict[str, Parameter]


def _sites(d: dict[str, Any]) -> list[Site]:
    if "sites" in d:
        return [Site(**s) for s in d["sites"]]
    g = d["generated_sites"]
    return [
        Site(id=g["id"].format(n=n), name=g["name"].format(n=n), country=g["country"])
        for n in range(1, int(g["count"]) + 1)
    ]


def _visits(schedule: dict[str, Any]) -> list[Visit]:
    n_visits = int(schedule["visits"])
    first = float(schedule.get("first_week", 0))
    step = float(schedule["every_weeks"])
    at: dict[str, list[int]] = {k: list(v) for k, v in schedule.get("procedures_at", {}).items()}
    temps: dict[str, str] = dict(schedule.get("sample_procedures", {}))
    visits: list[Visit] = []
    for i in range(1, n_visits + 1):
        codes = list(schedule.get("procedures_all", [])) + [c for c, nums in at.items() if i in nums]
        procs = [
            Procedure(code=c, label=PROCEDURE_LABELS.get(c, c), ships_sample=c in temps,
                      sample_temp=temps.get(c))  # type: ignore[arg-type]
            for c in codes
        ]
        visits.append(Visit(number=i, label=f"Visit {i}", week=first + (i - 1) * step, procedures=procs))
    return visits


def _override_param(pid: str, raw: dict[str, Any], trial_id: str, unit: str) -> Parameter:
    v = float(raw["value"])
    return Parameter(
        id=pid, label=f"{trial_id.upper()} reported activity: {pid}", value_low=v, value_mid=v, value_high=v,
        unit=unit, source_title=f"{PAPER_TITLE}, {raw['ref']}", source_url=PAPER_URL, source_year=2024,
        region="GB",
    )


def load_design(path: Path, trial_id: str, library: dict[str, Parameter] | None = None) -> PublishedDesign:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    d = dict(doc["design"])
    design = TrialDesign(
        id=d["id"], source=d["source"], registry_id=d["registry_id"], title=d["title"], phase=d["phase"],
        conditions=d.get("conditions", []), enrollment_target=int(d["enrollment_target"]),
        duration_months=float(d["duration_months"]), sites=_sites(d), visits=_visits(d["schedule"]),
        drug_type=d["drug_type"], missing_fields=list(d.get("missing_fields", [])),
    )
    inputs = tuple(DesignInput(**{k: str(v) for k, v in i.items()}) for i in doc.get("inputs", []))
    overrides: dict[str, Parameter] = {}
    for pid, raw in (doc.get("activity_overrides") or {}).items():
        unit = library[pid].unit if library and pid in library else "as_library"
        overrides[pid] = _override_param(pid, raw, trial_id, unit)
    return PublishedDesign(trial_id=trial_id, design=design, inputs=inputs, activity_overrides=overrides)


def load_paper_factor_overrides(path: Path) -> dict[str, Parameter]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, Parameter] = {}
    for pid, raw in doc.items():
        v = float(raw["value"])
        out[pid] = Parameter(
            id=pid, label=f"Paper's factor for {pid}", value_low=v, value_mid=v, value_high=v, unit=raw["unit"],
            source_title=f"{PAPER_TITLE}, {raw['ref']}", source_url=PAPER_URL, source_year=2024, region="GB",
        )
    return out

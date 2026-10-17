"""Default visit schedules from `data/fixtures/visit_templates.yaml` (every template is an assumption)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ._contracts import Visit
from .paths import fixtures_dir
from .procedures import Vocabulary, default_vocabulary

_WEEKS_PER_MONTH = 52.1775 / 12  # 365.25 / 7 / 12


@dataclass(frozen=True)
class TemplateSchedule:
    template_id: str
    visits: list[Visit]
    treatment_weeks: float
    treatment_weeks_basis: str  # "registry: <time frame>" or "assumption: template default"
    rationale: str


_UNITS = {"week": 1.0, "month": _WEEKS_PER_MONTH, "day": 1 / 7, "year": 52.1775}
_NUM_LIST = r"(\d+(?:\.\d+)?(?:\s*(?:,|and|&|or|to|-)\s*\d+(?:\.\d+)?)*)"


def _parse_timeframe_weeks(text: str) -> float | None:
    """Largest explicit time point in a registry time frame, in weeks.

    'Baseline (Day 1) to Week 52' -> 52; 'Weeks 2, 4, 8, 12, 24, 36 and 52' -> 52; '12 months' -> 52.2.
    """
    t = text.lower()
    found: list[float] = []
    for unit, factor in _UNITS.items():
        for m in re.finditer(rf"\b{unit}s?\s*{_NUM_LIST}", t):  # "week 52", "weeks 2, 4 and 52"
            found += [float(x) * factor for x in re.findall(r"\d+(?:\.\d+)?", m.group(1))]
        for m in re.finditer(rf"(\d+(?:\.\d+)?)\s*-?\s*{unit}s?\b", t):  # "52 weeks", "12-month"
            found.append(float(m.group(1)) * factor)
    return round(max(found), 1) if found else None


def treatment_weeks_from_registry(raw: dict[str, Any]) -> tuple[float | None, str | None]:
    """Per-patient participation hinted by the longest primary/secondary outcome time frame (registry data)."""
    om = raw.get("protocolSection", {}).get("outcomesModule", {})
    best: tuple[float, str] | None = None
    for kind in ("primaryOutcomes", "secondaryOutcomes"):
        for o in om.get(kind, []):
            tf = o.get("timeFrame") or ""
            w = _parse_timeframe_weeks(tf)
            if w is not None and w > 0 and (best is None or w > best[0]):
                best = (w, f"{kind[:-8]} outcome time frame '{tf[:120]}'")
    return (best[0], best[1]) if best else (None, None)


class TemplateLibrary:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or fixtures_dir() / "visit_templates.yaml"
        doc = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        self.version = int(doc.get("version", 1))
        self.templates: list[dict[str, Any]] = doc["templates"]
        for t in self.templates:
            if t.get("assumption") is not True or not (t.get("rationale") or "").strip():
                raise ValueError(f"visit template {t.get('id')!r} must be assumption: true with a rationale")

    def pick(self, phase: str | None) -> dict[str, Any]:
        for t in self.templates:
            if phase and phase in t.get("phases", []):
                return t
        return next(t for t in self.templates if t["id"] == "generic_default")

    def build(
        self,
        phase: str | None,
        treatment_weeks: float | None,
        treatment_basis: str | None = None,
        vocab: Vocabulary | None = None,
    ) -> TemplateSchedule:
        vocab = vocab or default_vocabulary()
        t = self.pick(phase)
        mid = {k: v["mid"] for k, v in t.items() if isinstance(v, dict) and "mid" in v}
        if treatment_weeks is None:
            weeks = float(mid["default_treatment_weeks"])
            basis = f"assumption: template {t['id']} default ({weeks:g} weeks)"
        else:
            weeks = float(treatment_weeks)
            basis = f"registry {treatment_basis}"

        def procs(kind: str) -> list[Any]:
            return [vocab.procedure_for_code(c) for c in t["procedures"][kind]]

        rows: list[tuple[str, float, str]] = [
            ("Screening", float(mid["screening_week"]), "screening"),
            ("Baseline / Day 1", 0.0, "baseline"),
        ]
        w = 0.0
        while True:
            step = mid["dense_interval_weeks"] if w < mid["dense_phase_until_week"] else mid["sparse_interval_weeks"]
            w += step
            if w >= weeks - 1e-9:
                break
            rows.append((f"Week {w:g}", w, "treatment"))
        rows.append((f"End of treatment (Week {weeks:g})", weeks, "end_of_treatment"))
        fu = weeks + float(mid["follow_up_weeks_after_last"])
        rows.append((f"Follow-up (Week {fu:g})", fu, "follow_up"))
        visits = [
            Visit(number=i, label=label, week=week, procedures=procs(kind))
            for i, (label, week, kind) in enumerate(rows, start=1)
        ]
        return TemplateSchedule(t["id"], visits, weeks, basis, " ".join(t["rationale"].split()))


@lru_cache(maxsize=1)
def default_templates() -> TemplateLibrary:
    return TemplateLibrary()

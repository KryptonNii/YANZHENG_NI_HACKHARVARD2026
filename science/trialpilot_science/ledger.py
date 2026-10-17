"""Load a transcribed calculation ledger (science/data/<trial>_ledger.yaml) and redo its arithmetic.

A line is `kg CO2e = product(qty) / qty_div x factor`. `reported_kg` is what the paper printed.
`correction` (optional) either replaces the quantity (`qty`, `qty_div`) or drops the line (`exclude: true`),
always with the id of a documented finding.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from trialpilot_contracts import CARBON_MODULES


class LedgerError(ValueError):
    """The ledger file is inconsistent (unknown module, duplicate id, dangling finding, ...)."""


@dataclass(frozen=True)
class Correction:
    finding: str
    reason: str
    exclude: bool = False
    qty: tuple[float, ...] | None = None
    qty_div: float = 1.0


@dataclass(frozen=True)
class Line:
    id: str
    module: str
    page: str
    item: str
    qty: tuple[float, ...]
    qty_div: float
    qty_unit: str
    factor: float
    factor_key: str
    reported_kg: float
    qty_note: str = ""
    correction: Correction | None = None

    @property
    def activity(self) -> float:
        """Activity quantity exactly as the paper states it."""
        return math.prod(self.qty) / self.qty_div

    @property
    def recomputed_kg(self) -> float:
        """Paper's activity x paper's factor, recomputed by us."""
        return self.activity * self.factor

    @property
    def corrected_activity(self) -> float | None:
        """Activity after our documented correction; None if the line is dropped."""
        c = self.correction
        if c is None:
            return self.activity
        if c.exclude:
            return None
        assert c.qty is not None
        return math.prod(c.qty) / c.qty_div

    @property
    def corrected_kg(self) -> float:
        a = self.corrected_activity
        return 0.0 if a is None else a * self.factor


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    lines: tuple[str, ...]
    summary: str
    detail: str = ""


@dataclass(frozen=True)
class Ledger:
    trial: dict[str, Any]
    published_total_kg: float
    published_total_main_text_kg: float
    published_modules: dict[str, float]
    figure_modules: dict[str, float]
    findings: tuple[Finding, ...]
    lines: tuple[Line, ...]
    path: Path = field(compare=False)

    @property
    def id(self) -> str:
        return str(self.trial["id"])

    def modules(self) -> list[str]:
        """Modules in §6 order that the paper reports or that have lines."""
        present = set(self.published_modules) | {ln.module for ln in self.lines}
        return [m for m in CARBON_MODULES if m in present]

    def lines_in(self, module: str) -> list[Line]:
        return [ln for ln in self.lines if ln.module == module]

    def recomputed_by_module(self) -> dict[str, float]:
        return {m: sum(ln.recomputed_kg for ln in self.lines_in(m)) for m in self.modules()}

    def corrected_by_module(self) -> dict[str, float]:
        return {m: sum(ln.corrected_kg for ln in self.lines_in(m)) for m in self.modules()}

    def finding(self, fid: str) -> Finding:
        for f in self.findings:
            if f.id == fid:
                return f
        raise KeyError(fid)


def _floats(value: Any, where: str) -> tuple[float, ...]:
    if not isinstance(value, list) or not value:
        raise LedgerError(f"{where}: qty must be a non-empty list of numbers")
    out = tuple(float(v) for v in value)
    if not all(math.isfinite(v) and v >= 0 for v in out):
        raise LedgerError(f"{where}: qty values must be finite and >= 0")
    return out


def load_ledger(path: Path) -> Ledger:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    pub = doc["published"]
    findings = tuple(
        Finding(id=f["id"], severity=f["severity"], lines=tuple(f.get("lines", [])),
                summary=f["summary"], detail=str(f.get("detail", "")).strip())
        for f in doc.get("findings", [])
    )
    finding_ids = {f.id for f in findings}
    lines: list[Line] = []
    seen: set[str] = set()
    for raw in doc["lines"]:
        lid = raw["id"]
        where = f"{path.name}:{lid}"
        if lid in seen:
            raise LedgerError(f"{where}: duplicate line id")
        seen.add(lid)
        if raw["module"] not in CARBON_MODULES:
            raise LedgerError(f"{where}: unknown module {raw['module']!r}")
        corr = None
        if raw.get("correction"):
            c = raw["correction"]
            if c["finding"] not in finding_ids:
                raise LedgerError(f"{where}: correction cites unknown finding {c['finding']!r}")
            corr = Correction(
                finding=c["finding"], reason=c["reason"], exclude=bool(c.get("exclude", False)),
                qty=None if c.get("exclude") else _floats(c["qty"], where + ".correction"),
                qty_div=float(c.get("qty_div", 1.0)),
            )
        lines.append(Line(
            id=lid, module=raw["module"], page=str(raw["page"]), item=raw["item"],
            qty=_floats(raw["qty"], where), qty_div=float(raw.get("qty_div", 1.0)),
            qty_unit=raw["qty_unit"], factor=float(raw["factor"]), factor_key=raw["factor_key"],
            reported_kg=float(raw["reported_kg"]), qty_note=str(raw.get("qty_note", "")), correction=corr,
        ))
    for f in findings:
        for lid in f.lines:
            if lid not in seen:
                raise LedgerError(f"{path.name}: finding {f.id} cites unknown line {lid!r}")
    modules = {str(k): float(v) for k, v in pub["modules"].items()}
    for m in modules:
        if m not in CARBON_MODULES:
            raise LedgerError(f"{path.name}: unknown published module {m!r}")
    return Ledger(
        trial=dict(doc["trial"]),
        published_total_kg=float(pub["total_kg"]),
        published_total_main_text_kg=float(pub["total_main_text_kg"]),
        published_modules=modules,
        figure_modules={str(k): float(v) for k, v in pub.get("figure_modules", {}).items()},
        findings=findings,
        lines=tuple(lines),
        path=path,
    )

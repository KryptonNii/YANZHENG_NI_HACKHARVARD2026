"""/api/export/scenario/{id}.csv | .pdf — design report for one saved scenario.

Contents: scenario + design identity, the design's missing_fields, levers, the six metrics
(P10/P50/P90), module breakdown, forecast and supply when the result has them, warnings and
assumptions, provenance formulas, every parameter used with its source (or its assumption
rationale), and the signature manifestation (signer, role, meaning, UTC time).
The CSV is one table with a `section` column so nothing is lost when it is filtered.
"""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlmodel import Session

from ._contracts import ApprovalRequest, Levers, Parameter, ScenarioResult
from .db import ScenarioRow, get_session, utcnow_iso
from .deps import services
from .engine_adapter import METRICS
from .errors import ApiError
from .routes_designs import load_design
from .routes_scenarios import sync_status

router = APIRouter(prefix="/api/export", tags=["export"])

METRIC_LABELS = {
    "cost_usd": "Cost",
    "site_staff_hours": "Site staff time",
    "patient_travel_hours": "Patient travel time",
    "co2e_kg": "Carbon",
    "duration_months": "Duration",
    "drug_waste_share": "Drug waste share",
}


def _gather(svc: Any, session: Session, scenario_id: str) -> dict[str, Any]:
    row = session.get(ScenarioRow, scenario_id)
    if row is None:
        raise ApiError(404, "scenario_not_found", f"No saved scenario with id {scenario_id!r}.",
                       {"scenario_id": scenario_id})
    approval: ApprovalRequest | None = sync_status(svc, session, row)
    result = ScenarioResult.model_validate_json(row.result)
    provenance = [pi for m in result.modules for pi in m.provenance]
    for view in (result.forecast, result.supply):
        if view is not None:
            provenance.extend(view.provenance)
    used_ids = sorted({pid for pi in provenance for pid in pi.parameter_ids})
    stored = svc.params.params_for_set(row.parameter_set_version)
    notes: list[str] = []
    if stored is None:
        stored = list(svc.params.current().params.values())
        notes.append(f"Parameter set {row.parameter_set_version} is not stored in this database; "
                     "parameter values below are from the current library.")
    by_id = {p.id: p for p in stored}
    params: list[Parameter] = [by_id[i] for i in used_ids if i in by_id]
    missing = [i for i in used_ids if i not in by_id]
    if missing:
        notes.append(f"Parameters referenced by provenance but not found: {', '.join(missing)}")
    assumptions = sorted({a for pi in provenance for a in pi.assumptions})
    try:
        _, design = load_design(session, row.design_id, row.design_version)
        missing_fields = list(design.missing_fields)
    except ApiError as exc:
        missing_fields = []
        notes.append(exc.message)
    return {
        "row": row, "result": result, "levers": Levers.model_validate_json(row.levers),
        "approval": approval, "params": params, "assumptions": assumptions, "notes": notes,
        "missing_fields": missing_fields, "generated_at": utcnow_iso(),
    }


def _write_range(w: Any, section: str, key: str, metric: Any, detail: str = "") -> None:
    w.writerow([section, key, _num(metric.p10), _num(metric.p50), _num(metric.p90),
                metric.unit, detail])


def _write_detail_views(w: Any, result: ScenarioResult) -> None:
    """Forecast and supply as stored. Null percentiles stay 'unknown'; a missing view is
    'not reported' and is not filled with zeros."""
    for section, view in (("forecast", result.forecast), ("supply", result.supply)):
        if view is not None:
            for pi in view.provenance:
                w.writerow(["provenance", f"{section}:{pi.formula_id}", "", "", "", "",
                            f"{pi.description} | parameters: {', '.join(pi.parameter_ids)}"])
            for key in ("draws_requested", "draws_used", "curve_draws_used"):
                if hasattr(view, key):
                    value = getattr(view, key)
                    w.writerow([section, key, "", "", "", "count",
                                "unknown" if value is None else value])
    forecast = result.forecast
    if forecast is None:
        w.writerow(["forecast", "detail", "", "", "", "", "not reported"])
    else:
        _write_range(w, "forecast", "months_to_full_enrollment", forecast.months_to_full_enrollment)
        for name, metric in forecast.milestone_dates.items():
            _write_range(w, "forecast", f"milestone.{name}", metric, "months from study start")
        for month, p10, p50, p90 in forecast.enrollment_curve:
            w.writerow(["forecast", "enrollment_curve", _num(p10), _num(p50), _num(p90),
                        "patients", f"month {month}"])
    supply = result.supply
    if supply is None:
        w.writerow(["supply", "detail", "", "", "", "", "not reported"])
    else:
        for key in ("kits_needed", "kits_produced", "kits_wasted", "waste_share", "shipments"):
            _write_range(w, "supply", key, getattr(supply, key))
        w.writerow(["supply", "stockout_probability", "", "", "", "share",
                    supply.stockout_probability])


def _filename(row: ScenarioRow, ext: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", row.name).strip("-").lower()[:60] or "scenario"
    return f"trialpilot-{slug}-v{row.version}.{ext}"


# ------------------------------------------------------------------------------------------ CSV
def _known(v: float | None) -> bool:
    return v is not None and math.isfinite(v)


def _num(v: float | None) -> float | str:
    """Unknown (contract v2: None, = a missing input) is written as 'unknown', never 0."""
    return v if v is not None and _known(v) else "unknown"


def build_csv(data: dict[str, Any]) -> str:
    row: ScenarioRow = data["row"]
    result: ScenarioResult = data["result"]
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["section", "key", "p10", "p50", "p90", "unit", "detail"])
    meta = {
        "scenario_id": row.id, "name": row.name, "version": row.version, "status": row.status,
        "author": row.author, "created_at": row.created_at, "design_id": row.design_id,
        "design_version": row.design_version, "design_hash": row.design_hash,
        "parameter_set_version": row.parameter_set_version, "seed": row.seed,
        "draws": row.draws, "record_hash": row.record_hash,
        "computed_at": result.computed_at.isoformat(), "generated_at": data["generated_at"],
    }
    for k, v in meta.items():
        w.writerow(["scenario", k, "", "", "", "", v])
    w.writerow(["design", "missing_fields", "", "", "", "",
                "; ".join(data["missing_fields"])])
    for k, v in data["levers"].model_dump().items():
        w.writerow(["lever", k, "", "", "", "", v])
    for m in METRICS:
        r = getattr(result, m)
        w.writerow(["metric", m, _num(r.p10), _num(r.p50), _num(r.p90), r.unit,
                    METRIC_LABELS[m]])
    for mod in result.modules:
        for metric_name, r in (("cost_usd", mod.cost_usd), ("co2e_kg", mod.co2e_kg)):
            w.writerow(["module", f"{mod.module}.{metric_name}", _num(r.p10), _num(r.p50),
                        _num(r.p90), r.unit, ""])
        for pi in mod.provenance:
            w.writerow(["provenance", f"{mod.module}:{pi.formula_id}", "", "", "", "",
                        f"{pi.description} | parameters: {', '.join(pi.parameter_ids)}"])
    _write_detail_views(w, result)
    for warning in result.warnings:
        w.writerow(["warning", "", "", "", "", "", warning])
    for a in data["assumptions"]:
        w.writerow(["assumption", "", "", "", "", "", a])
    for p in data["params"]:
        src = (f"ASSUMPTION: {p.rationale}" if p.assumption
               else f"{p.source_title or ''} {p.source_url or ''} ({p.source_year})".strip())
        w.writerow(["parameter", p.id, p.value_low, p.value_mid, p.value_high, p.unit,
                    f"{p.label} | v{p.version} | {src}"])
    for note in data["notes"]:
        w.writerow(["note", "", "", "", "", "", note])
    approval: ApprovalRequest | None = data["approval"]
    if approval:
        w.writerow(["approval", approval.id, "", "", "", "", approval.status])
        for s in approval.signatures:
            w.writerow(["signature", s.signer, "", "", "", "",
                        f"{s.signer_name} | {s.meaning} | "
                        f"role {s.role} | {s.signed_at.isoformat()} | record_hash {s.record_hash}"])
    return buf.getvalue()


@router.get("/scenario/{scenario_id}.csv")
def export_csv(
    scenario_id: str, session: Session = Depends(get_session), svc: Any = Depends(services)
) -> Response:
    data = _gather(svc, session, scenario_id)
    return Response(
        content=build_csv(data), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_filename(data["row"], "csv")}"'},
    )


# ------------------------------------------------------------------------------------------ PDF
def _fmt(v: float | None, unit: str) -> str:
    if v is None or not _known(v):
        return "unknown"
    if unit == "usd":
        return f"${v:,.0f}"
    if unit == "percent":
        return f"{v:,.1f}%"
    if abs(v) >= 100:
        return f"{v:,.0f}"
    return f"{v:,.2f}"


UNIT_TEXT = {"usd": "USD", "hours": "hours", "kg_co2e": "kg CO2e", "months": "months",
             "percent": "%", "patients": "patients", "kits": "kits", "count": "count"}


def build_pdf(data: dict[str, Any]) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    row: ScenarioRow = data["row"]
    result: ScenarioResult = data["result"]
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)
    story: list[Any] = []

    def p(text: str, style: Any = None) -> Paragraph:
        return Paragraph(escape(str(text)), style or styles["BodyText"])

    def table(rows: list[list[Any]], widths: list[float] | None = None) -> Table:
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF4")),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#B0B8C0")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        return t

    story += [p(f"TrialPilot design report — {row.name}", styles["Title"]),
              p("Prototype estimates. Every number is a range (P10 / P50 / P90).", small),
              Spacer(1, 4 * mm)]
    story.append(table([
        ["Scenario", f"{row.id} (version {row.version}, {row.status})"],
        ["Author", f"{row.author} — created {row.created_at}"],
        ["Design", f"{row.design_id} v{row.design_version} (hash {row.design_hash[:12]})"],
        ["Parameters", f"set {row.parameter_set_version}; seed {row.seed}; {row.draws} draws"],
        ["Record hash", row.record_hash],
        ["Generated", data["generated_at"]],
    ], [35 * mm, 135 * mm]))
    story += [Spacer(1, 4 * mm), p("Levers", styles["Heading2"])]
    story.append(table([["Lever", "Value"]] + [[k, p(str(v), small)] for k, v in
                                              data["levers"].model_dump().items()],
                       [60 * mm, 110 * mm]))
    story += [Spacer(1, 4 * mm), p("Results", styles["Heading2"])]
    rows = [["Metric", "P10", "P50", "P90", "Unit"]]
    for m in METRICS:
        r = getattr(result, m)
        rows.append([METRIC_LABELS[m], _fmt(r.p10, r.unit), _fmt(r.p50, r.unit),
                     _fmt(r.p90, r.unit), UNIT_TEXT.get(r.unit, r.unit)])
    story.append(table(rows, [50 * mm, 30 * mm, 30 * mm, 30 * mm, 30 * mm]))
    if result.modules:
        story += [Spacer(1, 4 * mm), p("By module", styles["Heading2"])]
        rows = [["Module", "Cost P50 (P10–P90)", "Carbon kg CO2e P50 (P10–P90)"]]
        for mod in result.modules:
            c, e = mod.cost_usd, mod.co2e_kg
            rows.append([mod.module,
                         f"{_fmt(c.p50, c.unit)} ({_fmt(c.p10, c.unit)}–{_fmt(c.p90, c.unit)})",
                         f"{_fmt(e.p50, e.unit)} ({_fmt(e.p10, e.unit)}–{_fmt(e.p90, e.unit)})"])
        story.append(table(rows, [45 * mm, 62 * mm, 63 * mm]))
    story += [Spacer(1, 4 * mm), p("Forecast and supply", styles["Heading2"])]
    for label, view in (("Forecast", result.forecast), ("Supply", result.supply)):
        if view is not None:
            story.append(p(f"{label} draws: requested {view.draws_requested}, "
                           f"used {view.draws_used} (None means not reported).", small))
            if hasattr(view, "curve_draws_used"):
                story.append(p(f"Enrollment curve draws: {view.curve_draws_used}.", small))
    forecast = result.forecast
    if forecast is None:
        story.append(p("Enrollment forecast: not reported.", small))
    else:
        m = forecast.months_to_full_enrollment
        story.append(p(
            "Months to full enrollment: "
            f"{_fmt(m.p10, m.unit)} / {_fmt(m.p50, m.unit)} / {_fmt(m.p90, m.unit)} "
            f"{UNIT_TEXT.get(m.unit, m.unit)} (P10 / P50 / P90).",
            small))
        for name, metric in forecast.milestone_dates.items():
            story.append(p(
                f"{name}: {_fmt(metric.p10, metric.unit)} / {_fmt(metric.p50, metric.unit)} / "
                f"{_fmt(metric.p90, metric.unit)} {UNIT_TEXT.get(metric.unit, metric.unit)}.",
                small))
        story.append(p(
            f"Enrollment curve: {len(forecast.enrollment_curve)} points "
            "(month, P10, P50, P90 cumulative patients). Full rows are in the CSV.",
            small))
    supply = result.supply
    if supply is None:
        story.append(p("Drug supply: not reported.", small))
    else:
        for label, metric in (
            ("Kits needed", supply.kits_needed), ("Kits produced", supply.kits_produced),
            ("Kits wasted", supply.kits_wasted), ("Waste share", supply.waste_share),
            ("Shipments", supply.shipments),
        ):
            story.append(p(
                f"{label}: {_fmt(metric.p10, metric.unit)} / {_fmt(metric.p50, metric.unit)} / "
                f"{_fmt(metric.p90, metric.unit)} {UNIT_TEXT.get(metric.unit, metric.unit)}.",
                small))
        story.append(p(
            f"Stockout probability: {supply.stockout_probability} "
            "(share of simulated draws with any site stockout).",
            small))
    if data["missing_fields"] or result.warnings or data["assumptions"] or data["notes"]:
        story += [Spacer(1, 4 * mm), p("Warnings and assumptions", styles["Heading2"])]
        if data["missing_fields"]:
            story.append(p("Design missing_fields: " + "; ".join(data["missing_fields"]), small))
        for text in [*result.warnings, *data["assumptions"], *data["notes"]]:
            story.append(p(f"• {text}", small))
    if data["params"]:
        story += [Spacer(1, 4 * mm), p("Parameters and sources", styles["Heading2"])]
        rows = [["Parameter", "Low / mid / high", "Unit", "Source or assumption"]]
        for prm in data["params"]:
            src = (f"ASSUMPTION — {prm.rationale}" if prm.assumption else
                   f"{prm.source_title or ''} ({prm.source_year}) {prm.source_url or ''}")
            rows.append([p(f"{prm.id} (v{prm.version})", small),
                         f"{prm.value_low:g} / {prm.value_mid:g} / {prm.value_high:g}",
                         p(prm.unit, small), p(src, small)])
        story.append(table(rows, [50 * mm, 32 * mm, 23 * mm, 65 * mm]))
    story += [Spacer(1, 4 * mm), p("Signatures", styles["Heading2"])]
    approval: ApprovalRequest | None = data["approval"]
    if approval and approval.signatures:
        rows = [["Signer (printed name)", "Role", "Meaning", "Signed (UTC)"]]
        for s in approval.signatures:
            rows.append([p(f"{s.signer_name} ({s.signer})", small),
                         s.role, s.meaning.upper(),
                         s.signed_at.isoformat(timespec="seconds").replace("+00:00", "Z")])
        story.append(table(rows, [60 * mm, 25 * mm, 30 * mm, 55 * mm]))
        story.append(p(f"Signatures are bound to record hash {row.record_hash}.", small))
    else:
        status = f"approval request {approval.id}: {approval.status}" if approval else row.status
        story.append(p(f"No signatures yet ({status}).", small))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title=f"TrialPilot — {row.name}",
                            author="TrialPilot", leftMargin=18 * mm, rightMargin=18 * mm)
    doc.build(story)
    return buf.getvalue()


@router.get("/scenario/{scenario_id}.pdf")
def export_pdf(
    scenario_id: str, session: Session = Depends(get_session), svc: Any = Depends(services)
) -> Response:
    data = _gather(svc, session, scenario_id)
    return Response(
        content=build_pdf(data), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_filename(data["row"], "pdf")}"'},
    )

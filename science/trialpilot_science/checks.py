"""The four reproduction checks. Each returns a `Check` (results.py) for one trial."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import Any

import numpy as np
from trialpilot_contracts import Levers, Parameter

from .designs import PublishedDesign
from .ledger import Ledger, Line
from .library import FloatArray, LibrarySampler
from .results import CLOSE_PCT, MATCH_PCT, MODULE_LABELS, Check, LineChange, ModuleRow, Range


# ---------------------------------------------------------------- helpers

def _range(values: FloatArray | float) -> Range:
    arr = np.atleast_1d(np.asarray(values, dtype=np.float64))
    p10, p50, p90 = (float(x) for x in np.percentile(arr, [10, 50, 90]))
    return Range(p10=round(p10, 2), p50=round(p50, 2), p90=round(p90, 2))


def _status(published: float | None, ours: Range | None) -> tuple[float | None, bool | None, str]:
    if ours is None:
        return None, None, "unavailable"
    if published is None:
        return None, None, "not_reported"
    if published == 0:
        diff = 0.0 if abs(ours.p50) < 0.5 else math.inf
    else:
        diff = (ours.p50 - published) / published * 100
    within = ours.p10 - 0.05 <= published <= ours.p90 + 0.05
    status = "match" if abs(diff) <= MATCH_PCT else "close" if abs(diff) <= CLOSE_PCT else "gap"
    return (round(diff, 2) if math.isfinite(diff) else None), within, status


def _row(module: str, published: float | None, ours: Range | None, explanation: str | None) -> ModuleRow:
    diff, within, status = _status(published, ours)
    if diff is None and status == "gap":
        status = "gap"
    return ModuleRow(module=module, label=MODULE_LABELS.get(module, "Total" if module == "total" else module),
                     published_kg=published, ours=ours, diff_pct=diff, published_within_range=within,
                     status=status, explanation=explanation)  # type: ignore[arg-type]


def _finding_text(ledger: Ledger, module: str, *, corrected: bool) -> str | None:
    texts = []
    for f in ledger.findings:
        lines = [ln for ln in ledger.lines if ln.id in f.lines and ln.module == module]
        if not lines:
            continue
        if corrected and not any(ln.correction for ln in lines):
            continue
        if not corrected and f.severity == "info":
            continue
        texts.append(f"{f.summary} ({f.id})")
    return " ".join(texts) or None


# ---------------------------------------------------------------- 1. method (as printed)

def method_check(ledger: Ledger) -> Check:
    rec = ledger.recomputed_by_module()
    rows = []
    for m in ledger.modules():
        ours = _range(rec[m])
        pub = ledger.published_modules.get(m)
        _, _, status = _status(pub, ours)
        expl = _finding_text(ledger, m, corrected=False) if status != "match" else None
        if status == "close" and expl is None:
            expl = "Rounding in the printed line values."
        rows.append(_row(m, pub, ours, expl))
    total = _row("total", ledger.published_total_kg, _range(sum(rec.values())),
                 "Sum of the module differences above." if abs(sum(rec.values()) - ledger.published_total_kg)
                 > MATCH_PCT / 100 * ledger.published_total_kg else None)
    return Check(
        id="method", title="Method check: the paper's own arithmetic",
        description=("Every line of the published calculation (appendix "
                     f"{'C' if ledger.id == 'casps' else 'D'}) recomputed as activity x factor with the "
                     "paper's own numbers, then summed per module. Tests our transcription and the paper's "
                     "arithmetic; no TrialPilot parameter is involved."),
        available=True, total=total, modules=rows,
        notes=[f"{len(ledger.lines)} calculation lines transcribed from page images; "
               f"{sum(1 for ln in ledger.lines if abs(ln.recomputed_kg - ln.reported_kg) > max(0.06, 0.01 * ln.reported_kg))}"
               " line(s) do not reproduce their printed value within 1%."],
    )


# ---------------------------------------------------------------- 2. corrected

def corrected_check(ledger: Ledger) -> Check:
    cor = ledger.corrected_by_module()
    rows = []
    for m in ledger.modules():
        pub = ledger.published_modules.get(m)
        ours = _range(cor[m])
        _, _, status = _status(pub, ours)
        expl = _finding_text(ledger, m, corrected=True) or _finding_text(ledger, m, corrected=False)
        rows.append(_row(m, pub, ours, expl if status != "match" else None))
    corrections = [ln for ln in ledger.lines if ln.correction]
    notes = [f"{ln.id}: {ln.correction.reason} ({ln.correction.finding})" for ln in corrections if ln.correction]
    total_expl = None
    delta = sum(cor.values()) - ledger.published_total_kg
    if abs(delta) > MATCH_PCT / 100 * ledger.published_total_kg:
        total_expl = f"Corrections change the total by {delta:+,.0f} kg CO2e ({delta / ledger.published_total_kg:+.1%})."
    return Check(
        id="corrected", title="Corrected: the paper's numbers with the errors we found fixed",
        description=("Same as the method check, after fixing only the documented errors (units slip, double "
                     "count, arithmetic). No factor or activity is tuned."),
        available=True, total=_row("total", ledger.published_total_kg, _range(sum(cor.values())), total_expl),
        modules=rows, notes=notes or ["No correction needed beyond the method check."],
    )


# ---------------------------------------------------------------- 3. library

def library_check(ledger: Ledger, sampler: LibrarySampler) -> Check:
    n = sampler.n
    by_module: dict[str, FloatArray] = {m: np.zeros(n) for m in ledger.modules()}
    changes: list[tuple[float, LineChange]] = []
    kept: list[str] = []
    for ln in ledger.lines:
        activity = ln.corrected_activity
        if activity is None:
            continue
        lf = sampler.factor(ln.factor_key)
        if lf.available and lf.draws is not None:
            kg = activity * lf.draws
            kind = lf.kind or "independent"
        else:
            kg = np.full(n, activity * ln.factor)
            kind = "paper_factor_kept"
            kept.append(f"{ln.id} ({ln.factor_key}): {lf.note}")
        by_module[ln.module] = by_module[ln.module] + kg
        paper_kg = activity * ln.factor
        lib_range = _range(kg)
        changes.append((abs(lib_range.p50 - paper_kg), LineChange(
            line_id=ln.id, module=ln.module, item=ln.item, paper_factor=ln.factor, paper_kg=round(paper_kg, 2),
            library_factor_p50=(round(float(np.median(lf.draws)), 6) if lf.draws is not None else None),
            library_kg=lib_range if lf.available else None, parameter_ids=lf.parameter_ids,
            kind=kind, note=lf.note,  # type: ignore[arg-type]
        )))
    rows = []
    for m in ledger.modules():
        pub = ledger.published_modules.get(m)
        ours = _range(by_module[m])
        _, _, status = _status(pub, ours)
        expl = _library_explanation(m, [c for _, c in changes if c.module == m]) if status != "match" else None
        rows.append(_row(m, pub, ours, expl))
    total_draws = sum(by_module.values(), np.zeros(n))
    total = _row("total", ledger.published_total_kg, _range(total_draws),
                 _library_explanation("total", [c for _, c in changes]))
    changes.sort(key=lambda t: -t[0])
    return Check(
        id="library", title="Library check: the paper's activity data x TrialPilot's parameter library",
        description=("The corrected activity data, multiplied by TrialPilot's library factors (DESNZ 2026 for "
                     "travel, freight, materials, electricity and hotels, plus well-to-tank as the LCCT method "
                     "does; LCCT values where no independent source exists). Each library factor is sampled "
                     f"triangular(low, mid, high), {n} seeded draws, P10/P50/P90."),
        available=True, total=total, modules=rows,
        notes=([f"{len(kept)} line(s) keep the paper's factor (no library equivalent):"] + kept) if kept else [],
        line_changes=[c for _, c in changes[:15]],
    )


def _library_explanation(module: str, changes: list[LineChange]) -> str | None:
    movers = sorted((c for c in changes if c.library_kg is not None),
                    key=lambda c: -abs(c.library_kg.p50 - c.paper_kg) if c.library_kg else 0)
    movers = [c for c in movers if c.library_kg and abs(c.library_kg.p50 - c.paper_kg) >= 1.0][:3]
    if not movers:
        return None
    parts = []
    for c in movers:
        assert c.library_kg is not None
        d = c.library_kg.p50 - c.paper_kg
        parts.append(f"{c.item}: paper factor {c.paper_factor:g} -> library {c.library_factor_p50:g} "
                     f"({d:+,.0f} kg). {c.note}".strip())
    lead = "Largest factor changes" if module == "total" else "Driven by"
    return f"{lead}: " + " | ".join(parts)


# ---------------------------------------------------------------- 4. engine

EngineFn = Callable[..., Any]


def _engine_range(r: Any) -> Range | None:
    """MetricRange -> Range, or None when the engine reports the value as unknown (None/NaN)."""
    vals = (r.p10, r.p50, r.p90)
    if any(v is None or not math.isfinite(v) for v in vals):
        return None
    return Range(p10=round(r.p10, 2), p50=round(r.p50, 2), p90=round(r.p90, 2))


def load_engine() -> tuple[EngineFn | None, str | None]:
    try:
        from trialpilot_engine import compute_scenario
    except Exception as exc:  # engine package absent or broken: report, never crash the science check
        return None, f"trialpilot_engine could not be imported: {type(exc).__name__}: {exc}"
    return compute_scenario, None


def engine_check(
    check_id: str,
    title: str,
    description: str,
    ledger: Ledger,
    published: PublishedDesign,
    params: Mapping[str, Parameter],
    engine: EngineFn | None,
    engine_reason: str | None,
    seed: int,
    draws: int,
    notes_by_module: Mapping[str, str],
) -> Check:
    if engine is None:
        return Check(id=check_id, title=title, description=description, available=False,  # type: ignore[arg-type]
                     unavailable_reason=engine_reason, total=None, modules=[])
    try:
        result = engine(published.design, Levers(), dict(params), seed=seed, draws=draws)
    except NotImplementedError as exc:
        return Check(id=check_id, title=title, description=description, available=False,  # type: ignore[arg-type]
                     unavailable_reason=f"engine not implemented yet: {exc}", total=None, modules=[])
    except Exception as exc:  # report the engine's own error message verbatim
        return Check(id=check_id, title=title, description=description, available=False,  # type: ignore[arg-type]
                     unavailable_reason=f"engine raised {type(exc).__name__}: {exc}", total=None, modules=[])
    engine_modules = {mb.module: mb for mb in result.modules}
    rows = []
    for m in [*ledger.modules(), *[k for k in engine_modules if k not in ledger.modules()]]:
        mb = engine_modules.get(m)
        ours = None
        if mb is not None:
            ours = _engine_range(mb.co2e_kg)
        pub = ledger.published_modules.get(m)
        _, _, status = _status(pub, ours)
        expl = notes_by_module.get(m)
        if ours is None:
            expl = "Engine returned no finite value for this module (see engine warnings). " + (expl or "")
        rows.append(_row(m, pub, ours, expl if status not in ("match",) else expl))
    total = _row("total", ledger.published_total_kg, _engine_range(result.co2e_kg), notes_by_module.get("total"))
    return Check(id=check_id, title=title, description=description, available=True,  # type: ignore[arg-type]
                 total=total, modules=rows,
                 notes=[f"parameter_set_version {result.parameter_set_version}", *result.warnings])

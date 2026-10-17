"""Reproduce the published CASPS and PRIMETIME footprints and write science/out/results.json.

    uv run --project science python -m science.reproduce            # from the repo root
    uv run --project science python -m trialpilot_science.reproduce  # same thing

Deterministic: fixed seed, no timestamps, sorted output. Never edits the parameter library.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from trialpilot_contracts import Levers, Parameter, TrialDesign, load_params, param_set_version

from . import paths
from .checks import (
    corrected_check,
    engine_check,
    library_check,
    load_engine,
    method_check,
)
from .designs import PAPER_URL, PublishedDesign, load_design, load_paper_factor_overrides
from .ledger import Ledger, load_ledger
from .library import LibrarySampler, load_factor_map
from .results import (
    BandTrial,
    Check,
    DesignInputOut,
    EngineInfo,
    FindingOut,
    IndustryBand,
    PublishedFigures,
    ScienceResults,
    TonneRange,
    TrialOut,
)

SEED = 7
DRAWS = 2000
CITATION = ("Griffiths J, Fox L, Williamson PR, on behalf of the Low Carbon Clinical Trials Group. Quantifying the "
            "carbon footprint of clinical trials: guidance development and case studies. BMJ Open "
            "2024;14:e075755. doi:10.1136/bmjopen-2023-075755")
# Industry range cited by Griffiths 2024 (Introduction): Mackillop et al., BMJ Open 2023 — three industry-sponsored
# late-stage trials: "2498 tonnes CO2e, 1632 tonnes CO2e and 1437 tonnes CO2e, respectively".
INDUSTRY_TRIALS_T = [2498.0, 1632.0, 1437.0]


def _engine_notes() -> dict[str, dict[str, str]]:
    path = paths.DATA_DIR / "engine_notes.yaml"
    if not path.exists():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: {m: str(t).strip() for m, t in v.items()} for k, v in doc.items()}


def _findings(ledger: Ledger) -> list[FindingOut]:
    out = []
    for f in ledger.findings:
        lines = [ln for ln in ledger.lines if ln.id in f.lines]
        effect = sum(ln.corrected_kg - ln.recomputed_kg for ln in lines)
        if f.id == "primetime-f1":  # effect vs the PRINTED value: our recomputation already uses 8 nights
            effect = sum(ln.recomputed_kg - ln.reported_kg for ln in lines)
        out.append(FindingOut(id=f.id, severity=f.severity, summary=f.summary,  # type: ignore[arg-type]
                              detail=f.detail or f.summary, lines=list(f.lines), effect_kg=round(effect, 1)))
    return out


def _summary(ledger: Ledger, checks: Mapping[str, Check]) -> list[str]:
    name = ledger.trial["name"]
    pub = ledger.published_total_kg
    m, c, lib = checks["method"].total, checks["corrected"].total, checks["library"].total
    assert m and c and lib and m.ours and c.ours and lib.ours
    s1 = (f"{name}: the paper's own arithmetic reproduces to {m.diff_pct:+.2f}% of the published "
          f"{pub:,.0f} kg CO2e ({m.ours.p50:,.0f} kg); fixing the errors we documented moves it to "
          f"{c.ours.p50:,.0f} kg ({c.diff_pct:+.1f}%).")
    eng = checks.get("engine_library")
    eng_txt = ""
    if eng and eng.available and eng.total and eng.total.ours:
        inside = "inside" if eng.total.published_within_range else "outside"
        eng_txt = (f" The full TrialPilot engine on the rebuilt design gives {eng.total.ours.p50:,.0f} kg "
                   f"(P10-P90 {eng.total.ours.p10:,.0f}-{eng.total.ours.p90:,.0f}, {eng.total.diff_pct:+.0f}%), "
                   f"published total {inside} the range, with module-level differences explained per module.")
    elif eng is not None:
        eng_txt = " The engine check is not available yet (" + (eng.unavailable_reason or "unknown") + ")."
    movers = [c for c in checks["library"].line_changes if c.library_kg is not None][:2]
    why = "; ".join(f"{c.item.split(':')[0].split(',')[0]} ({c.library_kg.p50 - c.paper_kg:+,.0f} kg)"
                    for c in movers if c.library_kg)
    s2 = (f"With TrialPilot's library factors the same activity data give {lib.ours.p50:,.0f} kg "
          f"(P10-P90 {lib.ours.p10:,.0f}-{lib.ours.p90:,.0f}, {lib.diff_pct:+.1f}% vs published), driven mostly by "
          f"{why}.{eng_txt}")
    return [s1, s2]


def _with(params: Mapping[str, Parameter], extra: Mapping[str, Parameter]) -> dict[str, Parameter]:
    out = dict(params)
    for pid, p in extra.items():
        if p.unit == "as_library" and pid in params:
            p = p.model_copy(update={"unit": params[pid].unit})
        out[pid] = p
    return out


def _demo_designs() -> list[tuple[Path, TrialDesign | None, str | None]]:
    found: list[tuple[Path, TrialDesign | None, str | None]] = []
    if not paths.DEMO_TRIALS_DIR.is_dir():
        return found
    for f in sorted(paths.DEMO_TRIALS_DIR.iterdir()):
        if f.suffix not in (".json", ".yaml", ".yml"):
            continue
        try:
            raw = json.loads(f.read_text(encoding="utf-8")) if f.suffix == ".json" else yaml.safe_load(
                f.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "design" in raw and "enrollment_target" not in raw:
                raw = raw["design"]
            found.append((f, TrialDesign.model_validate(raw), None))
        except Exception as exc:
            found.append((f, None, f"{type(exc).__name__}: {str(exc).splitlines()[0]}"))
    return found


def _industry_band(params: Mapping[str, Parameter], engine: Any, engine_reason: str | None, seed: int,
                   draws: int) -> IndustryBand:
    demo: list[BandTrial] = []
    for path, design, err in _demo_designs():
        if design is None:
            demo.append(BandTrial(design_id=path.name, title=path.name, registry_id=None, available=False,
                                  reason=f"not a TrialDesign: {err}"))
            continue
        if engine is None:
            demo.append(BandTrial(design_id=design.id, title=design.title, registry_id=design.registry_id,
                                  available=False, reason=engine_reason))
            continue
        try:
            r = engine(design, Levers(), dict(params), seed=seed, draws=draws)
            t = TonneRange(p10=round(r.co2e_kg.p10 / 1000, 3), p50=round(r.co2e_kg.p50 / 1000, 3),
                           p90=round(r.co2e_kg.p90 / 1000, 3))
            demo.append(BandTrial(design_id=design.id, title=design.title, registry_id=design.registry_id,
                                  available=True, total_t=t,
                                  within_band=min(INDUSTRY_TRIALS_T) <= t.p50 <= max(INDUSTRY_TRIALS_T)))
        except Exception as exc:
            demo.append(BandTrial(design_id=design.id, title=design.title, registry_id=design.registry_id,
                                  available=False, reason=f"engine raised {type(exc).__name__}: {exc}"))
    return IndustryBand(
        low_t=min(INDUSTRY_TRIALS_T), high_t=max(INDUSTRY_TRIALS_T), trials_t=INDUSTRY_TRIALS_T,
        source=("Mackillop N, Shah J, Collins M et al. Carbon footprint of industry-sponsored late-stage clinical "
                "trials. BMJ Open 2023;13:e072491 — as cited in Griffiths et al. 2024 (Introduction)."),
        note=("Sanity band only: three industry Phase 3 trials (cardiovascular, oncology, respiratory) measured with "
              "a different, industry method that includes drug manufacture. Mackillop's oncology trial is 1632 t in "
              "the abstract and 1638 t in its Results/Table 3; Griffiths cites 1632."),
        demo_trials=demo,
    )


def run(seed: int = SEED, draws: int = DRAWS) -> ScienceResults:
    library = load_params(paths.PARAMS_DIR)
    sampler = LibrarySampler(library, load_factor_map(paths.FACTOR_MAP), seed, draws)
    paper_factors = load_paper_factor_overrides(paths.PAPER_FACTOR_OVERRIDES)
    engine, engine_reason = load_engine()
    notes = _engine_notes()
    trials: list[TrialOut] = []
    for tid, lpath in paths.LEDGERS.items():
        ledger = load_ledger(lpath)
        published: PublishedDesign = load_design(paths.DESIGNS[tid], tid, library)
        lib_params = _with(library, published.activity_overrides)
        paper_params = _with(lib_params, paper_factors)
        tnotes = notes.get(tid, {})
        checks: dict[str, Check] = {
            "method": method_check(ledger),
            "corrected": corrected_check(ledger),
            "library": library_check(ledger, sampler),
            "engine_library": engine_check(
                "engine_library", "Engine check: TrialPilot engine + library on the rebuilt design",
                ("The trial rebuilt as a TrialDesign (sites, visits, procedures from the paper; gaps filled with "
                 "labelled assumptions) and run through the same engine the simulator uses, with the parameter "
                 "library plus the trial's reported activity (e.g. coordinating-unit FTE). Tests the engine's "
                 "model structure, not just its factors."),
                ledger, published, lib_params, engine, engine_reason, seed, draws, tnotes),
            "engine_paper_factors": engine_check(
                "engine_paper_factors", "Engine check with the paper's own factors",
                ("As above, but every engine emission factor the paper reports is replaced by the paper's value "
                 "(rail 0.04441, flights, air and road freight, UK grid 0.273, dry ice 1.81, CTU per-FTE). "
                 "Identified combined factors are split into documented direct/WTT components so each is "
                 "counted once. Road freight 0.19443 has an unidentified split and is used once without "
                 "additional WTT. Factors absent from the paper retain the library values. Remaining "
                 "differences include model structure and these unsourced activity assumptions."),
                ledger, published, paper_params, engine, engine_reason, seed, draws, tnotes),
        }
        t = ledger.trial
        trials.append(TrialOut(
            id=tid, name=t["name"], registry_id=t["registry_id"], title=t["title"], phase=t["phase"],
            patients=int(t["patients"]), sites=int(t["sites"]), countries=list(t["countries"]),
            duration_years=float(t["duration_years"]),
            published=PublishedFigures(total_kg=ledger.published_total_kg,
                                       total_main_text_kg=ledger.published_total_main_text_kg,
                                       modules=ledger.published_modules),
            source=f"{CITATION}. Online supplemental appendix {'C' if tid == 'casps' else 'D'} (CC BY 4.0).",
            checks=list(checks.values()), findings=_findings(ledger),
            design_inputs=[DesignInputOut(field=i.field, value=i.value, origin=i.origin, ref=i.ref)  # type: ignore[arg-type]
                           for i in published.inputs],
            summary=_summary(ledger, checks),
        ))
    return ScienceResults(
        title="Science check: reproducing two published clinical-trial carbon footprints",
        data_label=("Real published data (BMJ Open 2024, CC BY 4.0) transcribed by hand from the paper's appendices; "
                    "not simulated."),
        paper={"citation": CITATION, "url": PAPER_URL, "doi": "10.1136/bmjopen-2023-075755", "licence": "CC BY 4.0",
               "full_text": "https://europepmc.org/articles/PMC10823997"},
        parameter_set_version=param_set_version(library), seed=seed, draws=draws,
        thresholds_pct={"match": 1.0, "close": 10.0},
        engine=EngineInfo(available=engine is not None, reason=engine_reason),
        trials=trials, industry_band=_industry_band(library, engine, engine_reason, seed, draws),
        how_to_reproduce="uv run --project science python -m science.reproduce",
    )


def write(results: ScienceResults, out: Path = paths.RESULTS_JSON, schema: Path = paths.RESULTS_SCHEMA) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(results.model_dump_json())
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8",
                   newline="\n")
    schema.write_text(json.dumps(ScienceResults.model_json_schema(), indent=2, sort_keys=True) + "\n",
                      encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=paths.RESULTS_JSON)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--draws", type=int, default=DRAWS)
    args = ap.parse_args(argv)
    np.seterr(all="ignore")
    results = run(args.seed, args.draws)
    write(results, args.out, args.out.with_name("results.schema.json"))
    for t in results.trials:
        print(f"== {t.name}")
        for s in t.summary:
            print("  " + s)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

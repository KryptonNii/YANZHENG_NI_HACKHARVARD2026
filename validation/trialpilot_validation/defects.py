"""Planted defects: does the validation process actually catch problems?

`tpv defects-run` creates ONE throwaway `git worktree` of HEAD *outside* the repository folder,
runs an unsigned experiment there as a baseline, then for each patch in `validation/defects/`:
`git apply` → experiment → `git apply -R`. The worktree is removed afterwards. Nothing is ever
applied in the shared folder, and no branch is switched.

A defect counts as **detected** when, compared with the baseline, at least one stage reports
something new:
- unit test       — a test (or test collection) that passed in the baseline now fails/errors;
- trace check     — a new requirement without tests / unknown requirement id / below-depth gap;
- workflow check  — a compliance control probe (`tpv controls`) that held now fails.
Counts are taken from the runs as they happen; a patch that no longer applies is reported as such.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .context import Ctx, TpvError, md_escape, read_json, utc_now, write_json, write_text

EXPERIMENT_FILE = "experiment.json"


# ---- experiment (runs inside the copy) ---------------------------------------------------------


def experiment(ctx: Ctx, outdir: Path, only: list[str] | None = None) -> dict[str, Any]:
    """Unsigned run of suites + trace + control probes. NOT GxP evidence."""
    from . import controls, execute, trace

    outdir.mkdir(parents=True, exist_ok=True)
    res = execute.run_all(ctx, outdir, e2e=False, only=only)
    tr = trace.build(ctx, tests=res["tests"], source={"kind": "experiment"})
    probes = controls.run_probes()
    data = {
        "note": "Unsigned experiment for planted-defect detection — NOT GxP evidence.",
        "finished_at": utc_now(),
        "suites": [{k: s.get(k) for k in ("name", "status", "exit_code")} for s in res["suites"]],
        "tests": [{"id": t["id"], "outcome": t.get("outcome"), "reqs": t.get("reqs", [])}
                  for t in res["tests"]],
        "collection_errors": [e["id"] for e in res["collection_errors"]],
        "counts": res["counts"],
        "trace": {"summary": tr["summary"], "untested": tr["flags"]["untested_requirements"],
                  "unknown_refs": sorted(tr["flags"]["unknown_requirement_refs"]),
                  "below_min_depth": tr["flags"]["below_min_depth"],
                  "failing": tr["flags"]["failing_requirements"]},
        "controls": probes,
    }
    write_json(outdir / EXPERIMENT_FILE, data)
    return data


# ---- comparison -----------------------------------------------------------------------------------


def _bad(exp: dict[str, Any]) -> set[str]:
    out = {t["id"] for t in exp["tests"] if t["outcome"] in ("failed", "error", "xpassed")}
    out |= {f"collect:{e}" for e in exp["collection_errors"]}
    out |= {f"suite:{s['name']}" for s in exp["suites"] if s["status"] == "runner_error"}
    return out


def compare(base: dict[str, Any], exp: dict[str, Any]) -> dict[str, Any]:
    new_failures = sorted(_bad(exp) - _bad(base))
    tb, te = base["trace"], exp["trace"]
    new_trace = (
        [f"no test: {r}" for r in te["untested"] if r not in tb["untested"]]
        + [f"unknown requirement id: {r}" for r in te["unknown_refs"] if r not in tb["unknown_refs"]]
        + [f"below minimum depth: {r}" for r in te["below_min_depth"]
           if r not in tb["below_min_depth"]]
    )
    held = {p["id"] for p in base["controls"] if p["holds"]}
    broken = [f"{p['id']} {p['control']}: {p['detail']}" for p in exp["controls"]
              if p["id"] in held and not p["holds"]]
    stages = []
    if new_failures:
        stages.append("unit test")
    if new_trace:
        stages.append("trace check")
    if broken:
        stages.append("workflow check")
    return {"detected": bool(stages), "stages": stages, "new_failures": new_failures,
            "new_trace_flags": new_trace, "broken_controls": broken}


# ---- orchestration (runs in the main checkout) ----------------------------------------------------


def load_defects(ctx: Ctx) -> list[dict[str, Any]]:
    path = ctx.vdir / "defects" / "defects.yaml"
    if not path.exists():
        raise TpvError("validation/defects/defects.yaml not found.")
    items = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("defects") or []
    for d in items:
        if not (ctx.vdir / "defects" / d["patch"]).exists():
            raise TpvError(f"Patch file missing: validation/defects/{d['patch']}")
    return items


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None,
         timeout: int = 7200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _experiment_in(wt: Path, out: Path, tmp: Path, only: list[str] | None) -> dict[str, Any]:
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "TPV_PIN")}
    env.update(TPV_REPO=str(wt), TP_COMPLIANCE_DB=str(tmp / "experiment.sqlite"),
               TP_VALIDATION_OUT=str(tmp / "vout"), DEMO_OFFLINE="1",
               PYTHONIOENCODING="utf-8")
    uv = shutil.which("uv") or "uv"
    cmd = [uv, "run", "--project", str(wt / "validation"), "tpv", "experiment", "--out", str(out)]
    for name in only or []:
        cmd += ["--suite", name]
    proc = _run(cmd, cwd=wt / "validation", env=env)
    write_text(out / "experiment.log", f"$ {' '.join(cmd)}\n{proc.stdout}\n{proc.stderr}\n"
                                       f"exit {proc.returncode}\n")
    if not (out / EXPERIMENT_FILE).exists():
        raise TpvError(f"Experiment failed in {wt} (exit {proc.returncode}); see "
                       f"{out / 'experiment.log'}:\n{proc.stderr[-2000:]}")
    data: dict[str, Any] = read_json(out / EXPERIMENT_FILE)
    return data


def defects_run(ctx: Ctx, *, only_defects: list[str] | None = None,
                only_suites: list[str] | None = None, keep: bool = False) -> dict[str, Any]:
    defects = [d for d in load_defects(ctx) if not only_defects or d["id"] in only_defects]
    head = ctx.git("rev-parse", "HEAD")
    tmp = Path(tempfile.mkdtemp(prefix="tpv-defects-"))
    if ctx.repo.resolve() in tmp.resolve().parents:
        raise TpvError("Temporary directory is inside the repository; refusing.")
    wt = tmp / "worktree"
    results: dict[str, Any] = {"started_at": utc_now(), "head": head, "planted": len(defects),
                               "rows": [], "note": "Unsigned experiment, not GxP evidence. Only "
                               "committed code (HEAD) is tested."}
    out_root = ctx.out / "defects"
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    ctx.git("worktree", "add", "--detach", str(wt), head)
    try:
        print(f"tpv: baseline experiment in {wt} …", file=sys.stderr)
        base = _experiment_in(wt, out_root / "baseline", tmp, only_suites)
        results["baseline"] = {"counts": base["counts"], "trace": base["trace"]["summary"],
                               "controls_holding": sum(p["holds"] for p in base["controls"])}
        for d in defects:
            patch = (ctx.vdir / "defects" / d["patch"]).resolve()
            row: dict[str, Any] = {"id": d["id"], "type": d["type"], "patch": d["patch"],
                                   "requirement": d.get("requirement"),
                                   "expected_stages": d.get("expected_stages", [])}
            ap = _run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=wt)
            if ap.returncode != 0:
                row.update(applied=False, detected=False, stages=[],
                           error=f"patch did not apply: {ap.stderr.strip()[:500]}")
                results["rows"].append(row)
                print(f"tpv: {d['id']} — patch did not apply", file=sys.stderr)
                continue
            try:
                print(f"tpv: {d['id']} ({d['type']}) experiment …", file=sys.stderr)
                exp = _experiment_in(wt, out_root / d["id"], tmp, only_suites)
                row.update(applied=True, **compare(base, exp))
            except TpvError as exc:
                row.update(applied=True, detected=False, stages=[], error=str(exc)[:1000])
            finally:
                rv = _run(["git", "apply", "-R", "--whitespace=nowarn", str(patch)], cwd=wt)
                if rv.returncode != 0:
                    raise TpvError(f"Could not revert {d['patch']} in the throwaway worktree: "
                                   f"{rv.stderr}")
            results["rows"].append(row)
            print(f"tpv: {d['id']} detected={row['detected']} stages={row['stages']}",
                  file=sys.stderr)
    finally:
        if not keep:
            _run(["git", "worktree", "remove", "--force", str(wt)], cwd=ctx.repo)
            _run(["git", "worktree", "prune"], cwd=ctx.repo)
            shutil.rmtree(tmp, ignore_errors=True)
    results["applied"] = sum(1 for r in results["rows"] if r.get("applied"))
    results["detected"] = sum(1 for r in results["rows"] if r.get("detected"))
    results["finished_at"] = utc_now()
    write_json(out_root / "results.json", results)
    write_text(out_root / "defects.md", render_md(results))
    return results


def latest(ctx: Ctx) -> dict[str, Any] | None:
    p = ctx.out / "defects" / "results.json"
    archived = False
    if not p.exists():
        p = ctx.vdir / "defects" / "LAST_RUN.json"
        archived = True
        if not p.exists():
            return None
    data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    if archived:
        data = {**data, "archived": True, "source": "validation/defects/LAST_RUN.json"}
    return data


def render_md(r: dict[str, Any]) -> str:
    lines = ["# Planted-defect detection run", "",
             f"Commit `{r['head'][:10]}` · {r['started_at']} → {r.get('finished_at')} · "
             f"**detected {r['detected']} of {r['planted']}** planted defects "
             f"({r['applied']} applied).", "", f"> {r['note']}", ""]
    if r.get("archived"):
        lines += ["Archived experiment from `validation/defects/LAST_RUN.json`. The commit above "
                  "identifies the code tested; these are not measurements of the current checkout. "
                  "Run `tpv defects-run` to measure the current commit.", ""]
    if r.get("baseline"):
        b = r["baseline"]["counts"]
        lines += [f"Baseline (no defect): {b['total']} tests — passed {b['passed']}, failed "
                  f"{b['failed']}, error {b['error']}; control probes holding "
                  f"{r['baseline']['controls_holding']}.", ""]
    lines += ["| Defect | Type | Requirement | Applied | Detected | Stage(s) | What flagged it |",
              "|---|---|---|---|---|---|---|"]
    for row in r["rows"]:
        what = (row.get("new_failures", [])[:3] + row.get("new_trace_flags", [])[:3]
                + row.get("broken_controls", [])[:2])
        detail = "<br>".join(f"`{md_escape(w)}`" for w in what) or md_escape(row.get("error", "—"))
        lines.append(f"| {row['id']} | {row['type']} | {row.get('requirement') or ''} | "
                     f"{'yes' if row.get('applied') else 'no'} | "
                     f"**{'yes' if row.get('detected') else 'no'}** | "
                     f"{', '.join(row.get('stages', [])) or '—'} | {detail} |")
    lines.append("")
    return "\n".join(lines)

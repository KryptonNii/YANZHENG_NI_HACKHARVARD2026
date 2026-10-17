"""`tpv trace`: requirement → risk → tests → result → evidence hash.

Source of tests/results: the latest signed execution if there is one, else the latest collection
(results then show "not run"). Flags requirements with no test, tests with no requirement and tests
that cite unknown requirement ids.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from . import execute, protocol
from .context import Ctx, TpvError, md_escape, short, utc_now, write_json, write_text

RESULT_ORDER = ("pass", "fail", "incomplete", "not run", "no test")


def requirement_result(outcomes: list[str | None]) -> str:
    """pass = every listed test passed; incomplete = some passed, others did not run."""
    if not outcomes:
        return "no test"
    if any(o in ("failed", "error", "xpassed") for o in outcomes):
        return "fail"
    ran = sum(1 for o in outcomes if o in ("passed", "xfailed"))
    if ran == len(outcomes):
        return "pass"
    return "incomplete" if ran else "not run"


def build(ctx: Ctx, *, tests: list[dict[str, Any]] | None = None,
          source: dict[str, Any] | None = None) -> dict[str, Any]:
    """Trace from explicit `tests` (e.g. a defects experiment) or the latest run/collection."""
    requirements = ctx.requirements()
    run = execute.latest_run(ctx) if tests is None else None
    evidence_files: dict[str, str] = {}
    if tests is not None:
        source = source or {"kind": "experiment"}
    elif run is not None:
        tests = run["tests"]
        evidence_files = {f["path"]: f["sha256"] for f in run["manifest"]["files"]}
        source = {"kind": "execution", "run_id": run["run_id"],
                  "manifest_sha256": run["manifest_sha256"],
                  "signed_by": (run["signature"] or {}).get("signer"),
                  "git_commit": run["manifest"].get("git", {}).get("commit")}
    else:
        col = protocol.latest_collection(ctx)
        if col is None:
            raise TpvError("Nothing to trace: run `tpv protocol` (collects tests) or `tpv execute`.")
        tests = col["tests"]
        source = {"kind": "collection", "collected_at": col["collected_at"]}
    assert source is not None

    req_ids = {r["id"] for r in requirements}
    by_req: dict[str, list[dict[str, Any]]] = {r["id"]: [] for r in requirements}
    unknown: dict[str, list[str]] = {}
    untagged: list[str] = []
    for t in sorted(tests, key=lambda t: t["id"]):
        if not t.get("reqs"):
            untagged.append(t["id"])
        for rid in t.get("reqs", []):
            if rid in req_ids:
                by_req[rid].append(t)
            else:
                unknown.setdefault(rid, []).append(t["id"])

    rows = []
    for r in requirements:
        ts = by_req[r["id"]]
        suites = sorted({t.get("suite", "") for t in ts})
        evidence = []
        for s in suites:
            name = f"{s}.results.json" if s != "e2e" else "e2e.playwright.json"
            if name in evidence_files:
                evidence.append({"file": name, "sha256": evidence_files[name]})
        rows.append({
            "id": r["id"], "text": " ".join(str(r["text"]).split()), "risk": r["risk"],
            "gxp": r["gxp"], "area": r.get("area"),
            "tests": [{"id": t["id"], "kind": t.get("kind", "pytest"),
                       "outcome": t.get("outcome") or "not run"} for t in ts],
            "result": requirement_result([t.get("outcome") for t in ts]),
            "evidence": evidence,
            "below_min_depth": len(ts) < protocol.MIN_TESTS[r["risk"]],
        })
    flags = {
        "untested_requirements": [r["id"] for r in rows if not r["tests"]],
        "below_min_depth": [r["id"] for r in rows if r["tests"] and r["below_min_depth"]],
        "unknown_requirement_refs": unknown,
        "tests_without_requirement_count": len(untagged),
        "tests_without_requirement": untagged,
        "failing_requirements": [r["id"] for r in rows if r["result"] == "fail"],
    }
    summary = {res: sum(1 for r in rows if r["result"] == res) for res in RESULT_ORDER}
    return {"generated_at": utc_now(), "source": source, "rows": rows, "flags": flags,
            "summary": summary, "total_requirements": len(rows), "total_tests": len(tests)}


def render_md(trace: dict[str, Any]) -> str:
    src = trace["source"]
    s = trace["summary"]
    f = trace["flags"]
    lines = ["# Traceability matrix", ""]
    if src["kind"] == "experiment":
        lines.append("Results from an unsigned experiment run — **not GxP evidence**.")
    elif src["kind"] == "execution":
        lines.append(f"Results from signed execution **{src['run_id']}** (signed by "
                     f"{src.get('signed_by')}; manifest sha256 `{src['manifest_sha256'][:16]}…`; "
                     f"commit `{(src.get('git_commit') or 'unknown')[:10]}`).")
    else:
        lines.append(f"No execution yet — tests from collection at {src['collected_at']}; "
                     "results are *not run*.")
    lines += ["", f"Requirements: **{trace['total_requirements']}** · pass **{s['pass']}** · "
                  f"fail **{s['fail']}** · incomplete **{s['incomplete']}** · not run **{s['not run']}** · "
                  f"no test **{s['no test']}**",
              "", "## Flags", ""]
    lines.append(f"- Requirements with **no test**: {len(f['untested_requirements'])}"
                 + (f" — {', '.join(f['untested_requirements'])}" if f["untested_requirements"]
                    else ""))
    lines.append(f"- Below SOP minimum test depth: {len(f['below_min_depth'])}"
                 + (f" — {', '.join(f['below_min_depth'])}" if f["below_min_depth"] else ""))
    lines.append(f"- Tests citing **unknown** requirement ids: "
                 f"{sum(map(len, f['unknown_requirement_refs'].values()))}"
                 + (f" — {', '.join(sorted(f['unknown_requirement_refs']))}"
                    if f["unknown_requirement_refs"] else ""))
    lines.append(f"- Tests with **no requirement**: {f['tests_without_requirement_count']} "
                 "(listed in trace_matrix.json)")
    lines += ["", "## Matrix", "",
              "| Requirement | Risk | GxP | Tests | Result | Evidence (sha256) |",
              "|---|---|---|---|---|---|"]
    for r in trace["rows"]:
        tests = "<br>".join(f"`{md_escape(short(t['id'], 80))}` — {t['outcome']}"
                            for t in r["tests"]) or "**NO TEST**"
        ev = "<br>".join(f"{e['file']} `{e['sha256'][:12]}`" for e in r["evidence"]) or "—"
        lines.append(f"| **{r['id']}** {md_escape(short(r['text'], 70))} | {r['risk']} | "
                     f"{'yes' if r['gxp'] else 'no'} | {tests} | **{r['result']}** | {ev} |")
    lines.append("")
    return "\n".join(lines)


def render_csv(trace: dict[str, Any]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["requirement", "risk", "gxp", "test", "kind", "outcome", "requirement_result",
                "evidence_sha256"])
    for r in trace["rows"]:
        ev = ";".join(e["sha256"] for e in r["evidence"])
        if not r["tests"]:
            w.writerow([r["id"], r["risk"], r["gxp"], "", "", "", r["result"], ev])
        for t in r["tests"]:
            w.writerow([r["id"], r["risk"], r["gxp"], t["id"], t["kind"], t["outcome"],
                        r["result"], ev])
    return buf.getvalue()


def write(ctx: Ctx) -> dict[str, Any]:
    t = build(ctx)
    d = ctx.out / "trace"
    write_json(d / "trace_matrix.json", t)
    write_text(d / "trace_matrix.md", render_md(t))
    write_text(d / "trace_matrix.csv", render_csv(t))
    return t

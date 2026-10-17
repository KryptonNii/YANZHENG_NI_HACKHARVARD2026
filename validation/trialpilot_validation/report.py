"""`tpv report`: validation summary report (VSR) with real counts.

The report body contains facts only (counts, deviations, signatures already given). Its own QA
approval is *not* written into the body — that would change the hash QA signs — but is read live
from the workflow (`status()`): "awaiting QA approval" until QA signs it.
"""

from __future__ import annotations

from typing import Any

from . import execute, identity, protocol, trace
from .context import Ctx, TpvError, md_escape, read_json, sha256_text, utc_now, write_json, write_text


def render(ctx: Ctx, tr: dict[str, Any], run: dict[str, Any] | None,
           proto: dict[str, Any] | None) -> str:
    s = tr["summary"]
    f = tr["flags"]
    reqs = ctx.requirements()
    by_risk = {k: sum(1 for r in reqs if r["risk"] == k) for k in ("H", "M", "L")}
    gxp = sum(1 for r in reqs if r["gxp"])
    lines = [f"# Validation Summary Report {ctx.config['report_id']}", "",
             f"System: **{ctx.config['system']}** · Procedure: SOP CSV-001 (fictional) · "
             f"Requirements: {len(reqs)} (H {by_risk['H']}, M {by_risk['M']}, L {by_risk['L']}; "
             f"GxP-relevant {gxp})", ""]
    lines += ["## 1. Protocol", ""]
    if proto:
        lines.append(f"- Protocol **{proto['record_id']}** (sha256 `{proto['sha256'][:16]}…`)")
    if run:
        m = run["manifest"]
        p = m.get("protocol", {})
        for sg in p.get("signatures", []):
            lines.append(f"- {sg['meaning']} by {sg['signer']} at {sg['signed_at']}")
        lines += ["", "## 2. Execution", "",
                  f"- Run **{run['run_id']}** by {m['executor_name']} ({m['executor']}), "
                  f"{m['started_at']} → {m['finished_at']}",
                  f"- Git commit `{(m.get('git') or {}).get('commit') or 'unknown'}`"
                  + (" (working tree had uncommitted changes)"
                     if (m.get("git") or {}).get("dirty") else ""),
                  f"- Evidence manifest sha256 `{run['manifest_sha256']}` "
                  f"({len(m['files'])} files)"]
        if run.get("signature"):
            lines.append(f"- Executed signature: {run['signature']['manifestation']}")
        c = m["counts"]
        lines += ["", "| Tests | Passed | Failed | Error | Skipped | Not run |",
                  "|---|---|---|---|---|---|",
                  f"| {c['total']} | {c['passed']} | {c['failed']} | {c['error']} | "
                  f"{c['skipped']} | {c['not_run']} |", ""]
        suites = ", ".join(f"{x['name']}: {x['status']}"
                           + (f" (exit {x['exit_code']})" if x.get("exit_code") is not None else "")
                           for x in m.get("suites", []))
        lines.append(f"Suites — {suites}")
    else:
        lines += ["", "## 2. Execution", "", "**No signed execution yet.** Results are not run."]
    lines += ["", "## 3. Requirement results", "",
              "| Pass | Fail | Incomplete | Not run | No test | Total |", "|---|---|---|---|---|---|",
              f"| {s['pass']} | {s['fail']} | {s['incomplete']} | {s['not run']} | "
              f"{s['no test']} | {tr['total_requirements']} |", ""]
    lines += ["## 4. Deviations", ""]
    devs = run["deviations"] if run else {}
    items: list[str] = []
    for rid in f["failing_requirements"]:
        failing = [t["id"] for r in tr["rows"] if r["id"] == rid for t in r["tests"]
                   if t["outcome"] in ("failed", "error")]
        items.append(f"- **{rid} failed** — " + ", ".join(f"`{md_escape(t)}`" for t in failing))
    for rid in f["untested_requirements"]:
        items.append(f"- **{rid} has no test** (gap)")
    for rid in f["below_min_depth"]:
        items.append(f"- {rid} is below the SOP minimum test depth for its risk")
    for rid, tids in sorted(f["unknown_requirement_refs"].items()):
        items.append(f"- {len(tids)} test(s) cite unknown requirement **{rid}**")
    for key, label in (("planned_not_found", "planned test not found"),
                       ("planned_not_executed", "planned test not executed"),
                       ("unplanned_tagged", "tagged test not in the approved protocol")):
        for tid in devs.get(key, []):
            items.append(f"- {label}: `{md_escape(tid)}`")
    if run:
        for e in run.get("collection_errors", []):
            items.append(f"- collection error: `{md_escape(e['id'])}`")
    lines += items or ["None."]
    lines += ["", "## 5. Acceptance", ""]
    ok = run is not None and s["pass"] == tr["total_requirements"]
    lines.append(
        f"Acceptance criteria (every requirement passes, no gaps): **{'met' if ok else 'NOT met'}**"
        f" — {s['pass']} of {tr['total_requirements']} requirements passed.")
    lines += ["", "Whether the system is fit for its intended use is a decision for QA, recorded "
                  "by QA's electronic signature on this report (status is shown live in the "
                  "validation package and in the app under /approvals).", ""]
    return "\n".join(lines)


def generate(ctx: Ctx) -> dict[str, Any]:
    tr = trace.write(ctx)
    run = execute.latest_run(ctx)
    try:
        proto = protocol.current(ctx)
    except TpvError:
        proto = None
    body = render(ctx, tr, run, proto)
    digest = sha256_text(body)
    record_id = f"{ctx.config['report_id']}-{digest[:8]}"
    d = ctx.out / "report"
    path = write_text(d / f"{record_id}.md", body)
    meta = {"record_id": record_id, "sha256": digest, "path": ctx.rel(path),
            "generated_at": utc_now(), "run_id": run["run_id"] if run else None,
            "summary": tr["summary"],
            "counts": run["manifest"]["counts"] if run else None}
    write_json(d / "current.json", meta)
    c = identity.compliance()
    c.records.register_file("validation_report", record_id, path)
    return meta


def current(ctx: Ctx) -> dict[str, Any] | None:
    p = ctx.out / "report" / "current.json"
    return read_json(p) if p.exists() else None


def status(ctx: Ctx) -> dict[str, Any]:
    cur = current(ctx)
    if cur is None:
        return {"status": "not generated"}
    c = identity.compliance()
    st = c.workflow.approval_status("validation_report", cur["record_id"])
    if st["approved"]:
        qa = [s for s in st["signatures"] if s["meaning"] == "approved"]
        return {"status": "approved", "record_id": cur["record_id"], "approval_id":
                st["approval_id"], "signatures": st["signatures"],
                "qa_signature": qa[-1] if qa else None}
    if st["status"] == "pending":
        label = "awaiting QA approval"
    elif st["approval_id"] is None:
        label = "not submitted"
    elif st["status"] == "approved":
        label = "approval invalid — the report changed after QA signed"
    else:
        label = f"{st['status']} ({st['reason']})"
    return {"status": label, "record_id": cur["record_id"], "approval_id": st["approval_id"],
            "signatures": st["signatures"], "reason": st["reason"]}


def submit(ctx: Ctx, username: str | None) -> dict[str, Any]:
    cur = current(ctx)
    if cur is None:
        raise TpvError("Run `tpv report` first.")
    c = identity.compliance()
    user = identity.resolve_user(username)
    st = c.workflow.approval_status("validation_report", cur["record_id"])
    if st["approval_id"] and st["status"] in ("pending", "approved"):
        return {"approval_id": st["approval_id"], "status": st["status"], "created": False}
    try:
        req = c.workflow.create_request("validation_report", cur["record_id"], user.username,
                                        title=f"Validation summary report {cur['record_id']}",
                                        reason="submitted for QA approval")
    except c.ComplianceError as exc:
        raise TpvError(f"{exc.code}: {exc.message}") from exc
    return {"approval_id": req.id, "status": req.status, "created": True}

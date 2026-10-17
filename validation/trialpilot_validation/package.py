"""`tpv package`: assemble `validation/out/package/` (Markdown + HTML + index) for the API/UI.

The package only *collects* what the other commands produced; missing pieces are listed as missing,
never filled in. `package_index.json` is what `/api/validation/package` serves to the UI.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from . import __version__, defects, docs, effort, execute, identity, protocol, report, trace
from .context import (
    DRAFT_STAMP,
    Ctx,
    TpvError,
    fs_path,
    md_escape,
    read_json,
    sha256_file,
    utc_now,
    write_json,
    write_text,
)
from .render import page


def _approval(record_type: str, record_id: str | None) -> dict[str, Any] | None:
    if not record_id:
        return None
    c = identity.compliance()
    st = c.workflow.approval_status(record_type, record_id)
    return {k: st.get(k) for k in ("approved", "approval_id", "status", "reason")} | {
        "signatures": [{k: s.get(k) for k in ("signer", "signer_name", "meaning", "signed_at",
                                               "manifestation", "valid")}
                       for s in st.get("signatures", [])]}


def _signoff_md(title: str, appr: dict[str, Any] | None) -> str:
    if appr is None:
        return ""
    lines = ["", "---", "", f"### Approval status: {title}", ""]
    if appr["approved"]:
        lines.append("**Approved.**")
    elif appr["approval_id"] is None:
        lines.append("**Not submitted for approval.**")
    else:
        lines.append(f"**{appr['status']}** — {appr['reason']}")
    for s in appr["signatures"]:
        mark = {True: "valid", False: "INVALID (record changed)", None: "validity unknown"}[
            s.get("valid")]
        lines.append(f"- {s['manifestation']} — signature {mark}")
    lines.append("")
    return "\n".join(lines)


def build(ctx: Ctx) -> dict[str, Any]:
    pkg = ctx.out / "package"
    if pkg.exists():
        shutil.rmtree(fs_path(pkg))
    pkg.mkdir(parents=True)
    git = ctx.git_info()
    c = identity.compliance()
    deliverables: list[dict[str, Any]] = []

    def add(did: str, title: str, md_text: str | None, fname: str, *, status: str,
            draft: bool = False, record: tuple[str, str] | None = None,
            source: str | None = None) -> None:
        entry: dict[str, Any] = {"id": did, "title": title, "status": status,
                                 "draft_stamp": draft, "md": None, "html": None, "sha256": None,
                                 "source": source}
        if md_text is not None:
            appr = _approval(*record) if record else None
            full = md_text + _signoff_md(title, appr)
            p = write_text(pkg / fname, full)
            write_text(pkg / fname.replace(".md", ".html"), page(title, full))
            entry.update(md=fname, html=fname.replace(".md", ".html"), sha256=sha256_file(p))
            if record:
                entry.update(approval_record_type=record[0], approval_record_id=record[1],
                             approval=appr)
                if appr and appr["approved"]:
                    entry["status"] = "approved"
                elif appr and appr["status"] == "pending":
                    entry["status"] = "awaiting approval"
        deliverables.append(entry)

    sop = (ctx.vdir / "company_sop.md").read_text(encoding="utf-8")
    add("SOP", "Company procedure SOP CSV-001 (fictional)", sop, "sop.md", status="reference")
    add("D1", "Validation plan", docs.plan_md(ctx), "plan.md", status="draft", draft=True)
    add("D2", "User requirements (URS)", docs.urs_md(ctx), "urs.md", status="generated")
    add("D3", "Risk assessment", docs.risk_md(ctx), "risk_assessment.md", status="generated")
    roles_md = (ctx.vdir / "ROLES.md").read_text(encoding="utf-8")
    add("ROLES", "Roles and permission matrix", roles_md, "roles.md", status="reference")

    try:
        proto = protocol.current(ctx)
        add("D4", f"OQ test protocol {proto['record_id']}",
            Path(proto["file"]).read_text(encoding="utf-8"), "protocol.md", status="generated",
            record=("test_protocol", proto["record_id"]), source=proto["path"])
    except TpvError:
        proto = None
        add("D4", "OQ test protocol", None, "protocol.md", status="missing")

    run = execute.latest_run(ctx)
    execution: dict[str, Any] | None = None
    if run:
        problems = execute.verify_manifest(run["dir"])
        dest = pkg / "evidence" / run["run_id"]
        shutil.copytree(fs_path(run["dir"]), fs_path(dest))
        m = run["manifest"]
        lines = [f"# Executed evidence — {run['run_id']}", "",
                 f"Executor: {m['executor_name']} ({m['executor']}) · {m['started_at']} → "
                 f"{m['finished_at']} · commit `{(m.get('git') or {}).get('commit')}`", "",
                 f"Manifest sha256 `{run['manifest_sha256']}` — integrity check: "
                 + ("**all files match**" if not problems else
                    f"**{len(problems)} problem(s)**: " + "; ".join(problems)), ""]
        if run.get("signature"):
            lines.append(f"Executed signature: {run['signature']['manifestation']}")
        lines += ["", "| File | sha256 | Bytes |", "|---|---|---|"]
        for f in m["files"]:
            lines.append(f"| [{md_escape(f['path'])}](evidence/{run['run_id']}/{f['path']}) | "
                         f"`{f['sha256'][:16]}…` | {f['bytes']} |")
        lines.append("")
        add("D5", "Executed evidence", "\n".join(lines), "evidence.md", status="executed")
        sig = run.get("signature") or {}
        execution = {"run_id": run["run_id"], "started_at": m["started_at"],
                     "finished_at": m["finished_at"], "executor": m["executor"],
                     "executor_name": m["executor_name"], "counts": m["counts"],
                     "manifest_sha256": run["manifest_sha256"], "git": m.get("git"),
                     "integrity_problems": problems,
                     "executed_signature": {k: sig.get(k) for k in ("signer", "signed_at",
                                                                    "manifestation")} or None,
                     "evidence_dir": f"evidence/{run['run_id']}"}
    else:
        add("D5", "Executed evidence", None, "evidence.md", status="missing")

    try:
        tr = trace.write(ctx)
        add("D6", "Traceability matrix", trace.render_md(tr), "trace_matrix.md",
            status="generated")
        shutil.copy(ctx.out / "trace" / "trace_matrix.csv", pkg / "trace_matrix.csv")
    except TpvError:
        tr = None
        add("D6", "Traceability matrix", None, "trace_matrix.md", status="missing")

    rep = report.current(ctx)
    if rep:
        rep_text = (ctx.repo / rep["path"]).read_text(encoding="utf-8")
        add("D7", f"Validation summary report {rep['record_id']}", rep_text, "report.md",
            status="awaiting approval", record=("validation_report", rep["record_id"]),
            source=rep["path"])
    else:
        add("D7", "Validation summary report", None, "report.md", status="missing")

    chg = ctx.out / "change" / "latest.json"
    if chg.exists():
        meta = read_json(chg)
        add("D8", f"Change record {meta['record_id']}",
            (ctx.repo / meta["path"]).read_text(encoding="utf-8"), "change_control.md",
            status="draft", draft=True, record=("change_record", meta["record_id"]))
    else:
        add("D8", "Change control", "# Change control\n\nNo change record generated yet "
            "(`tpv impact --base <ref> --head <ref>`).\n", "change_control.md", status="none")

    dres = defects.latest(ctx)
    if dres:
        add("DEF", "Planted-defect detection run", defects.render_md(dres), "defects.md",
            status="generated")
    part11 = ctx.vdir / "PART11.md"
    if part11.exists():
        add("P11", "21 CFR Part 11 control mapping", part11.read_text(encoding="utf-8"),
            "part11.md", status="reference")

    chain = c.audit.verify_chain()
    rep_status = report.status(ctx)
    eff = effort.summary(ctx, run)
    index = {
        "generated_at": utc_now(),
        "system": ctx.config["system"],
        "tpv_version": __version__,
        "git": git,
        "draft_stamp": DRAFT_STAMP,
        "deliverables": deliverables,
        "requirements": {"total": len(ctx.requirements()),
                         "summary": tr["summary"] if tr else None},
        "trace": ({"source": tr["source"], "summary": tr["summary"], "flags": {
            k: v for k, v in tr["flags"].items() if k != "tests_without_requirement"},
            "rows": tr["rows"]} if tr else None),
        "execution": execution,
        "protocol": {"record_id": proto["record_id"], "sha256": proto["sha256"],
                     "approval": _approval("test_protocol", proto["record_id"])} if proto else None,
        "report": {**rep_status, "summary": rep["summary"] if rep else None,
                   "counts": rep["counts"] if rep else None} if rep else
        {"status": "not generated"},
        "defects": dres,
        "audit_chain": {k: chain[k] for k in ("ok", "checked", "head_hash", "first_bad_seq")},
        "effort": eff,
    }
    write_json(pkg / "package_index.json", index)
    write_text(pkg / "index.md", index_md(index))
    write_text(pkg / "index.html", page("TrialPilot validation package", index_md(index),
                                        back=False))
    pkg_root = fs_path(pkg)
    files = [{"path": p.relative_to(pkg_root).as_posix(), "sha256": sha256_file(p)}
             for p in sorted(pkg_root.rglob("*")) if p.is_file()]
    write_json(pkg / "package_manifest.json", {"generated_at": index["generated_at"],
                                               "files": files})
    identity.audit_event("validation.package", "validation_package", index["generated_at"],
                         after_hash=sha256_file(pkg / "package_index.json"),
                         reason=f"{len(deliverables)} deliverables")
    return index


def index_md(ix: dict[str, Any]) -> str:
    g = ix["git"] or {}
    lines = [f"# {ix['system']} — validation package", "",
             f"Generated {ix['generated_at']} by tpv {ix['tpv_version']} from commit "
             f"`{g.get('commit') or 'unknown'}`" + (" (uncommitted changes present)"
                                                   if g.get("dirty") else "") + ".", "",
             "| # | Deliverable | Status | sha256 |", "|---|---|---|---|"]
    for d in ix["deliverables"]:
        name = f"[{d['title']}]({d['html']})" if d["html"] else d["title"]
        stamp = " · DRAFT" if d.get("draft_stamp") else ""
        lines.append(f"| {d['id']} | {name} | {d['status']}{stamp} | "
                     f"{('`' + d['sha256'][:12] + '`') if d['sha256'] else '—'} |")
    lines += ["", "## At a glance", ""]
    if ix["trace"]:
        s = ix["trace"]["summary"]
        f = ix["trace"]["flags"]
        lines.append(f"- Requirements: {ix['requirements']['total']} — pass {s['pass']}, fail "
                     f"{s['fail']}, incomplete {s['incomplete']}, not run {s['not run']}, "
                     f"no test {s['no test']}")
        lines.append(f"- Tests without a requirement: {f['tests_without_requirement_count']}")
    if ix["execution"]:
        c = ix["execution"]["counts"]
        lines.append(f"- Execution {ix['execution']['run_id']}: {c['total']} tests — passed "
                     f"{c['passed']}, failed {c['failed']}, error {c['error']}, skipped "
                     f"{c['skipped']}")
    else:
        lines.append("- Execution: none signed yet")
    lines.append(f"- Summary report: **{ix['report']['status']}**")
    if ix["defects"]:
        d = ix["defects"]
        lines.append(f"- Planted defects detected: **{d['detected']} of {d['planted']}** "
                     f"(applied {d['applied']})")
    a = ix["audit_chain"]
    lines.append(f"- Audit chain: {'intact' if a['ok'] else 'BROKEN at seq ' + str(a['first_bad_seq'])}"
                 f" — {a['checked']} entries, head `{(a['head_hash'] or '')[:16]}…`")
    e = ix["effort"]
    lines.append(f"- Effort: manual OQ (5 requirements) {e['manual_oq_5_requirements_minutes']}"
                 f" min; tpv execute (all) {e['tpv_execute_minutes_all_requirements']} min")
    lines.append("")
    return "\n".join(lines)

"""`tpv` — TrialPilot validation toolkit.

    tpv plan [--ai-draft]            validation plan (GAMP category drafted as DRAFT for a human)
    tpv risk                         risk assessment from requirements.yaml
    tpv protocol [--submit --as U]   OQ protocol (tests per requirement); submit for approval
    tpv sign ID --as U --meaning M   sign an approval request (PIN prompt; or TPV_PIN)
    tpv reject ID --as U --reason R  reject an approval request
    tpv status                       approval status of protocol and report
    tpv execute --as U [--e2e]       run the APPROVED protocol, capture + sign evidence
    tpv trace                        traceability matrix (flags gaps)
    tpv report [--submit --as U]     validation summary report (awaiting QA until QA signs)
    tpv impact --base A --head B     change control: files -> requirements -> tests -> record
    tpv package                      assemble validation/out/package (served by the API)
    tpv controls                     probe the compliance controls (workflow check)
    tpv defects-run                  planted-defect detection in a throwaway worktree
    tpv effort start|stop|show       stopwatch for the manual-OQ effort baseline

Exit codes: 0 ok · 2 input/prerequisite problem · 3 refused by a control.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .context import Refused, TpvError, load_ctx


def _p(msg: str = "") -> None:
    print(msg)


def cmd_plan(ctx: Any, a: argparse.Namespace) -> int:
    from . import docs

    path = docs.write_plan(ctx, ai=a.ai_draft)
    _p(f"Validation plan written: {ctx.rel(path)} (system category is a DRAFT for human decision)")
    return 0


def cmd_risk(ctx: Any, a: argparse.Namespace) -> int:
    from . import docs

    path = docs.write_risk(ctx)
    reqs = ctx.requirements()
    counts = {k: sum(1 for r in reqs if r["risk"] == k) for k in "HML"}
    _p(f"Risk assessment written: {ctx.rel(path)} — H {counts['H']}, M {counts['M']}, "
       f"L {counts['L']} ({len(reqs)} requirements)")
    return 0


def cmd_protocol(ctx: Any, a: argparse.Namespace) -> int:
    from . import protocol

    col = protocol.latest_collection(ctx) if a.reuse_collection else None
    meta = protocol.generate(ctx, collection=col)
    tagged = sum(len(v) for v in meta["planned"].values())
    _p(f"Protocol {meta['record_id']} written: {meta['path']}")
    _p(f"  {len(meta['planned'])} requirements, {tagged} requirement-test links, "
       f"{len(meta['gaps'])} without a test, {len(meta['untagged'])} tests without a requirement, "
       f"{len(meta['collection_errors'])} collection errors")
    if a.submit:
        r = protocol.submit(ctx, meta["record_id"], a.as_user,
                            title=f"OQ protocol {meta['record_id']}")
        verb = "submitted" if r["created"] else "already"
        _p(f"  Approval request {r['approval_id']} ({verb} {r['status']}). Next: a reviewer signs "
           f"'reviewed', then QA signs 'approved' (app /approvals or `tpv sign`).")
    return 0


def _sign_like(a: argparse.Namespace, reject: bool) -> int:
    from . import identity

    c = identity.compliance()
    user = identity.resolve_user(a.as_user)
    pin = identity.get_pin(user.username)
    try:
        if reject:
            req = c.workflow.reject_request(a.approval_id, user.username, pin, a.reason)
        else:
            req = c.workflow.sign_request(a.approval_id, user.username, pin, a.meaning,
                                          reason=a.reason)
    except c.ComplianceError as exc:
        _p(f"Refused: {exc.code} — {exc.message}")
        return 3
    view = c.workflow.view(req.id)
    _p(f"{req.record_type}/{req.record_id}: {req.status}")
    for s in view["signatures"]:
        _p(f"  {s['manifestation']}")
    return 0


def cmd_sign(ctx: Any, a: argparse.Namespace) -> int:
    return _sign_like(a, reject=False)


def cmd_reject(ctx: Any, a: argparse.Namespace) -> int:
    return _sign_like(a, reject=True)


def cmd_status(ctx: Any, a: argparse.Namespace) -> int:
    from . import identity, protocol, report

    c = identity.compliance()
    try:
        cur = protocol.current(ctx)
        st = c.workflow.approval_status("test_protocol", cur["record_id"])
        _p(f"Protocol {cur['record_id']}: {'APPROVED' if st['approved'] else st['reason']}"
           + (f" (request {st['approval_id']})" if st["approval_id"] else ""))
        for s in st["signatures"]:
            _p(f"  {s['manifestation']} — valid={s['valid']}")
    except TpvError as exc:
        _p(f"Protocol: {exc}")
    rs = report.status(ctx)
    _p(f"Summary report {rs.get('record_id', '')}: {rs['status']}")
    return 0


def cmd_execute(ctx: Any, a: argparse.Namespace) -> int:
    from . import execute

    res = execute.execute(ctx, username=a.as_user, e2e=a.e2e, only=a.suite or None)
    c = res["counts"]
    _p(f"Executed {res['run_id']}: {c['total']} tests — passed {c['passed']}, failed {c['failed']},"
       f" error {c['error']}, skipped {c['skipped']}, not run {c['not_run']}")
    _p(f"  Evidence: {ctx.rel(res['evidence_dir'])} (manifest sha256 {res['manifest_sha256'][:16]}…)")
    _p(f"  Signed 'executed' by {res['signature'].signer} at {res['signature'].signed_at}")
    d = res["deviations"]
    _p(f"  Deviations: {len(d['failed'])} failed/error, {len(d['planned_not_found'])} planned "
       f"tests not found, {len(d['unplanned_tagged'])} tagged tests not in protocol")
    return 1 if a.fail_on_failure and (c["failed"] or c["error"]) else 0


def cmd_trace(ctx: Any, a: argparse.Namespace) -> int:
    from . import trace

    t = trace.write(ctx)
    s, f = t["summary"], t["flags"]
    _p(f"Traceability matrix: {ctx.rel(ctx.out / 'trace' / 'trace_matrix.md')} "
       f"(source: {t['source']['kind']})")
    _p(f"  {t['total_requirements']} requirements — pass {s['pass']}, fail {s['fail']}, "
       f"incomplete {s['incomplete']}, not run {s['not run']}, no test {s['no test']}")
    _p(f"  Flags: {len(f['untested_requirements'])} requirements with no test"
       + (f" ({', '.join(f['untested_requirements'])})" if f["untested_requirements"] else "")
       + f"; {f['tests_without_requirement_count']} tests with no requirement; "
       f"{len(f['unknown_requirement_refs'])} unknown requirement ids")
    return 0


def cmd_report(ctx: Any, a: argparse.Namespace) -> int:
    from . import report

    meta = report.generate(ctx)
    _p(f"Summary report {meta['record_id']} written: {meta['path']}")
    if a.submit:
        r = report.submit(ctx, a.as_user)
        _p(f"  Approval request {r['approval_id']} ({r['status']}).")
    _p(f"  Status: {report.status(ctx)['status']}")
    return 0


def cmd_impact(ctx: Any, a: argparse.Namespace) -> int:
    from . import impact

    m = impact.run_impact(ctx, a.base, a.head, submit_as=a.as_user if a.submit else None)
    _p(f"Change record draft {m['record_id']}: {m['path']}")
    _p(f"  {len(m['files'])} changed files ({len(m['unmapped'])} unmapped) → "
       f"{len(m['requirements'])} requirements → {len(m['tests_to_rerun'])} tests to rerun")
    if m.get("approval_id"):
        _p(f"  Approval request {m['approval_id']} (pending).")
    return 0


def cmd_package(ctx: Any, a: argparse.Namespace) -> int:
    from . import package

    ix = package.build(ctx)
    _p(f"Validation package: {ctx.rel(ctx.out / 'package' / 'index.html')}")
    for d in ix["deliverables"]:
        _p(f"  {d['id']:<5} {d['status']:<18} {d['title']}")
    _p(f"  Summary report: {ix['report']['status']}")
    return 0


def cmd_controls(ctx: Any, a: argparse.Namespace) -> int:
    from . import controls

    probes = controls.run_probes()
    if a.json:
        _p(json.dumps(probes, indent=2))
    else:
        for p in probes:
            _p(f"  {p['id']} {'HOLDS ' if p['holds'] else 'FAILED'} {p['req']:<8} {p['control']}")
    return 0 if all(p["holds"] for p in probes) else 1


def cmd_defects(ctx: Any, a: argparse.Namespace) -> int:
    from . import defects

    r = defects.defects_run(ctx, only_defects=a.defect or None, only_suites=a.suite or None,
                            keep=a.keep)
    _p(f"Planted defects: detected {r['detected']} of {r['planted']} (applied {r['applied']})")
    for row in r["rows"]:
        _p(f"  {row['id']} {row['type']:<28} applied={row.get('applied')} "
           f"detected={row.get('detected')} stages={','.join(row.get('stages', [])) or '-'}")
    _p(f"  Details: {ctx.rel(ctx.out / 'defects' / 'defects.md')}")
    return 0


def cmd_experiment(ctx: Any, a: argparse.Namespace) -> int:
    from . import defects

    data = defects.experiment(ctx, Path(a.out), only=a.suite or None)
    _p(f"Experiment (NOT GxP evidence): {data['counts']}")
    return 0


def cmd_effort(ctx: Any, a: argparse.Namespace) -> int:
    from . import effort, execute

    if a.action == "start":
        s = effort.start(ctx, a.label, a.who)
        _p(f"Started '{a.label}' at {s['started_at']}")
    elif a.action == "stop":
        s = effort.stop(ctx, a.label, a.note)
        _p(f"Stopped '{a.label}': {s['minutes']} minutes")
    else:
        _p(json.dumps(effort.summary(ctx, execute.latest_run(ctx)), indent=2))
    return 0


def cmd_verify_evidence(ctx: Any, a: argparse.Namespace) -> int:
    from . import execute

    run = execute.latest_run(ctx) if not a.run_dir else None
    evdir = Path(a.run_dir) if a.run_dir else (run["dir"] if run else None)
    if evdir is None:
        raise TpvError("No execution found.")
    problems = execute.verify_manifest(evdir)
    _p("Evidence intact: every file matches the manifest." if not problems else
       "Evidence problems:\n  " + "\n  ".join(problems))
    return 0 if not problems else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="tpv", description="TrialPilot validation toolkit",
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__)
    ap.add_argument("--version", action="version", version=f"tpv {__version__}")
    ap.add_argument("--repo", help="repository root (default: auto-detect / TPV_REPO)")
    sub = ap.add_subparsers(dest="command")

    def who(p: argparse.ArgumentParser, required: bool = False) -> None:
        p.add_argument("--as", dest="as_user", required=required,
                       help="acting user (or TPV_USER)")

    p = sub.add_parser("plan", help="validation plan")
    p.add_argument("--ai-draft", action="store_true", help="AI-draft the intro (stamped DRAFT)")
    p.set_defaults(fn=cmd_plan)
    sub.add_parser("risk", help="risk assessment").set_defaults(fn=cmd_risk)
    p = sub.add_parser("protocol", help="OQ test protocol")
    p.add_argument("--submit", action="store_true", help="submit for approval")
    p.add_argument("--reuse-collection", action="store_true",
                   help="reuse the last collection instead of collecting again")
    who(p)
    p.set_defaults(fn=cmd_protocol)
    p = sub.add_parser("sign", help="sign an approval request")
    p.add_argument("approval_id")
    p.add_argument("--meaning", required=True, choices=["reviewed", "approved"])
    p.add_argument("--reason")
    who(p)
    p.set_defaults(fn=cmd_sign)
    p = sub.add_parser("reject", help="reject an approval request")
    p.add_argument("approval_id")
    p.add_argument("--reason", required=True)
    who(p)
    p.set_defaults(fn=cmd_reject)
    sub.add_parser("status", help="approval status").set_defaults(fn=cmd_status)
    p = sub.add_parser("execute", help="run the approved protocol")
    who(p)
    p.add_argument("--e2e", action="store_true", help="also run Playwright specs")
    p.add_argument("--suite", action="append", help="only this suite (repeatable)")
    p.add_argument("--fail-on-failure", action="store_true", help="exit 1 if any test failed")
    p.set_defaults(fn=cmd_execute)
    sub.add_parser("trace", help="traceability matrix").set_defaults(fn=cmd_trace)
    p = sub.add_parser("report", help="validation summary report")
    p.add_argument("--submit", action="store_true", help="submit for QA approval")
    who(p)
    p.set_defaults(fn=cmd_report)
    p = sub.add_parser("impact", help="change control impact analysis")
    p.add_argument("--base", required=True)
    p.add_argument("--head", default="HEAD", help="git ref, or WORKTREE for uncommitted changes")
    p.add_argument("--submit", action="store_true", help="submit the change record")
    who(p)
    p.set_defaults(fn=cmd_impact)
    sub.add_parser("package", help="assemble the validation package").set_defaults(fn=cmd_package)
    p = sub.add_parser("controls", help="probe compliance controls")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_controls)
    p = sub.add_parser("defects-run", help="planted-defect detection run")
    p.add_argument("--defect", action="append", help="only this defect id (repeatable)")
    p.add_argument("--suite", action="append", help="only this suite (repeatable)")
    p.add_argument("--keep", action="store_true", help="keep the throwaway worktree")
    p.set_defaults(fn=cmd_defects)
    p = sub.add_parser("experiment", help=argparse.SUPPRESS)
    p.add_argument("--out", required=True)
    p.add_argument("--suite", action="append")
    p.set_defaults(fn=cmd_experiment)
    p = sub.add_parser("effort", help="manual-OQ effort stopwatch")
    p.add_argument("action", choices=["start", "stop", "show"])
    p.add_argument("label", nargs="?", default="manual")
    p.add_argument("--who")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_effort)
    p = sub.add_parser("verify-evidence", help="check evidence files against the manifest")
    p.add_argument("run_dir", nargs="?")
    p.set_defaults(fn=cmd_verify_evidence)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 0
    try:
        ctx = load_ctx(Path(a.repo) if a.repo else None)
        return int(a.fn(ctx, a))
    except Refused as exc:
        print(f"tpv: REFUSED — {exc}", file=sys.stderr)
        return 3
    except TpvError as exc:
        print(f"tpv: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

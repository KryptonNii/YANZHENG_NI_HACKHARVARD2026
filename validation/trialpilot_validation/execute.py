"""`tpv execute`: run the approved OQ protocol and capture signed evidence.

1. Gate: the current protocol (exact sha256) must be approved — otherwise refuse (exit 3).
2. Re-authenticate the executor (PIN) before running anything.
3. Run every suite (+ Playwright with --e2e), keep raw JSON results, JUnit XML and logs.
4. Write `evidence_manifest.json`: sha256 + size + UTC mtime of every evidence file, executor,
   git commit, protocol id/hash/approval, per-suite exit codes and counts.
5. Sign the manifest hash with meaning `executed` (the executor's PIN) and audit the run.

Results are copied from what pytest/Playwright reported; tpv computes counts, nothing else.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__, identity, protocol
from .context import Ctx, Refused, TpvError, fs_path, read_json, sha256_file, utc_now, write_json
from .runner import e2e_outcomes, load_suite_tests, run_e2e, run_suite, scan_e2e

MANIFEST = "evidence_manifest.json"
SIGNATURE = "executed_signature.json"


def check_gate(ctx: Ctx) -> dict[str, Any]:
    cur = protocol.current(ctx)
    c = identity.compliance()
    c.records.register_file("test_protocol", cur["record_id"], cur["file"])
    if not Path(cur["file"]).exists():
        raise Refused(f"Protocol file {cur['path']} is missing.")
    st = c.workflow.approval_status("test_protocol", cur["record_id"])
    if not st["approved"]:
        nxt = st.get("next_meaning")
        hint = (
            f"\n  Next signature needed: '{nxt}'." if nxt else ""
        ) + (
            "\n  Submit it:  tpv protocol --submit --as alex.author" if not st["approval_id"]
            else f"\n  Sign it in the app (/approvals) or: tpv sign {st['approval_id']} "
                 f"--as <reviewer|qa> --meaning <reviewed|approved>"
        )
        raise Refused(
            f"Protocol {cur['record_id']} is not approved: {st['reason']}.{hint}\n"
            "Refusing to execute (SOP CSV-001 §5.1: protocols are approved before execution)."
        )
    return {**cur, "approval": st}


def _counts(tests: list[dict[str, Any]]) -> dict[str, int]:
    c = Counter((t.get("outcome") or "not_run") for t in tests)
    return {k: c.get(k, 0) for k in ("passed", "failed", "error", "skipped", "xfailed",
                                      "xpassed", "not_run")} | {"total": len(tests)}


def run_all(ctx: Ctx, evdir: Path, *, e2e: bool, only: list[str] | None = None) -> dict[str, Any]:
    """Run suites into `evdir`; return {suites, tests, collection_errors, counts}."""
    suites = [s for s in ctx.config["suites"] if not only or s["name"] in only]
    summaries = [run_suite(ctx, s, evdir, "run") for s in suites]
    tests, errors = load_suite_tests(evdir, summaries)
    e2e_tests = scan_e2e(ctx)
    if e2e:
        es = run_e2e(ctx, evdir)
        summaries.append(es)
        outcomes = e2e_outcomes(evdir, es)
        for t in e2e_tests:
            t["outcome"] = outcomes.get((Path(t["file"]).name, t["name"]))
    tests += e2e_tests
    return {"suites": summaries, "tests": tests, "collection_errors": errors,
            "counts": _counts(tests)}


def _deviations(planned: dict[str, list[str]], tests: list[dict[str, Any]]) -> dict[str, Any]:
    planned_ids = sorted({t for ids in planned.values() for t in ids})
    executed = {t["id"] for t in tests if t.get("outcome")}
    known = {t["id"] for t in tests}
    return {
        "planned_not_found": [t for t in planned_ids if t not in known],
        "planned_not_executed": [t for t in planned_ids if t in known and t not in executed],
        "unplanned_tagged": sorted(t["id"] for t in tests
                                   if t.get("reqs") and t["id"] not in set(planned_ids)),
        "failed": sorted(t["id"] for t in tests if t.get("outcome") in ("failed", "error")),
    }


def _env_info(ctx: Ctx) -> dict[str, Any]:
    uv = shutil.which("uv")
    uv_version = None
    if uv:
        try:
            uv_version = subprocess.run([uv, "--version"], capture_output=True, text=True,
                                        timeout=30).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            uv_version = None
    return {"python": sys.version.split()[0], "platform": platform.platform(),
            "machine": platform.machine(), "uv": uv_version, "tpv_version": __version__,
            "test_env": {k: str(v) for k, v in (ctx.config.get("env") or {}).items()}}


def build_manifest(evdir: Path, meta: dict[str, Any]) -> dict[str, Any]:
    files = []
    root = fs_path(evdir)
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name not in (MANIFEST, SIGNATURE):
            st = p.stat()
            files.append({
                "path": p.relative_to(root).as_posix(),
                "sha256": sha256_file(p),
                "bytes": st.st_size,
                "modified_utc": datetime.fromtimestamp(st.st_mtime, UTC).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"),
            })
    return {**meta, "files": files}


def execute(ctx: Ctx, *, username: str | None, e2e: bool = False,
            only: list[str] | None = None,
            extra_evidence: list[Path] | None = None) -> dict[str, Any]:
    c = identity.compliance()
    gate = check_gate(ctx)
    user = identity.resolve_user(username)
    if not c.roles.can(user.role, "sign.executed"):
        raise Refused(f"{user.username} ({user.role}) may not execute/sign test runs.")
    pin = identity.get_pin(user.username)
    try:
        c.esign.reauthenticate(user.username, pin)
    except c.ComplianceError as exc:
        raise Refused(f"{exc.code}: {exc.message}") from exc

    started = utc_now()
    run_id = f"RUN-{started.replace('-', '').replace(':', '')}-{uuid.uuid4().hex[:4]}"
    evdir = ctx.out / "evidence" / run_id
    evdir.mkdir(parents=True, exist_ok=True)
    if extra_evidence:
        dest = fs_path(evdir / "preflight")
        dest.mkdir(parents=True, exist_ok=True)
        for path in extra_evidence:
            shutil.copy2(fs_path(path), dest / path.name)
    identity.audit_event("validation.execute_start", "test_execution", run_id, user=user,
                         reason=f"executing {gate['record_id']}")
    result = run_all(ctx, evdir, e2e=e2e, only=only)
    deviations = _deviations(gate.get("planned", {}), result["tests"])
    write_json(evdir / "tests.json", {"run_id": run_id, "tests": result["tests"],
                                      "collection_errors": result["collection_errors"]})
    write_json(evdir / "environment.json", _env_info(ctx))
    meta = {
        "run_id": run_id,
        "started_at": started,
        "finished_at": utc_now(),
        "executor": user.username,
        "executor_name": user.display_name,
        "executor_role": user.role,
        "git": ctx.git_info(),
        "protocol": {"record_id": gate["record_id"], "sha256": gate["sha256"],
                     "approval_id": gate["approval"]["approval_id"],
                     "signatures": [
                         {k: s.get(k) for k in ("signer", "meaning", "signed_at", "valid")}
                         for s in gate["approval"]["signatures"]]},
        "suites": [{k: s.get(k) for k in ("name", "status", "exit_code", "started_at",
                                          "finished_at")} for s in result["suites"]],
        "counts": result["counts"],
        "deviations": {k: len(v) for k, v in deviations.items()},
        "subset": only or None,
        "e2e_requested": e2e,
    }
    write_json(evdir / "deviations.json", deviations)
    manifest = build_manifest(evdir, meta)
    mpath = write_json(evdir / MANIFEST, manifest)
    mhash = sha256_file(mpath)
    try:
        sig = c.esign.sign("test_execution", run_id, mhash, user.username, user.role, "executed",
                           pin, reason=f"executed {gate['record_id']}; manifest sha256 {mhash[:12]}")
    except c.ComplianceError as exc:
        raise Refused(f"Evidence captured but not signed: {exc.code}: {exc.message}") from exc
    c.records.register_file("test_execution", run_id, mpath)
    write_json(evdir / SIGNATURE, {**sig.model_dump(mode="json"),
                                   "manifestation": c.esign.manifestation(sig),
                                   "manifest_sha256": mhash})
    identity.audit_event("validation.execute_finish", "test_execution", run_id, user=user,
                         after_hash=mhash, reason=f"counts {result['counts']}")
    write_json(ctx.out / "evidence" / "latest.json",
               {"run_id": run_id, "path": ctx.rel(evdir), "manifest_sha256": mhash})
    return {"run_id": run_id, "evidence_dir": evdir, "manifest_sha256": mhash,
            "counts": result["counts"], "deviations": deviations, "signature": sig}


def latest_run(ctx: Ctx) -> dict[str, Any] | None:
    p = ctx.out / "evidence" / "latest.json"
    if not p.exists():
        return None
    ptr = read_json(p)
    evdir = ctx.repo / ptr["path"] if not Path(ptr["path"]).is_absolute() else Path(ptr["path"])
    if not (evdir / MANIFEST).exists():
        raise TpvError(f"Latest run {ptr['run_id']} has no manifest.")
    manifest = read_json(evdir / MANIFEST)
    tests = read_json(evdir / "tests.json")
    sig = read_json(evdir / SIGNATURE) if (evdir / SIGNATURE).exists() else None
    return {"run_id": ptr["run_id"], "dir": evdir, "manifest": manifest,
            "manifest_sha256": sha256_file(evdir / MANIFEST), "tests": tests["tests"],
            "collection_errors": tests.get("collection_errors", []), "signature": sig,
            "deviations": read_json(evdir / "deviations.json")
            if (evdir / "deviations.json").exists() else {}}


def verify_manifest(evdir: Path) -> list[str]:
    """Return problems (empty = every file matches its recorded sha256)."""
    manifest = read_json(evdir / MANIFEST)
    problems = []
    listed = set()
    root = fs_path(evdir)
    for f in manifest["files"]:
        listed.add(f["path"])
        p = root / f["path"]
        if not p.exists():
            problems.append(f"missing: {f['path']}")
        elif sha256_file(p) != f["sha256"]:
            problems.append(f"hash mismatch: {f['path']}")
    for p in root.rglob("*"):
        rel = p.relative_to(root).as_posix()
        if p.is_file() and p.name not in (MANIFEST, SIGNATURE) and rel not in listed:
            problems.append(f"not in manifest: {rel}")
    return problems

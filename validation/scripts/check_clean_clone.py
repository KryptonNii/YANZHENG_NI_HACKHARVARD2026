"""Exercise the real validation pipeline in a local clean clone.

Run with the validation interpreter, for example:
    uv run --project validation python validation/scripts/check_clean_clone.py --e2e

All signatures here are automated test fixtures using the published fictional demo
identities. They are not human approvals or evidence of regulatory validation.
The summary report deliberately remains awaiting human QA approval.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def worker(repo: Path, output: Path, *, e2e: bool) -> int:
    from trialpilot_api.compliance import ComplianceError, audit, store, workflow

    from trialpilot_validation import docs, execute, package, protocol, report, trace
    from trialpilot_validation.context import Refused, load_ctx, read_json, sha256_file, write_json

    ctx = load_ctx(repo)
    ctx.config["system"] = "TrialPilot (automated check; fictional demo identities)"
    db = store.configure(repo / "var" / "clean-clone-test.sqlite")
    try:
        docs.write_plan(ctx)
        docs.write_risk(ctx)
        print("Collecting the clean clone's real test suites...", flush=True)
        meta = protocol.generate(ctx)
        try:
            execute.check_gate(ctx)
        except Refused:
            pass
        else:
            raise AssertionError("Unapproved protocol was allowed to execute")

        req = protocol.submit(ctx, meta["record_id"], "alex.author", "Automated fixture protocol")
        for signer, pin, meaning, expected in (
            ("alex.author", "1111", "approved", "self_approval_forbidden"),
            ("sam.qa", "3333", "approved", "out_of_order"),
        ):
            try:
                workflow.sign_request(req["approval_id"], signer, pin, meaning)
            except ComplianceError as exc:
                assert exc.code == expected, exc.code
            else:
                raise AssertionError(f"Expected refusal: {expected}")

        # Automated fixtures, just like the workflow tests; never a human sign-off.
        workflow.sign_request(req["approval_id"], "riley.reviewer", "2222", "reviewed",
                              reason="Automated isolated test fixture; not human review")
        workflow.sign_request(req["approval_id"], "sam.qa", "3333", "approved",
                              reason="Automated isolated test fixture; not human QA approval")
        os.environ["TPV_PIN"] = "1111"
        print("Executing the approved fixture protocol...", flush=True)
        result = execute.execute(ctx, username="alex.author", e2e=e2e)
        problems = execute.verify_manifest(result["evidence_dir"])
        assert not problems, problems
        tr = trace.write(ctx)
        report.generate(ctx)
        report.submit(ctx, "alex.author")
        ix = package.build(ctx)
        assert ix["report"]["status"] == "awaiting QA approval"
        assert ix["audit_chain"]["ok"] is True
        assert ix["execution"]["integrity_problems"] == []
        manifest = read_json(output / "package" / "package_manifest.json")
        assert all(sha256_file(output / "package" / item["path"]) == item["sha256"]
                   for item in manifest["files"])
        run = execute.latest_run(ctx)
        assert run is not None
        summary = {
            "note": "Automated isolated integration test. Fictional demo-user signatures; "
                    "not human approvals or regulatory validation evidence.",
            "git": ctx.git_info(),
            "clone": str(repo),
            "output": str(output),
            "protocol_gate_refused_before_approval": True,
            "self_approval_refused": True,
            "out_of_order_refused": True,
            "counts": result["counts"],
            "failed_tests": result["deviations"]["failed"],
            "suites": run["manifest"]["suites"],
            "trace": tr["summary"],
            "untested_requirements": tr["flags"]["untested_requirements"],
            "collection_errors": run["collection_errors"],
            "report_status": ix["report"]["status"],
            "evidence_integrity_problems": problems,
            "package_hashes_verified": len(manifest["files"]),
            "audit_chain": audit.verify_chain(),
        }
        write_json(output / "summary.json", summary)
        print(json.dumps(summary, indent=2), flush=True)
        counts = result["counts"]
        bad_suites = any(s["status"] != "ran" or s.get("exit_code") != 0
                         for s in summary["suites"])
        return int(bool(counts["failed"] or counts["error"] or counts["xpassed"]
                        or run["collection_errors"] or bad_suites))
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--e2e", action="store_true", help="Install locked web dependencies and run Playwright")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.worker:
        return worker(args.worker.resolve(), args.output.resolve(), e2e=args.e2e)

    source = Path(__file__).resolve().parents[2]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (args.output or source / "validation" / "out" / "clean-clone" / stamp).resolve()
    output.mkdir(parents=True, exist_ok=False)
    repo = Path(tempfile.mkdtemp(prefix="tpv-clean-")) / "repo"
    # Preserve the clone for inspection; do not delete or modify the shared checkout.
    print(f"Clean clone: {repo}\nResults: {output}", flush=True)
    subprocess.run(["git", "clone", "--local", "--no-hardlinks", str(source), str(repo)],
                   check=True)
    env = {k: v for k, v in os.environ.items()
           if k not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "UV_PROJECT_ENVIRONMENT",
                        "TPV_PIN", "TPV_USER", "E2E_MOCK", "E2E_SCREENSHOTS", "TP_DB_PATH",
                        "TP_DATA_DIR", "TP_COMPLIANCE_DB")}
    env.update(
        UV_PYTHON=sys._base_executable,
        PYTHONIOENCODING="utf-8",
        TPV_REPO=str(repo), TP_VALIDATION_OUT=str(output),
        TP_COMPLIANCE_DB=str(repo / "var" / "clean-clone-test.sqlite"),
        TP_SECRET_PEPPER="clean-clone-test-fixture-not-a-production-secret",
        TP_DEMO_PINS="", DEMO_OFFLINE="1", CI="1", E2E_API_PORT="8007", E2E_WEB_PORT="5180",
        TP_RUNTIME_CACHE_DIR=str(repo / "var" / "importers"),
    )
    if args.e2e:
        pnpm = shutil.which("pnpm")
        if pnpm is None:
            raise SystemExit("pnpm is required for --e2e")
        setup = subprocess.run(
            [pnpm, "--dir", str(repo / "web"), "install", "--frozen-lockfile"],
            cwd=repo, env=env, check=False, capture_output=True, text=True, encoding="utf-8",
            errors="replace",
        )
        (output / "web-install.log").write_text(setup.stdout + setup.stderr, encoding="utf-8")
        if setup.returncode:
            (output / "setup_failure.json").write_text(json.dumps({
                "stage": "locked web dependency installation", "exit_code": setup.returncode,
                "clone": str(repo), "log": str(output / "web-install.log"),
                "note": "The install failed; no test execution or signatures were created.",
            }, indent=2), encoding="utf-8")
            print(f"Web dependency installation failed; see {output / 'web-install.log'}",
                  file=sys.stderr)
            return setup.returncode
    uv = shutil.which("uv") or "uv"
    cmd = [uv, "run", "--frozen", "--project", str(repo / "validation"), "python",
           str(Path(__file__).resolve()), "--worker", str(repo), "--output", str(output)]
    if args.e2e:
        cmd.append("--e2e")
    return subprocess.run(cmd, cwd=repo, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

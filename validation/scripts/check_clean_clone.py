"""Exercise the real validation pipeline in a local clean clone.

Run with the validation interpreter, for example:
    uv run --project validation python validation/scripts/check_clean_clone.py --e2e

All signatures here are automated test fixtures using the published fictional demo
identities. They are not human approvals or evidence of regulatory validation.
The summary report deliberately remains awaiting human QA approval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

# Automated signatures use the published fictional demo identities. This prefix is
# written onto their manifestations so a package cannot be read as human approval.
DEMO_MARK = "DEMO FIXTURE — not a human approval — "
_MANIFEST = re.compile(
    r"(?<!DEMO FIXTURE — not a human approval — )"
    r"([A-Za-z][A-Za-z .'-]{0,40} \([a-z0-9.]+, "
    r"(?:author|reviewer|qa|admin|viewer)\) — "
    r"(?:AUTHORED|REVIEWED|APPROVED|EXECUTED|VERIFIED) — )"
)
HISTORICAL_RUN = "validation/out/clean-clone/20261017T023042Z"


def _fs(path: Path) -> Path:
    try:
        from trialpilot_api.compliance.hashing import fs_path
    except ImportError:
        return path
    return fs_path(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(_fs(path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package_downloads(output: Path) -> dict:
    """Exercise the real package and audit HTTP routes, including long attachments."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from trialpilot_api.compliance.routes import router

    app = FastAPI()
    app.include_router(router)
    manifest = json.loads(_fs(output / "package/package_manifest.json").read_text(encoding="utf-8"))
    checked = []
    with TestClient(app) as client:
        response = client.get("/api/validation/package")
        response.raise_for_status()
        index = response.json()
        assert index["signature_class"] == "demo"
        assert index["report"]["status"] == "awaiting QA approval"
        for entry in manifest["files"]:
            response = client.get("/api/validation/package/files/" + quote(entry["path"]))
            response.raise_for_status()
            actual = hashlib.sha256(response.content).hexdigest()
            assert actual == entry["sha256"], entry["path"]
            checked.append({"path": entry["path"], "sha256": actual, "bytes": len(response.content)})
        chain = client.get("/api/audit/verify")
        chain.raise_for_status()
        assert chain.json()["ok"] is True
    return {"transport": "HTTP ASGI TestClient; real compliance router", "files": checked,
            "verified_count": len(checked), "audit_chain": chain.json()}


def require_free_ports(ports: tuple[int, ...]) -> None:
    for port in ports:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is occupied. Existing process was not stopped.")


def build_checks(repo: Path, output: Path, *, e2e: bool) -> list[dict]:
    """Keep lint, types, generated contracts, licences, web units and build in evidence."""
    uv = shutil.which("uv") or "uv"
    commands = []
    for pkg in ("contracts", "engine", "api", "science", "validation"):
        commands.append((f"ruff-{pkg}", repo / pkg, [uv, "run", "--frozen", "ruff", "check", "."]))
    for pkg in ("contracts", "engine"):
        targets = [f"trialpilot_{pkg}"] + (["gen.py"] if pkg == "contracts" else [])
        commands.append((f"mypy-{pkg}", repo / pkg, [uv, "run", "--frozen", "mypy", "--strict", *targets]))
    commands += [
        ("generated-contracts", repo, [uv, "run", "--frozen", "--project", "contracts", "python", "contracts/gen.py", "--check"]),
        ("parameter-library", repo, [uv, "run", "--frozen", "--project", "contracts", "python", "-m", "trialpilot_contracts", "data/params"]),
        ("licences", repo, [uv, "run", "--frozen", "--project", "contracts", "python", ".github/scripts/third_party.py", "--check"]),
    ]
    if e2e:
        pnpm = os.environ.get("TPV_PNPM") or shutil.which("pnpm") or "pnpm"
        for task in ("typecheck", "test", "build"):
            commands.append((f"web-{task}", repo, [pnpm, "--dir", "web", task]))
    dest = output / "preflight"
    dest.mkdir()
    results = []
    for name, cwd, cmd in commands:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", check=False)
        log = dest / f"{name}.log"
        log.write_text(f"$ {cmd!r}\n{proc.stdout}\n{proc.stderr}", encoding="utf-8")
        results.append({"name": name, "exit_code": proc.returncode, "log": log.name,
                        "sha256": _sha256(log)})
        print(f"Preflight {name}: exit {proc.returncode}", flush=True)
    (dest / "checks.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def _mark_text(text: str) -> str:
    return _MANIFEST.sub(lambda m: DEMO_MARK + m.group(1), text)


def _mark_signature(sig: dict) -> None:
    sig["actor_class"] = "demo"
    sig["human_approval"] = False
    manifestation = sig.get("manifestation")
    if isinstance(manifestation, str):
        sig["manifestation"] = _mark_text(manifestation)


def label_demo_package(output: Path) -> str:
    """Mark automated signatures as demo fixtures and refresh the package manifest.

    Returns the sha256 of the labeled `package_index.json`. Does not change the
    report status and does not rewrite copied evidence files.
    """
    pkg = output / "package"
    index_path = pkg / "package_index.json"
    index = json.loads(_fs(index_path).read_text(encoding="utf-8"))
    if index.get("report", {}).get("status") != "awaiting QA approval":
        raise AssertionError(index.get("report", {}).get("status"))
    index["signature_class"] = "demo"
    index["human_qa_approval"] = False
    index["signature_note"] = (
        "Every signature in this package is an automated demo fixture using a "
        "fictional identity. It is not a human approval. The summary report remains "
        "awaiting QA approval."
    )
    protocol = index.get("protocol") or {}
    for sig in (protocol.get("approval") or {}).get("signatures") or []:
        _mark_signature(sig)
    for deliverable in index.get("deliverables") or []:
        for sig in (deliverable.get("approval") or {}).get("signatures") or []:
            _mark_signature(sig)
    executed = (index.get("execution") or {}).get("executed_signature")
    if isinstance(executed, dict):
        _mark_signature(executed)

    evidence = _fs(pkg / "evidence")
    root = _fs(pkg)
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".html"}:
            continue
        if path == evidence or evidence in path.parents:
            continue
        original = path.read_text(encoding="utf-8")
        marked = _mark_text(original)
        if path.name in {"index.md", "index.html"} and index["signature_note"] not in marked:
            first, _, rest = marked.partition("\n")
            marked = first + "\n\n" + index["signature_note"] + "\n" + rest
        if marked != original:
            path.write_text(marked, encoding="utf-8", newline="\n")

    for deliverable in index.get("deliverables") or []:
        md_name = deliverable.get("md")
        if md_name:
            deliverable["sha256"] = _sha256(pkg / md_name)
    _fs(index_path).write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8", newline="\n")
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "package_manifest.json":
            files.append({"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)})
    manifest = {"generated_at": index["generated_at"], "files": files}
    manifest_path = pkg / "package_manifest.json"
    _fs(manifest_path).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8", newline="\n")
    return _sha256(index_path)


def urs009_observation(repo: Path, output: Path) -> dict:
    """Record the cold-path sample actually executed. Do not change the 300 ms gate."""
    source_path = repo / "validation" / "tests" / "oq" / "test_oq_scenarios.py"
    source = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
    observation: dict = {
        "requirement_p50_ms": 300,
        "draws": 2000,
        "seeds": list(range(200, 207)),
        "cache": "miss",
        "header": "X-Compute-Ms",
        "path": "cold",
        "path_note": (
            "Each of the seven seeds is distinct, so every call is a compute-cache miss. "
            "Forecast, supply and the engine run. This is not the slider hot path."
        ),
        "source_encodes_cold_path": (
            "range(200, 207)" in source and "draws=2000" in source
            and 'resp.headers["X-Cache"] == "miss"' in source
            and "statistics.median(times) < 300" in source
        ),
        "outcome": "not found",
        "median_ms": None,
        "samples_ms": None,
    }
    results = list((output / "evidence").glob("*/validation.results.json"))
    if not results:
        return observation
    data = json.loads(_fs(results[0]).read_text(encoding="utf-8"))
    test = next((t for t in data.get("tests", [])
                 if str(t.get("id", "")).endswith("test_compute_p50_latency_under_300ms")), None)
    if test is None:
        return observation
    observation["outcome"] = test.get("outcome")
    samples = (test.get("properties") or {}).get("cold_samples_ms")
    if samples is not None:
        observation["samples_ms"] = json.loads(samples)
        observation["median_ms"] = statistics.median(observation["samples_ms"])
    message = test.get("message") or ""
    matched = re.search(r"median ([\d.]+) ms: \[([^\]]+)\]", message)
    if matched:
        observation["median_ms"] = float(matched.group(1))
        observation["samples_ms"] = [float(part) for part in matched.group(2).split(",")]
    compared = re.search(r"assert ([\d.]+) < 300", message)
    if compared and observation["median_ms"] is None:
        observation["median_ms"] = float(compared.group(1))
    return observation


def commit_scope(source: Path) -> dict:
    """Read-only check of whether claimed fixes are in HEAD. Does not stage anything."""
    def show(path: str) -> str:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{path}"], cwd=source, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        return (proc.stdout or "") if proc.returncode == 0 else ""

    def tracked(path: str) -> bool:
        proc = subprocess.run(
            ["git", "cat-file", "-e", f"HEAD:{path}"], cwd=source, capture_output=True,
        )
        return proc.returncode == 0

    head_proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )
    head = (head_proc.stdout or "").strip()
    watched = [
        "engine/tests/test_uncertainty.py", "engine/tests/test_model.py",
        "engine/trialpilot_engine/uncertainty.py", "engine/trialpilot_engine/supply.py",
        "science/tests/test_reproduce.py", "science/out/results.json",
        "web/package.json", "web/pnpm-workspace.yaml",
        "web/src/features/scenario/SciencePage.tsx",
        "web/src/features/command", "web/src/features/compliance",
    ]
    status_proc = subprocess.run(
        ["git", "status", "--porcelain", "--", *watched], cwd=source, capture_output=True,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    status = (status_proc.stdout or "").splitlines()
    uncertainty = show("engine/tests/test_uncertainty.py")
    model = show("engine/tests/test_model.py")
    supply = show("engine/trialpilot_engine/supply.py")
    science = show("science/tests/test_reproduce.py")
    package_json = show("web/package.json")
    chunk = next((line.strip() for line in supply.splitlines()
                  if "_CHUNK_SITE_DRAWS" in line and not line.strip().startswith("#")), "")
    return {
        "head": head,
        "included_in_this_run": "HEAD only. Uncommitted work from other modules was not cloned.",
        "a2_null_assertions_in_head": (
            "def test_to_range_is_ordered_and_none_for_unknown" in uncertainty
            and "np.isnan(unknown.p50)" not in uncertainty
            and "np.isnan(r.cost_usd.p50)" not in model
        ),
        "a3_supply_chunk_in_head": chunk,
        "a3_chunk_65536_in_head": "65536" in chunk.replace("_", ""),
        "a10_urs014_tag_in_head": 'req("URS-014")' in science,
        "a8_package_manager_in_head": '"packageManager"' in package_json,
        "pnpm_workspace_file_in_head": tracked("web/pnpm-workspace.yaml"),
        "uncommitted_watched_paths": status,
    }


def worker(repo: Path, output: Path, *, e2e: bool) -> int:
    from trialpilot_api.compliance import ComplianceError, audit, store, workflow

    from trialpilot_validation import docs, execute, package, protocol, report, trace
    from trialpilot_validation.context import Refused, load_ctx, read_json, sha256_file, write_json

    ctx = load_ctx(repo)
    expected = os.environ.get("TPV_EXPECTED_COMMIT")
    if expected and ctx.git_info()["commit"] != expected:
        raise AssertionError("Clone HEAD differs from the explicitly selected source commit")
    preflight = build_checks(repo, output, e2e=e2e)
    ctx.config["system"] = (
        "TrialPilot (automated check; fictional demo identities; "
        "signatures are demo fixtures, not human approvals)"
    )
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
        result = execute.execute(ctx, username="alex.author", e2e=e2e,
                                 extra_evidence=list((output / "preflight").iterdir()))
        problems = execute.verify_manifest(result["evidence_dir"])
        assert not problems, problems
        tr = trace.write(ctx)
        report.generate(ctx)
        report.submit(ctx, "alex.author")
        ix = package.build(ctx)
        assert ix["report"]["status"] == "awaiting QA approval"
        assert ix["audit_chain"]["ok"] is True
        assert ix["execution"]["integrity_problems"] == []
        before_label = sha256_file(output / "package" / "package_index.json")
        labeled = label_demo_package(output)
        manifest = read_json(output / "package" / "package_manifest.json")
        assert all(sha256_file(output / "package" / item["path"]) == item["sha256"]
                   for item in manifest["files"])
        audit.append(
            "alex.author", "author", "validation.package.demo_label",
            "validation_package", ix["generated_at"], before_label, labeled,
            "Marked automated signatures as demo fixtures; not a human approval. "
            "Report remains awaiting QA approval.",
        )
        run = execute.latest_run(ctx)
        assert run is not None
        downloads = verify_package_downloads(output)
        write_json(output / "package-downloads.json", downloads)
        scope_path = output / "commit_scope.json"
        scope = read_json(scope_path) if scope_path.is_file() else commit_scope(repo)
        summary = {
            "note": "Automated isolated integration test. Fictional demo-user signatures; "
                    "not human approvals or regulatory validation evidence.",
            "signature_class": "demo",
            "human_qa_approval": False,
            "git": ctx.git_info(),
            "clone": str(repo),
            "output": str(output),
            "commit_scope": scope,
            "protocol_gate_refused_before_approval": True,
            "self_approval_refused": True,
            "out_of_order_refused": True,
            "counts": result["counts"],
            "build_checks": preflight,
            "failed_tests": result["deviations"]["failed"],
            "urs009": urs009_observation(repo, output),
            "preserved_historical_run": {
                "path": HISTORICAL_RUN,
                "commit": "38e207387a38e4b9d6619d6194cd8279d2865416",
                "counts": {"passed": 507, "failed": 3, "total": 510},
                "urs009_full_run_median_ms": 664.1,
                "note": "Not overwritten, deleted, or rewritten as a pass. "
                        "Its standalone retry is not a result of this run.",
            },
            "suites": run["manifest"]["suites"],
            "trace": tr["summary"],
            "untested_requirements": tr["flags"]["untested_requirements"],
            "collection_errors": run["collection_errors"],
            "report_status": ix["report"]["status"],
            "evidence_integrity_problems": problems,
            "package_hashes_verified": len(manifest["files"]),
            "package_downloads_verified": downloads["verified_count"],
            "labeled_package_index_sha256": labeled,
            "audit_chain": audit.verify_chain(),
            "python": sys.version,
            "web_installer": {
                "executable": os.environ.get("TPV_PNPM", ""),
                "version": os.environ.get("TPV_PNPM_VERSION", ""),
                "release_age_override": False,
            },
        }
        write_json(output / "summary.json", summary)
        print(json.dumps(summary, indent=2), flush=True)
        counts = result["counts"]
        bad_suites = any(s["status"] != "ran" or s.get("exit_code") != 0
                         for s in summary["suites"])
        return int(bool(any(check["exit_code"] for check in preflight)
                        or counts["failed"] or counts["error"] or counts["xpassed"]
                        or run["collection_errors"] or bad_suites))
    finally:
        db.close()


def resolve_pnpm(home: Path | None = None) -> str:
    """Use pnpm 9.15.9, the version named by api/Dockerfile and lockfileVersion 9.

    No release-age override and no lockfile edit. When pnpm is not already on PATH,
    corepack materializes 9.15.9 under `home` and does not change the user profile.
    """
    found = shutil.which("pnpm")
    if found:
        return found
    corepack = shutil.which("corepack")
    if corepack is None:
        raise SystemExit("pnpm is required for --e2e")
    if home is None:
        home = Path(tempfile.mkdtemp(prefix="tpv-pnpm-"))
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["COREPACK_HOME"] = str(home)
    prepared = subprocess.run(
        [corepack, "prepare", "pnpm@9.15.9", "--activate"],
        cwd=home, env=env, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    direct = home / "v1" / "pnpm" / "9.15.9" / "bin" / "pnpm.cjs"
    if not direct.is_file():
        direct = next((path for path in home.rglob("pnpm.cjs")
                       if path.is_file() and path.parent.name == "bin"), None)
    node = shutil.which("node")
    if direct is not None and direct.is_file() and node:
        shim_dir = home / "shims"
        shim_dir.mkdir(parents=True, exist_ok=True)
        shim = shim_dir / "pnpm.cmd"
        shim.write_text(f'@echo off\r\n"{node}" "{direct}" %*\r\n', encoding="utf-8")
        return str(shim)
    raise SystemExit(
        "pnpm 9.15.9 could not be resolved via corepack\n"
        + (prepared.stdout or "") + (prepared.stderr or "")
    )


def publish_served_output(source: Path, output: Path) -> None:
    """Point the real API at this run when `TP_VALIDATION_OUT` is unset."""
    if not (output / "package" / "package_index.json").is_file():
        return
    pointer = source / "validation" / "out" / "served_output.txt"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(str(output.resolve()) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--e2e", action="store_true", help="Install locked web dependencies and run Playwright")
    ap.add_argument("--output", type=Path)
    ap.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.worker:
        return worker(args.worker.resolve(), args.output.resolve(), e2e=args.e2e)

    if args.e2e:
        require_free_ports((8007, 5180))

    source = Path(__file__).resolve().parents[2]
    scope = commit_scope(source)
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
        TPV_EXPECTED_COMMIT=scope["head"],
    )
    if args.e2e:
        pnpm = resolve_pnpm(output / "corepack")
        env["TPV_PNPM"] = pnpm
        pnpm_dir = str(Path(pnpm).resolve().parent)
        env["PATH"] = pnpm_dir + os.pathsep + env.get("PATH", "")
        version = subprocess.run(
            [pnpm, "--version"], cwd=source, env=env, check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
        env["TPV_PNPM_VERSION"] = (version.stdout or "").strip()
    (output / "commit_scope.json").write_text(
        json.dumps(scope, indent=2) + "\n", encoding="utf-8", newline="\n",
    )
    if args.e2e:
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
           str(repo / "validation/scripts/check_clean_clone.py"),
           "--worker", str(repo), "--output", str(output)]
    if args.e2e:
        cmd.append("--e2e")
    code = subprocess.run(cmd, cwd=repo, env=env, check=False).returncode
    publish_served_output(source, output)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

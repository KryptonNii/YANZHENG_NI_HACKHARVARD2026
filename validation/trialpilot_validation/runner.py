"""Run (or collect) each package's pytest suite in its own venv, plus Playwright specs.

Every suite runs as a subprocess with the tpv pytest plugin on PYTHONPATH; results are read back
from the JSON the plugin writes. A suite that is absent is reported as `not_present`, never as passed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .context import Ctx, read_json, utc_now, write_text

SUITE_TIMEOUT_S = int(os.environ.get("TPV_SUITE_TIMEOUT", "1800"))

_E2E_TEST = re.compile(r"""\b(?:test|it)(?:\.only|\.skip|\.fixme)?\s*\(\s*(['"`])(.+?)\1""")
_REQ = re.compile(r"@req\s+((?:URS-\d{3}[\s,]*)+)")
_REQ_ID = re.compile(r"URS-\d{3}")
_ANNOT = re.compile(r"""type:\s*['"]req['"]\s*,\s*description:\s*['"](URS-\d{3})['"]""")


def _clean_env(ctx: Ctx) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTHONHOME")}
    for k, v in (ctx.config.get("env") or {}).items():
        env[str(k)] = str(v)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ctx.vdir)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
    )
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def suite_command(ctx: Ctx, suite: dict[str, Any], json_path: Path, mode: str,
                  junit_path: Path | None = None) -> list[str]:
    project = ctx.repo / suite["project"]
    runner = suite.get("runner", "uv")
    if runner == "python":
        base = [sys.executable, "-m", "pytest"]
    else:
        uv = shutil.which("uv") or "uv"
        base = [uv, "run"]
        if (project / "uv.lock").exists():
            base.append("--frozen")
        base += ["--project", str(project), "pytest"]
    args = [suite.get("tests", "tests"), "-p", "trialpilot_validation.pytest_plugin",
            f"--tpv-prefix={suite['project']}/", "-p", "no:cacheprovider", "-q",
            "-o", "console_output_style=classic"]
    args += [str(arg) for arg in suite.get("pytest_args", [])]
    if mode == "collect":
        args += ["--collect-only", f"--tpv-collect={json_path}"]
    else:
        args += [f"--tpv-results={json_path}"]
        if junit_path is not None:
            args.append(f"--junitxml={junit_path}")
    return base + args


def run_suite(ctx: Ctx, suite: dict[str, Any], outdir: Path, mode: str) -> dict[str, Any]:
    """mode: 'collect' or 'run'. Returns a suite summary; per-test data is in the JSON file."""
    name = suite["name"]
    project = ctx.repo / suite["project"]
    tests_dir = project / suite.get("tests", "tests")
    summary: dict[str, Any] = {"name": name, "project": suite["project"], "status": None,
                               "exit_code": None, "json": None, "log": None, "junit": None,
                               "started_at": utc_now(), "finished_at": None}
    if not (project / "pyproject.toml").exists() or not tests_dir.exists():
        summary.update(status="not_present", finished_at=utc_now())
        return summary
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / f"{name}.{'collect' if mode == 'collect' else 'results'}.json"
    log_path = outdir / f"{name}.{mode}.log"
    junit_path = outdir / f"{name}.junit.xml" if mode == "run" else None
    cmd = suite_command(ctx, suite, json_path, mode, junit_path)
    try:
        proc = subprocess.run(cmd, cwd=project, env=_clean_env(ctx), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=SUITE_TIMEOUT_S)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        code = -1
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        err = f"TIMEOUT after {SUITE_TIMEOUT_S}s"
    except FileNotFoundError as exc:
        code, out, err = -2, "", f"cannot start runner: {exc}"
    write_text(log_path, f"$ {' '.join(cmd)}\n(cwd={project})\n\n--- stdout ---\n{out}\n"
                         f"--- stderr ---\n{err}\n--- exit code: {code} ---\n")
    summary.update(exit_code=code, log=log_path.name, finished_at=utc_now())
    if json_path.exists():
        summary["json"] = json_path.name
        summary["status"] = "ran" if mode == "run" else "collected"
    else:
        summary["status"] = "runner_error"
    if junit_path is not None and junit_path.exists():
        summary["junit"] = junit_path.name
    return summary


def load_suite_tests(outdir: Path, summaries: list[dict[str, Any]]) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]]]:
    tests: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for s in summaries:
        if s.get("json"):
            data = read_json(outdir / s["json"])
            for t in data.get("tests", []):
                t = dict(t)
                t["suite"] = s["name"]
                t["kind"] = "pytest"
                tests.append(t)
            for e in data.get("collection_errors", []):
                errors.append({**e, "suite": s["name"]})
        elif s.get("status") == "runner_error":
            errors.append({"id": f"{s['project']}/", "suite": s["name"],
                           "message": f"suite could not run (exit {s.get('exit_code')}); "
                                      f"see {s.get('log')}"})
    return tests, errors


# ---- Playwright -----------------------------------------------------------------------------


def scan_e2e(ctx: Ctx) -> list[dict[str, Any]]:
    """Static scan of Playwright specs for tests and their `@req URS-xxx` annotations."""
    found: list[dict[str, Any]] = []
    e2e = ctx.config.get("e2e") or {}
    for spec_dir in e2e.get("specs", []):
        base = ctx.repo / spec_dir
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or not re.search(r"\.(spec|test)\.[cm]?[jt]sx?$", path.name):
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            rel = ctx.rel(path)
            for i, line in enumerate(lines):
                m = _E2E_TEST.search(line)
                if not m or "describe" in line[: m.start() + 12]:
                    continue
                title = m.group(2)
                reqs: list[str] = []
                window = [line]
                j = i - 1
                while j >= 0 and lines[j].strip().startswith(("//", "*", "/*")):
                    window.append(lines[j])
                    j -= 1
                window += lines[i + 1: i + 4]
                for w in window:
                    for mm in _REQ.finditer(w):
                        reqs += _REQ_ID.findall(mm.group(1))
                    reqs += _ANNOT.findall(w)
                found.append({"id": f"{rel}::{title}", "file": rel, "name": title, "line": i + 1,
                              "reqs": sorted(set(reqs)), "kind": "playwright", "outcome": None,
                              "suite": "e2e"})
    return found


def run_e2e(ctx: Ctx, outdir: Path) -> dict[str, Any]:
    e2e = ctx.config.get("e2e") or {}
    project = ctx.repo / e2e.get("project", "web")
    summary: dict[str, Any] = {"name": "e2e", "project": e2e.get("project", "web"),
                               "status": None, "exit_code": None, "json": None, "log": None,
                               "started_at": utc_now(), "finished_at": None}
    pnpm = shutil.which("pnpm")
    if not (project / "package.json").exists() or pnpm is None or not (
            project / "node_modules").exists():
        summary.update(status="not_available", finished_at=utc_now())
        return summary
    outdir.mkdir(parents=True, exist_ok=True)
    json_path = outdir / "e2e.playwright.json"
    log_path = outdir / "e2e.run.log"
    env = _clean_env(ctx)
    env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(json_path)
    cmd = [pnpm, "--dir", str(project), "exec", "playwright", "test", "--reporter=json",
           "--trace=on", f"--output={outdir / 'e2e-artifacts'}"]
    try:
        proc = subprocess.run(cmd, cwd=project, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=SUITE_TIMEOUT_S)
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        code, out, err = -1, "", str(exc)
    write_text(log_path, f"$ {' '.join(cmd)}\n\n--- stdout ---\n{out[-200000:]}\n"
                         f"--- stderr ---\n{err}\n--- exit code: {code} ---\n")
    summary.update(exit_code=code, log=log_path.name, finished_at=utc_now())
    if json_path.exists():
        summary.update(status="ran", json=json_path.name)
    else:
        summary["status"] = "runner_error"
    return summary


def e2e_outcomes(outdir: Path, summary: dict[str, Any]) -> dict[tuple[str, str], str]:
    """(spec basename, title) -> outcome from a Playwright JSON report."""
    result: dict[tuple[str, str], str] = {}
    if not summary.get("json"):
        return result
    data = json.loads((outdir / summary["json"]).read_text(encoding="utf-8"))

    def walk(suite: dict[str, Any]) -> None:
        for spec in suite.get("specs", []):
            statuses = [t.get("status") for t in spec.get("tests", [])]
            if not statuses:
                continue
            if all(s == "skipped" for s in statuses):
                outcome = "skipped"
            elif all(s in ("expected", "flaky") for s in statuses if s != "skipped"):
                outcome = "passed"
            else:
                outcome = "failed"
            result[(Path(spec.get("file", "")).name, spec.get("title", ""))] = outcome
        for child in suite.get("suites", []):
            walk(child)

    for s in data.get("suites", []):
        walk(s)
    return result

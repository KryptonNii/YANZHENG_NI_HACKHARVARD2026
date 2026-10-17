"""Keep the clean-clone check isolated, including its environment and failed setup."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_clean_clone.py"


@pytest.mark.req("URS-026", "URS-027")
def test_clean_clone_does_not_leak_database_overrides_into_suites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = runpy.run_path(str(SCRIPT))
    output = tmp_path / "output"
    calls: list[tuple[list[str], dict]] = []

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(script["tempfile"], "mkdtemp", lambda **kw: str(tmp_path / "clone"))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--output", str(output)])
    monkeypatch.setenv("TP_DB_PATH", "shared.sqlite")
    monkeypatch.setenv("TP_DATA_DIR", "shared-data")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "shared-venv")
    assert script["main"]() == 0
    assert len(calls) == 2
    env = calls[-1][1]["env"]
    assert "TP_DB_PATH" not in env and "TP_DATA_DIR" not in env
    assert "UV_PROJECT_ENVIRONMENT" not in env
    assert Path(env["TP_COMPLIANCE_DB"]).is_relative_to(tmp_path / "clone")
    assert env["TP_VALIDATION_OUT"] == str(output)
    assert env["DEMO_OFFLINE"] == "1"
    assert env["CI"] == "1"  # Playwright must start fresh servers rather than reuse another app.


@pytest.mark.req("URS-026", "URS-027")
def test_rejected_web_install_is_recorded_without_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = runpy.run_path(str(SCRIPT))
    output = tmp_path / "output"
    calls: list[list[str]] = []

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        calls.append(cmd)
        code = 0 if cmd[0] == "git" else 1
        return subprocess.CompletedProcess(cmd, code, stdout="", stderr="Policy rejected install")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(script["tempfile"], "mkdtemp", lambda **kw: str(tmp_path / "clone"))
    monkeypatch.setattr(script["shutil"], "which", lambda name: f"test-{name}")
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--e2e", "--output", str(output)])
    assert script["main"]() == 1
    assert len(calls) == 2 and "--worker" not in calls[-1]
    failure = json.loads((output / "setup_failure.json").read_text(encoding="utf-8"))
    assert failure["stage"] == "locked web dependency installation" and failure["exit_code"] == 1
    assert "Policy rejected install" in (output / "web-install.log").read_text(encoding="utf-8")

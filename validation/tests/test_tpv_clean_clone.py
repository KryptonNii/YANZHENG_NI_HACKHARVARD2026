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
    worker = next(item for item in calls if "--worker" in item[0])
    env = worker[1]["env"]
    assert "TP_DB_PATH" not in env and "TP_DATA_DIR" not in env
    assert "UV_PROJECT_ENVIRONMENT" not in env
    assert Path(env["TP_COMPLIANCE_DB"]).is_relative_to(tmp_path / "clone")
    assert env["TP_VALIDATION_OUT"] == str(output)
    assert env["DEMO_OFFLINE"] == "1"
    assert env["CI"] == "1"  # Playwright must start fresh servers rather than reuse another app.
    assert str(tmp_path / "clone/repo/validation/scripts/check_clean_clone.py") in worker[0]


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
    assert calls and "--worker" not in calls[-1]
    assert any(cmd[0] != "git" for cmd in calls)
    failure = json.loads((output / "setup_failure.json").read_text(encoding="utf-8"))
    assert failure["stage"] == "locked web dependency installation" and failure["exit_code"] == 1
    assert "Policy rejected install" in (output / "web-install.log").read_text(encoding="utf-8")


def test_demo_signatures_are_labelled_and_report_stays_unapproved(tmp_path: Path) -> None:
    script = runpy.run_path(str(SCRIPT))
    pkg = tmp_path / "package"
    pkg.mkdir()
    manifestation = (
        "Sam QA (sam.qa, qa) — APPROVED — 2026-10-17 03:00:00 UTC — "
        "test_protocol/OQ-1 sha256:abcdefabcdef…"
    )
    index = {
        "generated_at": "2026-10-17T03:00:00Z",
        "report": {"status": "awaiting QA approval"},
        "protocol": {"approval": {"signatures": [{"manifestation": manifestation}]}},
        "deliverables": [{"id": "D7", "md": "report.md", "sha256": "old",
                          "approval": {"signatures": [{"manifestation": manifestation}]}}],
        "execution": {"executed_signature": {"manifestation": manifestation}},
    }
    (pkg / "package_index.json").write_text(json.dumps(index), encoding="utf-8")
    (pkg / "report.md").write_text(f"# Report\n\n- {manifestation} — signature valid\n",
                                   encoding="utf-8")
    (pkg / "index.md").write_text("# Package\n", encoding="utf-8")
    evidence = pkg / "evidence" / "RUN"
    evidence.mkdir(parents=True)
    raw = evidence / "tests.json"
    raw.write_text(manifestation, encoding="utf-8")
    digest = script["label_demo_package"](tmp_path)
    labeled = json.loads((pkg / "package_index.json").read_text(encoding="utf-8"))
    assert labeled["signature_class"] == "demo"
    assert labeled["human_qa_approval"] is False
    assert labeled["report"]["status"] == "awaiting QA approval"
    assert labeled["execution"]["executed_signature"]["manifestation"].startswith(
        "DEMO FIXTURE — not a human approval — ")
    assert labeled["execution"]["executed_signature"]["human_approval"] is False
    assert "DEMO FIXTURE" in (pkg / "report.md").read_text(encoding="utf-8")
    assert raw.read_text(encoding="utf-8") == manifestation
    manifest = json.loads((pkg / "package_manifest.json").read_text(encoding="utf-8"))
    assert all(script["_sha256"](pkg / item["path"]) == item["sha256"] for item in manifest["files"])
    assert digest == script["_sha256"](pkg / "package_index.json")

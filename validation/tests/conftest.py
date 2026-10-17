"""Fixtures: a tiny throwaway repository with one tagged test suite, and a temp compliance DB."""

from __future__ import annotations

import subprocess
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

from trialpilot_validation.context import Ctx, load_ctx

PINS = {"alex.author": "1111", "riley.reviewer": "2222", "sam.qa": "3333"}

REQS = """\
document: URS
id: URS-FX
version: 1
system: FixtureSystem
items:
  - {id: URS-001, area: a, text: First requirement, risk: H, risk_rationale: r1, gxp: true}
  - {id: URS-002, area: a, text: Second requirement, risk: M, risk_rationale: r2, gxp: false}
  - {id: URS-003, area: b, text: Third requirement (no test), risk: L, risk_rationale: r3, gxp: false}
"""

CONFIG = """\
system: FixtureSystem
protocol_id: OQ-FX-001
report_id: VSR-FX-001
change_record_prefix: CR-FX
suites:
  - {name: demo, project: demo, tests: tests, runner: python}
  - {name: missing, project: nothere, tests: tests, runner: python}
env: {DEMO_OFFLINE: "1"}
"""

DEMO_TESTS = '''\
import pytest


@pytest.mark.req("URS-001")
def test_one_a():
    assert 1 + 1 == 2


@pytest.mark.req("URS-001", "URS-002")
def test_one_b_and_two():
    assert "x".upper() == "X"


@pytest.mark.req("URS-099")
def test_cites_unknown_requirement():
    assert True


def test_untagged():
    assert True
'''


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def fx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Ctx]:
    repo = tmp_path / "repo"
    v = repo / "validation"
    (v / "defects").mkdir(parents=True)
    (v / "requirements.yaml").write_text(REQS, encoding="utf-8")
    (v / "tpv_config.yaml").write_text(CONFIG, encoding="utf-8")
    (v / "company_sop.md").write_text("# SOP (fictional)\n", encoding="utf-8")
    (v / "ROLES.md").write_text("# Roles\n", encoding="utf-8")
    (v / "component_map.yaml").write_text(textwrap.dedent("""\
        components:
          - {id: demo, paths: ["demo/**"], requirements: [URS-001, URS-002]}
        """), encoding="utf-8")
    demo = repo / "demo"
    (demo / "tests").mkdir(parents=True)
    (demo / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0"\n[tool.pytest.ini_options]\n'
        'testpaths = ["tests"]\n', encoding="utf-8")
    (demo / "tests" / "test_demo.py").write_text(DEMO_TESTS, encoding="utf-8")
    git(repo, "init", "-q")
    git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "fx")

    monkeypatch.setenv("TPV_REPO", str(repo))
    monkeypatch.setenv("TP_VALIDATION_OUT", str(repo / "validation" / "out"))
    monkeypatch.setenv("TP_SECRET_PEPPER", "tpv-test-pepper")
    monkeypatch.setenv("TP_DEMO_PINS", "")
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    monkeypatch.delenv("TPV_PIN", raising=False)
    monkeypatch.delenv("TPV_USER", raising=False)
    from trialpilot_api.compliance import store

    st = store.configure(tmp_path / "compliance.sqlite")
    yield load_ctx(repo)
    st.close()


def approve_current_protocol(ctx: Ctx) -> str:
    from trialpilot_api.compliance import workflow

    from trialpilot_validation import protocol

    cur = protocol.current(ctx)
    req = protocol.submit(ctx, cur["record_id"], "alex.author", title="fx protocol")
    workflow.sign_request(req["approval_id"], "riley.reviewer", PINS["riley.reviewer"], "reviewed")
    workflow.sign_request(req["approval_id"], "sam.qa", PINS["sam.qa"], "approved")
    return str(req["approval_id"])

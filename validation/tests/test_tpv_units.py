"""Unit tests for tpv pieces: requirements, roles doc, impact, controls, defects, effort, AI drafts."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

import pytest

from trialpilot_validation import ai_draft, cli, controls, defects, docs, effort, impact
from trialpilot_validation.context import (
    DRAFT_STAMP,
    Ctx,
    TpvError,
    load_ctx,
    load_requirements,
    read_json,
)

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def real() -> Ctx:
    return load_ctx(REPO)


@pytest.mark.req("URS-027")
def test_repository_requirements_are_valid(real: Ctx) -> None:
    reqs = real.requirements()
    ids = [r["id"] for r in reqs]
    assert len(reqs) >= 20
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    assert all(r["risk"] in "HML" and r["risk_rationale"].strip() for r in reqs)


@pytest.mark.req("URS-027")
def test_invalid_requirements_are_rejected_with_reasons(tmp_path: Path) -> None:
    p = tmp_path / "r.yaml"
    p.write_text("items:\n  - {id: URS-1, text: '', risk: X, gxp: maybe}\n"
                 "  - {id: URS-002, text: ok, risk: H, risk_rationale: r, gxp: true}\n"
                 "  - {id: URS-002, text: ok, risk: H, risk_rationale: r, gxp: true}\n",
                 encoding="utf-8")
    with pytest.raises(TpvError) as ei:
        load_requirements(p)
    msg = str(ei.value)
    for needle in ("id must look like URS-001", "text is empty", "risk must be one of H/M/L",
                   "risk_rationale is required", "gxp must be true or false", "duplicate id"):
        assert needle in msg


@pytest.mark.req("URS-023")
def test_roles_doc_matches_code() -> None:
    from trialpilot_api.compliance import roles, workflow

    text = (REPO / "validation" / "ROLES.md").read_text(encoding="utf-8")
    header = ["author", "reviewer", "qa", "admin", "viewer"]
    doc: dict[str, set[str]] = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 6 and cells[0] in roles.PERMISSIONS:
            doc[cells[0]] = {header[i] for i, c in enumerate(cells[1:]) if c == "✓"}
    assert doc == {k: set(v) for k, v in roles.PERMISSIONS.items()}
    for rt, meanings in workflow.REQUIRED_MEANINGS.items():
        assert re.search(rf"\| {rt} \| {' → '.join(meanings)} \| qa \|", text), rt
    for u in roles.DEMO_USERS:
        assert f"| {u.username} | {u.display_name} | {u.role} | {u.default_pin} |" in text


@pytest.mark.req("URS-031")
def test_impact_maps_changed_files_to_requirements(real: Ctx) -> None:
    a = impact.analyse(real, ["api/trialpilot_api/compliance/workflow.py",
                              "data/params/emission_factors.yaml", "README.md"])
    assert a["components"]["api/trialpilot_api/compliance/workflow.py"] == ["compliance-workflow"]
    assert {"URS-021", "URS-022", "URS-003", "URS-008"} <= set(a["requirements"])
    assert a["unmapped"] == ["README.md"]


@pytest.mark.req("URS-031")
def test_impact_change_record_is_a_draft_for_humans(fx: Ctx) -> None:
    from .conftest import git

    (fx.repo / "demo" / "tests" / "test_demo.py").write_text("# changed\n", encoding="utf-8")
    git(fx.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qam", "chg")
    m = impact.run_impact(fx, "HEAD~1", "HEAD", submit_as="alex.author")
    assert m["files"] == ["demo/tests/test_demo.py"]
    assert m["requirements"] == ["URS-001", "URS-002"]
    body = (fx.repo / m["path"]).read_text(encoding="utf-8")
    assert DRAFT_STAMP in body and "_To be written by the change owner._" in body
    from trialpilot_api.compliance import workflow

    assert workflow.get_request(m["approval_id"]).required_meanings == ["reviewed", "approved"]


@pytest.mark.req("URS-031")
def test_impact_submit_uses_tpv_user_and_keeps_the_pending_request(
        fx: Ctx, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from trialpilot_api.compliance import workflow

    from .conftest import git

    (fx.repo / "demo" / "tests" / "test_demo.py").write_text("# changed\n", encoding="utf-8")
    git(fx.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qam", "chg")
    args = ["impact", "--base", "HEAD~1", "--head", "HEAD"]
    assert cli.main([*args, "--as", "alex.author"]) == 0  # --as without --submit submits nothing
    record_id = read_json(fx.out / "change" / "latest.json")["record_id"]
    assert workflow.approval_status("change_record", record_id)["approval_id"] is None
    monkeypatch.setenv("TPV_USER", "alex.author")
    assert cli.main([*args, "--submit"]) == 0
    first = workflow.approval_status("change_record", record_id)["approval_id"]
    assert first is not None
    assert cli.main([*args, "--submit"]) == 0  # unchanged record: the pending request is reused
    assert workflow.approval_status("change_record", record_id)["approval_id"] == first
    monkeypatch.delenv("TPV_USER")
    capsys.readouterr()
    assert cli.main([*args, "--submit"]) == 2
    assert "Say who you are" in capsys.readouterr().err


def test_component_map_cites_only_known_requirements(real: Ctx) -> None:
    comps = impact.load_map(real)
    assert comps and all(c["requirements"] for c in comps)


@pytest.mark.req("URS-016", "URS-017", "URS-018", "URS-020", "URS-021", "URS-022", "URS-025",
                 "URS-028")
def test_all_control_probes_hold_on_this_code() -> None:
    probes = controls.run_probes()
    assert [p["id"] for p in probes] == ["C1", "C1b", "C2", "C3", "C4", "C5", "C6", "C7", "C8",
                                         "C9"]
    failed = [p for p in probes if not p["holds"]]
    assert failed == []


def test_control_probes_remove_their_scratch_files_and_restore_env(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[str] = []
    mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(**kwargs: Any) -> str:
        made.append(mkdtemp(dir=tmp_path, **kwargs))
        return made[-1]

    monkeypatch.setattr(controls.tempfile, "mkdtemp", recording_mkdtemp)
    monkeypatch.setenv("TP_SECRET_PEPPER", "outer-pepper")
    monkeypatch.delenv("TP_DEMO_PINS", raising=False)
    probes = controls.run_probes()
    assert [p for p in probes if not p["holds"]] == []
    assert len(made) == 1 and not Path(made[0]).exists()
    assert os.environ["TP_SECRET_PEPPER"] == "outer-pepper" and "TP_DEMO_PINS" not in os.environ


def test_control_probes_restore_env_when_setup_fails(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from trialpilot_api.compliance import roles

    def broken_seed(store: Any) -> None:
        raise RuntimeError("seed failed")

    mkdtemp = tempfile.mkdtemp
    monkeypatch.setattr(controls.tempfile, "mkdtemp", lambda **kw: mkdtemp(dir=tmp_path, **kw))
    monkeypatch.setattr(roles, "seed_demo_users", broken_seed)
    monkeypatch.setenv("TP_SECRET_PEPPER", "outer-pepper")
    with pytest.raises(RuntimeError, match="seed failed"):
        controls.run_probes()
    assert os.environ["TP_SECRET_PEPPER"] == "outer-pepper"
    assert list(tmp_path.iterdir()) == []


def test_each_defect_old_text_occurs_once_in_its_target(real: Ctx) -> None:
    """A stale `old` text means make_patches.py finds no match and defects-run cannot plant it."""
    for d in defects.load_defects(real):
        if not d.get("append"):
            target = (REPO / d["target"]).read_text(encoding="utf-8")
            assert target.count(d["old"]) == 1, f"{d['id']}: update `old` in defects.yaml"


def test_defect_comparison_attributes_stages() -> None:
    base = {"tests": [{"id": "a", "outcome": "passed"}, {"id": "b", "outcome": "failed"}],
            "collection_errors": [], "suites": [{"name": "s", "status": "ran"}],
            "trace": {"untested": ["URS-003"], "unknown_refs": [], "below_min_depth": []},
            "controls": [{"id": "C1", "control": "x", "holds": True, "detail": ""}]}
    same = defects.compare(base, base)
    assert same["detected"] is False and same["stages"] == []
    exp = {**base, "tests": [{"id": "a", "outcome": "failed"}, {"id": "b", "outcome": "failed"}]}
    r = defects.compare(base, exp)
    assert r["stages"] == ["unit test"] and r["new_failures"] == ["a"]
    exp = {**base, "trace": {"untested": ["URS-003", "URS-033"], "unknown_refs": [],
                             "below_min_depth": []}}
    assert defects.compare(base, exp)["stages"] == ["trace check"]
    exp = {**base, "controls": [{"id": "C1", "control": "x", "holds": False, "detail": "d"}]}
    assert defects.compare(base, exp)["stages"] == ["workflow check"]


def test_defect_set_is_complete(real: Ctx) -> None:
    items = defects.load_defects(real)
    types = {d["type"] for d in items}
    assert len(items) == 6
    assert types == {"calculation bug", "missing audit entry", "role can self-approve",
                     "export drops rows", "wrong configuration value", "requirement with no test"}
    key = (REPO / "validation" / "defects" / "ANSWER_KEY.md").read_text(encoding="utf-8")
    for d in items:
        assert d["id"] in key and d["patch"] in key


def test_archived_defect_results_are_labelled_and_local_runs_take_precedence(fx: Ctx) -> None:
    from trialpilot_validation.context import write_json

    assert defects.latest(fx) is None
    measured = {"head": "abc123", "started_at": "2026-01-01T00:00:00Z", "finished_at":
                "2026-01-01T00:01:00Z", "note": "Test fixture", "planted": 0, "applied": 0,
                "detected": 0, "rows": []}
    write_json(fx.vdir / "defects" / "LAST_RUN.json", measured)
    archived = defects.latest(fx)
    assert archived is not None and archived["archived"] is True
    text = defects.render_md(archived)
    assert "Archived experiment" in text and "not measurements of the current checkout" in text
    write_json(fx.out / "defects" / "results.json", {**measured, "head": "def456"})
    local = defects.latest(fx)
    assert local is not None and local["head"] == "def456" and "archived" not in local


@pytest.mark.req("URS-025")
def test_plan_marks_system_category_as_draft_for_humans(real: Ctx) -> None:
    text = docs.plan_md(real)
    cat = text.index("## 2. System category")
    assert text.index(DRAFT_STAMP, cat) < text.index("GAMP 5 software category 5", cat)
    assert "tpv does not decide it" in text


@pytest.mark.req("URS-025")
def test_ai_drafting_is_off_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    assert ai_draft.draft("anything") is None
    monkeypatch.setenv("DEMO_OFFLINE", "0")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert ai_draft.draft("anything") is None


@pytest.mark.req("URS-025")
def test_ai_drafted_plan_paragraph_is_stamped(real: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_draft, "draft", lambda *a, **k: "Generated introduction text.")
    text = docs.plan_md(real, ai=True)
    stamp = text.index(DRAFT_STAMP + " (AI-drafted paragraph)")
    assert stamp < text.index("Generated introduction text.")


def test_effort_is_not_measured_until_a_human_times_it(fx: Ctx) -> None:
    s = effort.summary(fx, None)
    assert s["manual_oq_5_requirements_minutes"] == "not measured"
    assert s["tpv_execute_minutes_all_requirements"] == "not measured"
    effort.start(fx, "manual", "tester")
    with pytest.raises(TpvError):
        effort.start(fx, "manual", "tester")
    done = effort.stop(fx, "manual", "5 requirements")
    assert done["minutes"] is not None and done["minutes"] >= 0


def test_validation_out_falls_back_to_the_repo_dotenv(real: Ctx, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    from trialpilot_api.compliance import config

    monkeypatch.setattr(config, "repo_root", lambda: tmp_path)
    (tmp_path / ".env").write_text(f"TP_VALIDATION_OUT={tmp_path / 'dotenv-out'}\n",
                                   encoding="utf-8")
    monkeypatch.delenv("TP_VALIDATION_OUT", raising=False)
    assert real.out == tmp_path / "dotenv-out"  # same directory the API and compliance DB use
    monkeypatch.setenv("TP_VALIDATION_OUT", str(tmp_path / "env-wins"))
    assert real.out == tmp_path / "env-wins"
    monkeypatch.setenv("TP_VALIDATION_OUT", "")
    assert real.out == real.vdir / "out"

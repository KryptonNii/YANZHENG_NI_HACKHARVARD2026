"""tpv end to end on a fixture repo: protocol → gate → execute → trace → report → package."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trialpilot_validation import cli, execute, package, protocol, report, trace
from trialpilot_validation.context import Ctx, read_json, sha256_file

from .conftest import PINS, approve_current_protocol


@pytest.mark.req("URS-027")
def test_protocol_lists_tests_per_requirement_and_gaps(fx: Ctx) -> None:
    meta = protocol.generate(fx)
    assert meta["record_id"].startswith("OQ-FX-001-")
    assert meta["planned"]["URS-001"] == [
        "demo/tests/test_demo.py::test_one_a", "demo/tests/test_demo.py::test_one_b_and_two"]
    assert meta["planned"]["URS-002"] == ["demo/tests/test_demo.py::test_one_b_and_two"]
    assert meta["gaps"] == ["URS-003"]
    assert meta["untagged"] == ["demo/tests/test_demo.py::test_untagged"]
    assert list(meta["unknown_refs"]) == ["URS-099"]
    text = (fx.repo / meta["path"]).read_text(encoding="utf-8")
    assert "**NO TEST**" in text and "approved by QA before it is executed" in text
    # deterministic: regenerating unchanged inputs gives the same record id
    assert protocol.generate(fx)["record_id"] == meta["record_id"]


@pytest.mark.req("URS-024")
def test_execute_refuses_unapproved_protocol(fx: Ctx, capsys: pytest.CaptureFixture[str],
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    protocol.generate(fx)
    monkeypatch.setenv("TPV_PIN", PINS["alex.author"])
    assert cli.main(["execute", "--as", "alex.author"]) == 3
    err = capsys.readouterr().err
    assert "REFUSED" in err and "not approved" in err and "tpv protocol --submit" in err
    assert not (fx.out / "evidence").exists()


@pytest.mark.req("URS-024")
def test_execute_refuses_while_review_pending(fx: Ctx, capsys: pytest.CaptureFixture[str],
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    from trialpilot_api.compliance import workflow

    meta = protocol.generate(fx)
    req = protocol.submit(fx, meta["record_id"], "alex.author", title="t")
    workflow.sign_request(req["approval_id"], "riley.reviewer", PINS["riley.reviewer"], "reviewed")
    monkeypatch.setenv("TPV_PIN", PINS["alex.author"])
    assert cli.main(["execute", "--as", "alex.author"]) == 3
    assert "Next signature needed: 'approved'" in capsys.readouterr().err


@pytest.mark.req("URS-024", "URS-020")
def test_changed_protocol_needs_new_approval(fx: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    protocol.generate(fx)
    approve_current_protocol(fx)
    tests = fx.repo / "demo" / "tests" / "test_demo.py"
    tests.write_text(tests.read_text(encoding="utf-8") + "\n\n@pytest.mark.req('URS-003')\n"
                     "def test_three():\n    assert True\n", encoding="utf-8")
    meta = protocol.generate(fx)
    assert meta["gaps"] == []
    monkeypatch.setenv("TPV_PIN", PINS["alex.author"])
    assert cli.main(["execute", "--as", "alex.author"]) == 3


@pytest.mark.req("URS-026", "URS-024")
def test_execute_writes_hashed_manifest_and_executed_signature(
        fx: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    protocol.generate(fx)
    approve_current_protocol(fx)
    monkeypatch.setenv("TPV_PIN", PINS["alex.author"])
    assert cli.main(["execute", "--as", "alex.author"]) == 0
    run = execute.latest_run(fx)
    assert run is not None
    m = run["manifest"]
    assert m["executor"] == "alex.author" and m["git"]["commit"]
    assert m["counts"] == {"passed": 4, "failed": 0, "error": 0, "skipped": 0, "xfailed": 0,
                           "xpassed": 0, "not_run": 0, "total": 4}
    assert {s["name"]: s["status"] for s in m["suites"]} == {"demo": "ran",
                                                             "missing": "not_present"}
    for f in m["files"]:  # every evidence file is listed with its real hash
        assert sha256_file(run["dir"] / f["path"]) == f["sha256"]
        assert f["modified_utc"].endswith("Z")
    names = {f["path"] for f in m["files"]}
    assert {"demo.results.json", "demo.junit.xml", "demo.run.log", "tests.json",
            "environment.json"} <= names
    sig = run["signature"]
    assert sig["signer"] == "alex.author" and sig["meaning"] == "executed"
    assert sig["record_hash"] == sha256_file(run["dir"] / execute.MANIFEST)
    assert execute.verify_manifest(run["dir"]) == []
    (run["dir"] / "demo.results.json").write_text("{}", encoding="utf-8")
    assert execute.verify_manifest(run["dir"]) == ["hash mismatch: demo.results.json"]


@pytest.mark.req("URS-026")
def test_execute_requires_the_executors_pin(fx: Ctx, monkeypatch: pytest.MonkeyPatch,
                                            capsys: pytest.CaptureFixture[str]) -> None:
    protocol.generate(fx)
    approve_current_protocol(fx)
    monkeypatch.setenv("TPV_PIN", "0000")
    assert cli.main(["execute", "--as", "alex.author"]) == 3
    assert "invalid_credential" in capsys.readouterr().err
    assert not (fx.out / "evidence").exists()


@pytest.mark.req("URS-027")
def test_trace_flags_untested_unknown_untagged_and_failures(
        fx: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    tests = fx.repo / "demo" / "tests" / "test_demo.py"
    tests.write_text(tests.read_text(encoding="utf-8").replace(
        'assert "x".upper() == "X"', 'assert "x".upper() == "Y"'), encoding="utf-8")
    protocol.generate(fx)
    approve_current_protocol(fx)
    monkeypatch.setenv("TPV_PIN", PINS["alex.author"])
    assert cli.main(["execute", "--as", "alex.author"]) == 0
    t = trace.write(fx)
    rows = {r["id"]: r for r in t["rows"]}
    assert rows["URS-001"]["result"] == "fail" and rows["URS-002"]["result"] == "fail"
    assert rows["URS-003"]["result"] == "no test"
    assert t["flags"]["untested_requirements"] == ["URS-003"]
    assert list(t["flags"]["unknown_requirement_refs"]) == ["URS-099"]
    assert t["flags"]["tests_without_requirement_count"] == 1
    assert rows["URS-001"]["evidence"][0]["file"] == "demo.results.json"
    assert len(rows["URS-001"]["evidence"][0]["sha256"]) == 64
    csv_text = (fx.out / "trace" / "trace_matrix.csv").read_text(encoding="utf-8")
    assert "URS-003,L,False,,,,no test" in csv_text


@pytest.mark.req("URS-027")
def test_trace_without_execution_shows_not_run(fx: Ctx) -> None:
    protocol.generate(fx)
    t = trace.build(fx)
    assert t["source"]["kind"] == "collection"
    assert {r["id"]: r["result"] for r in t["rows"]} == {
        "URS-001": "not run", "URS-002": "not run", "URS-003": "no test"}


@pytest.mark.req("URS-032")
def test_report_states_real_counts_and_waits_for_qa(fx: Ctx,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    from trialpilot_api.compliance import workflow

    protocol.generate(fx)
    approve_current_protocol(fx)
    monkeypatch.setenv("TPV_PIN", PINS["alex.author"])
    cli.main(["execute", "--as", "alex.author"])
    meta = report.generate(fx)
    text = (fx.repo / meta["path"]).read_text(encoding="utf-8")
    assert "| 4 | 4 | 0 | 0 | 0 | 0 |" in text  # tests: total, passed, failed, error, ...
    assert "URS-003 has no test" in text and "NOT met" in text
    assert report.status(fx)["status"] == "not submitted"
    sub = report.submit(fx, "alex.author")
    assert report.status(fx)["status"] == "awaiting QA approval"
    with pytest.raises(Exception):  # the author cannot approve their own report
        workflow.sign_request(sub["approval_id"], "alex.author", PINS["alex.author"], "approved")
    workflow.sign_request(sub["approval_id"], "sam.qa", PINS["sam.qa"], "approved")
    st = report.status(fx)
    assert st["status"] == "approved" and st["qa_signature"]["signer"] == "sam.qa"
    (fx.repo / meta["path"]).write_text(text + "\nedited\n", encoding="utf-8")
    assert report.status(fx)["status"].startswith("approval invalid")


@pytest.mark.req("URS-027", "URS-032")
def test_package_index_for_the_ui(fx: Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    protocol.generate(fx)
    approve_current_protocol(fx)
    monkeypatch.setenv("TPV_PIN", PINS["alex.author"])
    cli.main(["execute", "--as", "alex.author"])
    report.generate(fx)
    assert cli.main(["package"]) == 0
    pkg = fx.out / "package"
    ix = read_json(pkg / "package_index.json")
    status = {d["id"]: d["status"] for d in ix["deliverables"]}
    assert status["D4"] == "approved" and status["D5"] == "executed"
    assert status["D7"] == "awaiting approval" and status["D1"] == "draft"
    assert next(d for d in ix["deliverables"] if d["id"] == "D1")["draft_stamp"] is True
    assert ix["report"]["status"] == "not submitted"
    assert ix["trace"]["flags"]["untested_requirements"] == ["URS-003"]
    assert ix["execution"]["counts"]["total"] == 4 and ix["execution"]["integrity_problems"] == []
    assert ix["audit_chain"]["ok"] is True
    assert ix["effort"]["manual_oq_5_requirements_minutes"] == "not measured"
    for d in ix["deliverables"]:
        if d["html"]:
            html = (pkg / d["html"]).read_text(encoding="utf-8")
            assert html.startswith("<!doctype html>")
    plan_html = (pkg / "plan.html").read_text(encoding="utf-8")
    assert 'class="draft">DRAFT — requires human review' in plan_html
    man = json.loads((pkg / "package_manifest.json").read_text(encoding="utf-8"))
    assert all(sha256_file(pkg / f["path"]) == f["sha256"] for f in man["files"])
    assert (pkg / "evidence" / ix["execution"]["run_id"] / execute.MANIFEST).exists()


def test_package_without_anything_lists_missing(fx: Ctx) -> None:
    ix = package.build(fx)
    status = {d["id"]: d["status"] for d in ix["deliverables"]}
    assert status["D4"] == "missing" and status["D5"] == "missing" and status["D7"] == "missing"
    assert ix["execution"] is None


@pytest.mark.req("URS-022")
def test_cli_sign_reports_refusals(fx: Ctx, monkeypatch: pytest.MonkeyPatch,
                                   capsys: pytest.CaptureFixture[str]) -> None:
    meta = protocol.generate(fx)
    req = protocol.submit(fx, meta["record_id"], "alex.author", title="t")
    monkeypatch.setenv("TPV_PIN", PINS["sam.qa"])
    assert cli.main(["sign", req["approval_id"], "--as", "sam.qa", "--meaning", "approved"]) == 3
    assert "out_of_order" in capsys.readouterr().out
    monkeypatch.setenv("TPV_PIN", PINS["riley.reviewer"])
    assert cli.main(["sign", req["approval_id"], "--as", "riley.reviewer",
                     "--meaning", "reviewed"]) == 0
    assert "REVIEWED" in capsys.readouterr().out


def test_unknown_repo_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TPV_REPO", raising=False)
    assert cli.main(["--repo", str(tmp_path), "risk"]) == 2

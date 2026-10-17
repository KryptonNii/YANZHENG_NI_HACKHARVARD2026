"""`tpv controls`: probe the compliance controls of the code under test ("workflow check" stage).

Runs against a throwaway SQLite file (never the real audit trail) and exercises each control the
way a misuser would. Each probe passes only if the control holds. Used by `tpv execute` evidence and
by `tpv defects-run` as an independent detection stage next to unit tests and the trace check.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

PINS = {"alex.author": "1111", "riley.reviewer": "2222", "sam.qa": "3333", "admin": "9999"}
H1 = "1" * 64


def _expect_error(fn: Callable[[], Any], code: str, c: Any) -> tuple[bool, str]:
    try:
        fn()
    except c.ComplianceError as exc:
        return exc.code == code, f"got {exc.status} {exc.code}"
    return False, "no error raised — control did not hold"


def run_probes() -> list[dict[str, Any]]:
    from trialpilot_api import compliance as c

    saved = {k: os.environ.get(k) for k in ("TP_SECRET_PEPPER", "TP_DEMO_PINS")}
    tmp = tempfile.mkdtemp(prefix="tpv-controls-")
    st = None
    try:
        os.environ["TP_SECRET_PEPPER"] = "tpv-controls-probe"
        os.environ["TP_DEMO_PINS"] = ""
        st = c.store.Store(Path(tmp) / "probe.sqlite")
        c.roles.seed_demo_users(st)
        return _probe(c, st, tmp)
    finally:
        if st is not None:
            st.close()
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)


def _probe(c: Any, st: Any, tmp: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cp = None

    def add(pid: str, req: str, title: str, outcome: tuple[bool, str]) -> None:
        results.append({"id": pid, "req": req, "control": title, "holds": bool(outcome[0]),
                        "detail": outcome[1]})

    try:
        wf = c.workflow

        def new_req() -> str:
            return str(wf.create_request("scenario", f"probe-{len(results)}", "alex.author",
                                         record_hash=H1, store=st).id)

        rid = new_req()
        add("C1", "URS-021", "author cannot approve own record", _expect_error(
            lambda: wf.sign_request(rid, "alex.author", PINS["alex.author"], "approved", store=st),
            "self_approval_forbidden", c))
        qa_req = str(wf.create_request("change_record", "probe-qa", "sam.qa", record_hash=H1,
                                       store=st).id)
        add("C1b", "URS-021", "no role (not even QA) approves its own record", _expect_error(
            lambda: wf.sign_request(qa_req, "sam.qa", PINS["sam.qa"], "reviewed", store=st),
            "self_approval_forbidden", c))
        add("C2", "URS-022", "approval steps follow the required order", _expect_error(
            lambda: wf.sign_request(rid, "sam.qa", PINS["sam.qa"], "approved", store=st),
            "out_of_order", c))
        try:
            wf.sign_request(rid, "riley.reviewer", PINS["riley.reviewer"], "reviewed", store=st)
            ok3 = _expect_error(lambda: wf.sign_request(rid, "riley.reviewer",
                                                        PINS["riley.reviewer"], "approved",
                                                        store=st), "duplicate_signer", c)
        except c.ComplianceError as exc:
            ok3 = (False, f"review step failed: {exc.code}")
        add("C3", "URS-022", "one signer per approval step", ok3)

        try:
            st.conn.execute("UPDATE audit SET reason = 'x' WHERE seq = 1")
            add("C4", "URS-016", "database rejects UPDATE on audit", (False, "UPDATE succeeded"))
        except sqlite3.DatabaseError as exc:
            add("C4", "URS-016", "database rejects UPDATE on audit", (True, str(exc)))

        copy_path = Path(tmp) / "tampered.sqlite"
        dst = sqlite3.connect(copy_path)
        st.conn.backup(dst)
        dst.close()
        cp = c.store.Store(copy_path)
        cp.conn.execute("DROP TRIGGER IF EXISTS audit_no_update")
        cp.conn.execute("UPDATE audit SET reason = 'tampered' WHERE seq = 2")
        v = c.audit.verify_chain(store=cp)
        add("C5", "URS-017", "chain verification finds a tampered row",
            (v["ok"] is False and v["first_bad_seq"] == 2, f"verify -> {v}"))
        cp.close()

        n = c.audit.count(store=st)
        rows = c.audit.export_csv(store=st).strip().splitlines()
        add("C6", "URS-028", "audit export contains every entry",
            (len(rows) - 1 == n, f"{len(rows) - 1} exported rows vs {n} entries"))

        codes = []
        for _ in range(3):
            try:
                c.esign.reauthenticate("riley.reviewer", "wrong-pin", store=st)
                codes.append("ok")
            except c.ComplianceError as exc:
                codes.append(exc.code)
        add("C7", "URS-018", "wrong PIN rejected; 3rd failure locks",
            (codes == ["invalid_credential", "invalid_credential", "account_locked"],
             f"codes {codes}"))

        add("C8", "URS-025", "AI actor cannot sign", _expect_error(
            lambda: c.esign.sign("probe", "p1", H1, "ai:drafter", "author", "executed", "1111",
                                 store=st), "ai_signature_forbidden", c))

        doc = Path(tmp) / "record.md"
        doc.write_text("v1", encoding="utf-8")
        c.records.register_file("test_protocol", "probe-doc", doc, store=st)
        sig = c.esign.sign("test_protocol", "probe-doc", c.hashing.file_sha256(doc), "sam.qa",
                           "qa", "verified", PINS["sam.qa"], store=st)
        doc.write_text("v2", encoding="utf-8")
        status = c.esign.signature_status(sig, store=st)
        add("C9", "URS-020", "signature invalid after the record changes",
            (status["valid"] is False, f"status {status}"))
    except Exception as exc:  # a crash in the probe is itself a finding
        add("CX", "", "probe crashed", (False, f"{type(exc).__name__}: {exc}"))
    finally:
        if cp is not None:
            cp.close()
    return results

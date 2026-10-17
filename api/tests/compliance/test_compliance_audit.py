"""Audit trail: hash chain, append-only enforcement, tamper detection, export."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from pathlib import Path

import pytest

from trialpilot_api.compliance import audit, store
from trialpilot_api.compliance.errors import ComplianceError
from trialpilot_api.compliance.hashing import GENESIS_HASH, canonical_json, sha256_hex

PKG = Path(audit.__file__).resolve().parent


def _fill(n: int, st: store.Store) -> None:
    for i in range(n):
        audit.append("alex.author", "author", "scenario.create", "scenario", f"s{i}",
                     None, sha256_hex(f"v{i}"), f"reason {i}", store=st)


@pytest.mark.req("URS-015")
def test_append_records_who_what_when_why(db: store.Store) -> None:
    e = audit.append("alex.author", "author", "scenario.create", "scenario", "s1", None,
                     "a" * 64, "initial draft")
    assert e.seq == 1
    assert e.actor == "alex.author" and e.role == "author"
    assert e.action == "scenario.create" and e.object_type == "scenario" and e.object_id == "s1"
    assert e.before_hash is None and e.after_hash == "a" * 64
    assert e.reason == "initial draft"
    assert e.at.tzinfo is not None and e.at.utcoffset().total_seconds() == 0


@pytest.mark.req("URS-017")
def test_entry_hash_formula_and_genesis(db: store.Store) -> None:
    e = audit.append("sam.qa", "qa", "approval.sign", "approval", "a1", "b" * 64, "b" * 64)
    assert e.prev_entry_hash == GENESIS_HASH == sha256_hex("trialpilot-genesis")
    body = e.model_dump(mode="json")
    body.pop("entry_hash")
    body["at"] = e.at.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    assert e.entry_hash == sha256_hex(canonical_json(body) + e.prev_entry_hash)
    e2 = audit.append("sam.qa", "qa", "approval.approve", "approval", "a1", None, None)
    assert e2.prev_entry_hash == e.entry_hash and e2.seq == 2


@pytest.mark.req("URS-017")
def test_verify_intact_chain(db: store.Store) -> None:
    _fill(5, db)
    res = audit.verify_chain()
    assert res["ok"] is True and res["checked"] == 5 and res["first_bad_seq"] is None


@pytest.mark.req("URS-016")
def test_database_rejects_update_and_delete(db: store.Store) -> None:
    _fill(2, db)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.conn.execute("UPDATE audit SET reason = 'edited' WHERE seq = 1")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.conn.execute("DELETE FROM audit WHERE seq = 2")
    assert audit.count() == 2 and audit.verify_chain()["ok"]


def _tampered_copy(db: store.Store, tmp_path: Path) -> store.Store:
    copy_path = tmp_path / "copy.sqlite"
    dst = sqlite3.connect(copy_path)
    db.conn.backup(dst)
    dst.close()
    copy = store.Store(copy_path)
    copy.conn.execute("DROP TRIGGER audit_no_update")
    copy.conn.execute("DROP TRIGGER audit_no_delete")
    return copy


@pytest.mark.req("URS-017")
def test_tampered_row_reports_first_bad_seq(db: store.Store, tmp_path: Path) -> None:
    _fill(6, db)
    copy = _tampered_copy(db, tmp_path)
    copy.conn.execute("UPDATE audit SET reason = 'nothing to see here' WHERE seq = 3")
    res = audit.verify_chain(store=copy)
    assert res["ok"] is False and res["first_bad_seq"] == 3
    assert "altered" in res["problem"]
    assert audit.verify_chain()["ok"] is True  # the original is untouched
    copy.close()


@pytest.mark.req("URS-017")
def test_deleted_row_is_detected_as_gap(db: store.Store, tmp_path: Path) -> None:
    _fill(5, db)
    copy = _tampered_copy(db, tmp_path)
    copy.conn.execute("DELETE FROM audit WHERE seq = 2")
    res = audit.verify_chain(store=copy)
    assert res["ok"] is False and res["first_bad_seq"] == 2
    copy.close()


@pytest.mark.req("URS-017")
def test_truncation_detected_with_recorded_anchor(db: store.Store, tmp_path: Path) -> None:
    _fill(4, db)
    anchor = audit.verify_chain()
    copy = _tampered_copy(db, tmp_path)
    copy.conn.execute("DELETE FROM audit WHERE seq = 4")
    assert audit.verify_chain(store=copy)["ok"] is True  # a bare chain cannot see truncation ...
    res = audit.verify_chain(store=copy, expected_head=anchor["head_hash"], expected_count=4)
    assert res["ok"] is False and res["first_bad_seq"] == 4  # ... a recorded anchor can
    copy.close()


@pytest.mark.req("URS-015")
def test_invalid_entries_rejected(db: store.Store) -> None:
    with pytest.raises(ComplianceError) as ei:
        audit.append("x", "superuser", "a", "b", "c", None, None)
    assert ei.value.status == 422
    with pytest.raises(ComplianceError):
        audit.append("", "author", "a", "b", "c", None, None)
    assert audit.count() == 0


@pytest.mark.req("URS-016")
def test_no_update_or_delete_code_path_on_audit_or_signatures() -> None:
    pattern = re.compile(r"(UPDATE|DELETE\s+FROM)\s+(audit|signatures)\b", re.IGNORECASE)
    offenders = [
        f"{p.name}:{i}"
        for p in PKG.glob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line) and "RAISE(ABORT" not in line and "TRIGGER" not in line
    ]
    assert offenders == []


@pytest.mark.req("URS-028")
def test_export_contains_every_entry(db: store.Store) -> None:
    _fill(7, db)
    rows = list(csv.reader(io.StringIO(audit.export_csv())))
    assert rows[0] == list(audit.CSV_COLUMNS)
    assert len(rows) - 1 == audit.count() == 7
    assert [int(r[0]) for r in rows[1:]] == list(range(1, 8))


@pytest.mark.req("URS-015")
def test_list_filters_and_paging(db: store.Store) -> None:
    _fill(3, db)
    audit.append("sam.qa", "qa", "approval.sign", "approval", "a1", None, None)
    items, total = audit.list_entries(limit=2)
    assert total == 4 and [e.seq for e in items] == [4, 3]
    items, total = audit.list_entries(actor="sam.qa")
    assert total == 1 and items[0].action == "approval.sign"
    items, total = audit.list_entries(action="scenario.")
    assert total == 3

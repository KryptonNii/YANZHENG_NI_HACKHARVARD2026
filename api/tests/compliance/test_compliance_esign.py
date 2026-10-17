"""E-signatures: re-authentication, lockout, record binding, manifestation, AI never signs."""

from __future__ import annotations

from pathlib import Path

import pytest

from trialpilot_api.compliance import audit, esign, records, roles, store
from trialpilot_api.compliance.errors import ComplianceError
from trialpilot_api.compliance.hashing import file_sha256, sha256_hex

from .conftest import PINS, FakeClock

H = sha256_hex("record v1")


def _actions() -> list[str]:
    items, _ = audit.list_entries(limit=1000, newest_first=False)
    return [e.action for e in items]


@pytest.mark.req("URS-018")
def test_correct_pin_signs(db: store.Store) -> None:
    sig = esign.sign("test_execution", "run-1", H, "alex.author", "author", "executed",
                     PINS["alex.author"])
    assert sig.signer == "alex.author" and sig.meaning == "executed" and sig.record_hash == H
    assert "signature.create" in _actions()


@pytest.mark.req("URS-018")
def test_wrong_pin_is_401_and_audited(db: store.Store) -> None:
    with pytest.raises(ComplianceError) as ei:
        esign.sign("test_execution", "run-1", H, "alex.author", "author", "executed", "0000")
    assert ei.value.status == 401 and ei.value.code == "invalid_credential"
    assert ei.value.details["attempts_left"] == 2
    assert _actions() == ["esign.auth_failed"]
    assert esign.list_signatures() == []


@pytest.mark.req("URS-018")
def test_three_failures_lock_for_five_minutes(db: store.Store, clock: FakeClock) -> None:
    for _ in range(2):
        with pytest.raises(ComplianceError) as ei:
            esign.reauthenticate("sam.qa", "bad")
        assert ei.value.status == 401
    with pytest.raises(ComplianceError) as ei:
        esign.reauthenticate("sam.qa", "bad")
    assert ei.value.status == 423 and ei.value.code == "account_locked"
    assert "esign.lockout" in _actions()
    # even the right PIN is refused while locked, and the attempt is logged
    clock.advance(299)
    with pytest.raises(ComplianceError) as ei:
        esign.reauthenticate("sam.qa", PINS["sam.qa"])
    assert ei.value.status == 423
    assert _actions()[-1] == "esign.attempt_while_locked"
    clock.advance(2)
    assert esign.reauthenticate("sam.qa", PINS["sam.qa"]).username == "sam.qa"


@pytest.mark.req("URS-018")
def test_success_resets_failure_counter(db: store.Store) -> None:
    for _ in range(2):
        with pytest.raises(ComplianceError):
            esign.reauthenticate("riley.reviewer", "bad")
    esign.reauthenticate("riley.reviewer", PINS["riley.reviewer"])
    with pytest.raises(ComplianceError) as ei:
        esign.reauthenticate("riley.reviewer", "bad")
    assert ei.value.status == 401 and ei.value.details["attempts_left"] == 2


@pytest.mark.req("URS-018")
def test_pins_are_stored_peppered_argon2_hashes(db: store.Store) -> None:
    rows = db.query("SELECT username, pin_hash FROM compliance_users")
    assert len(rows) == len(roles.DEMO_USERS)
    for r in rows:
        assert r["pin_hash"].startswith("$argon2id$")
        assert PINS[r["username"]] not in r["pin_hash"]


@pytest.mark.req("URS-018")
def test_pepper_is_part_of_the_hash(db: store.Store, monkeypatch: pytest.MonkeyPatch) -> None:
    row = db.query_one("SELECT pin_hash FROM compliance_users WHERE username='sam.qa'")
    assert roles.check_pin(row["pin_hash"], PINS["sam.qa"])
    monkeypatch.setenv("TP_SECRET_PEPPER", "another-pepper")
    assert not roles.check_pin(row["pin_hash"], PINS["sam.qa"])


@pytest.mark.req("URS-019")
def test_signature_binds_record_hash_and_manifests_name_time_meaning(db: store.Store,
                                                                     clock: FakeClock) -> None:
    sig = esign.sign("test_execution", "run-7", H, "sam.qa", "qa", "verified", PINS["sam.qa"])
    text = esign.manifestation(sig)
    assert "Sam QA" in text and "sam.qa" in text
    assert "VERIFIED" in text
    assert "2026-10-17 12:00:00 UTC" in text
    assert H[:12] in text
    stored = esign.list_signatures(record_type="test_execution", record_id="run-7")
    assert stored == [sig]


@pytest.mark.req("URS-020")
def test_signature_invalid_after_record_changes(db: store.Store, tmp_path: Path) -> None:
    doc = tmp_path / "protocol.md"
    doc.write_text("# OQ protocol v1\n", encoding="utf-8")
    records.register_file("test_protocol", "OQ-1", doc)
    sig = esign.sign("test_protocol", "OQ-1", file_sha256(doc), "riley.reviewer", "reviewer",
                     "reviewed", PINS["riley.reviewer"])
    assert esign.signature_status(sig)["valid"] is True
    doc.write_text("# OQ protocol v1 (quietly edited)\n", encoding="utf-8")
    status = esign.signature_status(sig)
    assert status["valid"] is False and status["reason"] == "record changed after signing"
    assert esign.signature_view(sig)["valid"] is False


@pytest.mark.req("URS-020")
def test_validity_from_registered_resolver(db: store.Store) -> None:
    current = {"s1": H}
    records.register_resolver("scenario", lambda rid: current.get(rid))
    sig = esign.sign("scenario", "s1", H, "riley.reviewer", "reviewer", "reviewed",
                     PINS["riley.reviewer"])
    assert esign.signature_status(sig)["valid"] is True
    current["s1"] = sha256_hex("record v2")
    assert esign.signature_status(sig)["valid"] is False
    current.pop("s1")
    assert esign.signature_status(sig)["valid"] is None


@pytest.mark.req("URS-025")
def test_ai_actor_can_never_sign(db: store.Store) -> None:
    with pytest.raises(ComplianceError) as ei:
        esign.sign("test_execution", "run-1", H, "ai:drafter", "author", "executed", "1111")
    assert ei.value.status == 403 and ei.value.code == "ai_signature_forbidden"
    assert esign.list_signatures() == []
    assert _actions() == ["esign.denied"]


@pytest.mark.req("URS-023")
def test_role_comes_from_registry_not_from_caller(db: store.Store) -> None:
    with pytest.raises(ComplianceError) as ei:
        esign.sign("test_execution", "r", H, "alex.author", "qa", "verified", PINS["alex.author"])
    assert ei.value.status == 403 and ei.value.code == "role_mismatch"
    with pytest.raises(ComplianceError) as ei:
        esign.sign("test_execution", "r", H, "val.viewer", "viewer", "executed", PINS["val.viewer"])
    assert ei.value.status == 403 and ei.value.code == "role_not_permitted"
    assert esign.list_signatures() == []


@pytest.mark.req("URS-016")
def test_signatures_table_is_append_only(db: store.Store) -> None:
    import sqlite3

    esign.sign("test_execution", "r", H, "alex.author", "author", "executed", PINS["alex.author"])
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.conn.execute("UPDATE signatures SET record_hash = 'x'")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.conn.execute("DELETE FROM signatures")

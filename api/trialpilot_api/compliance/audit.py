"""Append-only audit trail with a SHA-256 hash chain.

    entry_hash = sha256(canonical_json(entry without entry_hash) + prev_entry_hash)
    prev_entry_hash of seq 1 = sha256("trialpilot-genesis")

Rows are only ever INSERTed. SQLite triggers abort UPDATE/DELETE on the table, and `verify_chain`
detects any row changed behind the triggers' back (e.g. raw SQL after dropping a trigger).
"""

from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from ._contracts import ROLES, AuditEntry
from .errors import ComplianceError
from .hashing import GENESIS_HASH, canonical_json, iso_utc, now, parse_utc, sha256_hex
from .store import Store, get_store

_HASHED_FIELDS = (
    "seq",
    "at",
    "actor",
    "role",
    "action",
    "object_type",
    "object_id",
    "before_hash",
    "after_hash",
    "reason",
    "prev_entry_hash",
)

CSV_COLUMNS = (*_HASHED_FIELDS, "entry_hash")


def compute_entry_hash(fields: dict[str, Any]) -> str:
    body = {k: fields[k] for k in _HASHED_FIELDS}
    return sha256_hex(canonical_json(body) + fields["prev_entry_hash"])


def _row_to_entry(row: sqlite3.Row) -> AuditEntry:
    data = dict(row)
    data["at"] = parse_utc(data["at"])
    return AuditEntry.model_validate(data)


def append(
    actor: str,
    role: str,
    action: str,
    object_type: str,
    object_id: str,
    before_hash: str | None,
    after_hash: str | None,
    reason: str | None = None,
    *,
    store: Store | None = None,
) -> AuditEntry:
    """Append one entry to the audit trail and return it (with its chain hash)."""
    if not actor or not actor.strip():
        raise ComplianceError(422, "invalid_audit_entry", "Audit entries need an actor.")
    if role not in ROLES:
        raise ComplianceError(
            422, "invalid_audit_entry", f"Unknown role {role!r}.", {"allowed": list(ROLES)}
        )
    if not action or not object_type or object_id is None or str(object_id) == "":
        raise ComplianceError(
            422, "invalid_audit_entry", "Audit entries need an action, object_type and object_id."
        )
    st = store or get_store()
    with st.tx() as conn:
        last = conn.execute("SELECT seq, entry_hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        seq = (last["seq"] + 1) if last else 1
        prev = last["entry_hash"] if last else GENESIS_HASH
        fields: dict[str, Any] = {
            "seq": seq,
            "at": iso_utc(now()),
            "actor": actor,
            "role": role,
            "action": action,
            "object_type": object_type,
            "object_id": str(object_id),
            "before_hash": before_hash,
            "after_hash": after_hash,
            "reason": reason,
            "prev_entry_hash": prev,
        }
        fields["entry_hash"] = compute_entry_hash(fields)
        cols = ", ".join(CSV_COLUMNS)
        marks = ", ".join("?" for _ in CSV_COLUMNS)
        conn.execute(f"INSERT INTO audit ({cols}) VALUES ({marks})", [fields[c] for c in CSV_COLUMNS])
    data = dict(fields)
    data["at"] = parse_utc(fields["at"])
    return AuditEntry.model_validate(data)


def _filters(
    actor: str | None,
    action: str | None,
    object_type: str | None,
    object_id: str | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for col, val in (
        ("actor", actor),
        ("object_type", object_type),
        ("object_id", object_id),
    ):
        if val:
            clauses.append(f"{col} = ?")
            params.append(val)
    if action:
        # "approval." matches every approval action; an exact action name matches itself.
        if action.endswith("."):
            clauses.append("action LIKE ?")
            params.append(action + "%")
        else:
            clauses.append("action = ?")
            params.append(action)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_entries(
    *,
    limit: int = 50,
    offset: int = 0,
    actor: str | None = None,
    action: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    newest_first: bool = True,
    store: Store | None = None,
) -> tuple[list[AuditEntry], int]:
    st = store or get_store()
    where, params = _filters(actor, action, object_type, object_id)
    total_row = st.query_one(f"SELECT COUNT(*) AS n FROM audit{where}", params)
    total = int(total_row["n"]) if total_row else 0
    order = "DESC" if newest_first else "ASC"
    rows = st.query(
        f"SELECT * FROM audit{where} ORDER BY seq {order} LIMIT ? OFFSET ?",
        [*params, int(limit), int(offset)],
    )
    return [_row_to_entry(r) for r in rows], total


def count(store: Store | None = None) -> int:
    st = store or get_store()
    row = st.query_one("SELECT COUNT(*) AS n FROM audit")
    return int(row["n"]) if row else 0


def verify_chain(
    *,
    expected_head: str | None = None,
    expected_count: int | None = None,
    store: Store | None = None,
) -> dict[str, Any]:
    """Recompute every hash in seq order.

    Returns `{ok, first_bad_seq, checked, head_hash, problem}`. `checked` is the number of entries
    examined. A chain alone cannot detect removal of the newest rows; pass a previously recorded
    `expected_head`/`expected_count` (e.g. from a validation package) to detect truncation too.
    """
    st = store or get_store()
    rows = st.query("SELECT * FROM audit ORDER BY seq ASC")
    prev = GENESIS_HASH
    expected_seq = 1
    checked = 0
    for row in rows:
        checked += 1
        fields = dict(row)
        problem = None
        if fields["seq"] != expected_seq:
            problem = f"sequence gap: expected seq {expected_seq}, found {fields['seq']}"
        elif fields["prev_entry_hash"] != prev:
            problem = "prev_entry_hash does not match the previous entry's hash"
        elif compute_entry_hash(fields) != fields["entry_hash"]:
            problem = "entry content does not match its entry_hash (row was altered)"
        if problem:
            return {
                "ok": False,
                "first_bad_seq": min(fields["seq"], expected_seq),
                "checked": checked,
                "head_hash": prev,
                "problem": problem,
            }
        prev = fields["entry_hash"]
        expected_seq += 1
    result: dict[str, Any] = {
        "ok": True,
        "first_bad_seq": None,
        "checked": checked,
        "head_hash": prev,
        "problem": None,
    }
    if expected_count is not None and checked < expected_count:
        result.update(
            ok=False,
            first_bad_seq=checked + 1,
            problem=f"chain has {checked} entries but {expected_count} were recorded earlier",
        )
    elif expected_head is not None and expected_count is not None:
        anchor = st.query_one("SELECT entry_hash FROM audit WHERE seq = ?", (expected_count,))
        if anchor is None or anchor["entry_hash"] != expected_head:
            result.update(
                ok=False,
                first_bad_seq=expected_count,
                problem="entry at the recorded anchor no longer has the recorded hash",
            )
    return result


def export_csv(
    *,
    actor: str | None = None,
    action: str | None = None,
    object_type: str | None = None,
    object_id: str | None = None,
    store: Store | None = None,
) -> str:
    """Every matching entry, oldest first, as CSV (header + one row per entry)."""
    entries, _total = list_entries(
        limit=1_000_000,
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=object_id,
        newest_first=False,
        store=store,
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for e in entries:
        d = e.model_dump()
        d["at"] = iso_utc(e.at)
        writer.writerow(["" if d[c] is None else d[c] for c in CSV_COLUMNS])
    return buf.getvalue()

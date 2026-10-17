"""SQLite storage for the compliance layer (stdlib `sqlite3`).

The audit log (`audit`) and the signature table (`signatures`) are append-only at the database
level: triggers abort every UPDATE and DELETE. No code path in this package updates or deletes
those rows (a test greps the package source to keep it that way).

One process-wide store is created lazily from `TP_COMPLIANCE_DB` / `TP_DB_PATH`
(default `<repo>/var/trialpilot.sqlite`, the same file as A5's API). `configure(path)` replaces it;
tests point it at a temp file.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import default_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq             INTEGER PRIMARY KEY,
    at              TEXT NOT NULL,
    actor           TEXT NOT NULL,
    role            TEXT NOT NULL,
    action          TEXT NOT NULL,
    object_type     TEXT NOT NULL,
    object_id       TEXT NOT NULL,
    before_hash     TEXT,
    after_hash      TEXT,
    reason          TEXT,
    prev_entry_hash TEXT NOT NULL,
    entry_hash      TEXT NOT NULL UNIQUE
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only: UPDATE is forbidden'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only: DELETE is forbidden'); END;

CREATE TABLE IF NOT EXISTS signatures (
    id           TEXT PRIMARY KEY,
    approval_id  TEXT,
    signer       TEXT NOT NULL,
    signer_name  TEXT NOT NULL,
    role         TEXT NOT NULL,
    meaning      TEXT NOT NULL,
    signed_at    TEXT NOT NULL,
    record_type  TEXT NOT NULL,
    record_id    TEXT NOT NULL,
    record_hash  TEXT NOT NULL,
    reason       TEXT
);
CREATE TRIGGER IF NOT EXISTS signatures_no_update BEFORE UPDATE ON signatures
BEGIN SELECT RAISE(ABORT, 'signatures are append-only: UPDATE is forbidden'); END;
CREATE TRIGGER IF NOT EXISTS signatures_no_delete BEFORE DELETE ON signatures
BEGIN SELECT RAISE(ABORT, 'signatures are append-only: DELETE is forbidden'); END;

CREATE TABLE IF NOT EXISTS compliance_users (
    username        TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    role            TEXT NOT NULL,
    pin_hash        TEXT NOT NULL,
    pepper_id       TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT
);

CREATE TABLE IF NOT EXISTS approvals (
    id                TEXT PRIMARY KEY,
    record_type       TEXT NOT NULL,
    record_id         TEXT NOT NULL,
    record_hash       TEXT NOT NULL,
    author            TEXT NOT NULL,
    required_meanings TEXT NOT NULL,
    status            TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    closed_at         TEXT,
    closed_by         TEXT,
    reject_reason     TEXT,
    title             TEXT
);

CREATE TABLE IF NOT EXISTS file_records (
    record_type   TEXT NOT NULL,
    record_id     TEXT NOT NULL,
    path          TEXT NOT NULL,
    registered_at TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id)
);
"""


class Store:
    """One SQLite connection guarded by a re-entrant lock.

    `tx()` opens `BEGIN IMMEDIATE` (a write lock that also serialises other processes such as the
    `tpv` CLI using the same file) and nests: only the outermost block commits or rolls back.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._depth = 0
        self.conn = sqlite3.connect(
            str(path), check_same_thread=False, isolation_level=None, timeout=30
        )
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout = 30000")
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)
        self.seeded = False

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            outer = self._depth == 0
            if outer:
                self.conn.execute("BEGIN IMMEDIATE")
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outer:
                    self.conn.execute("ROLLBACK")
                raise
            else:
                self._depth -= 1
                if outer:
                    self.conn.execute("COMMIT")

    def query(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: tuple[Any, ...] | list[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            row: sqlite3.Row | None = self.conn.execute(sql, params).fetchone()
            return row

    def close(self) -> None:
        with self._lock:
            self.conn.close()


_store: Store | None = None
_store_lock = threading.Lock()


def configure(path: str | Path | None = None) -> Store:
    """(Re)open the process-wide store at `path` (default from env) and seed the demo users."""
    global _store
    with _store_lock:
        if _store is not None:
            _store.close()
        _store = Store(path if path is not None else default_db_path())
    from . import roles  # local import: roles depends on store

    roles.seed_demo_users(_store)
    return _store


def get_store() -> Store:
    if _store is None:
        return configure()
    return _store

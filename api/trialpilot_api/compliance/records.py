"""Where the *current* hash of a signed record comes from.

A signature binds to the record hash at signing time. On every read we ask the record's owner for
its current hash; if it differs, the signature is shown as invalid.

- In-process owners register a resolver: `register_resolver("scenario", fn)` where
  `fn(record_id) -> current sha256 | None` (A5 registers scenarios).
- File-based records (tpv test protocols, validation reports) are registered in the DB with
  `register_file(...)`, so the API server and the `tpv` CLI (separate processes) agree.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .config import repo_root
from .hashing import file_sha256, iso_utc, now
from .store import Store, get_store

Resolver = Callable[[str], str | None]

_resolvers: dict[str, Resolver] = {}


def register_resolver(record_type: str, fn: Resolver) -> None:
    _resolvers[record_type] = fn


def unregister_resolver(record_type: str) -> None:
    _resolvers.pop(record_type, None)


def _stored_path(path: Path) -> str:
    """Store paths relative to the repo when possible, so a moved checkout still resolves."""
    p = path.resolve()
    try:
        return p.relative_to(repo_root()).as_posix()
    except ValueError:
        return p.as_posix()


def _resolve_path(stored: str) -> Path:
    p = Path(stored)
    return p if p.is_absolute() else repo_root() / p


def register_file(
    record_type: str, record_id: str, path: str | Path, *, store: Store | None = None
) -> None:
    st = store or get_store()
    with st.tx() as conn:
        conn.execute(
            "INSERT INTO file_records (record_type, record_id, path, registered_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(record_type, record_id) DO UPDATE SET path = excluded.path,"
            " registered_at = excluded.registered_at",
            (record_type, record_id, _stored_path(Path(path)), iso_utc(now())),
        )


def file_for(record_type: str, record_id: str, *, store: Store | None = None) -> Path | None:
    st = store or get_store()
    row = st.query_one(
        "SELECT path FROM file_records WHERE record_type = ? AND record_id = ?",
        (record_type, record_id),
    )
    return _resolve_path(row["path"]) if row else None


def current_hash(record_type: str, record_id: str, *, store: Store | None = None) -> str | None:
    """Current sha256 of the record, or None when no owner can tell (unknown / missing)."""
    fn = _resolvers.get(record_type)
    if fn is not None:
        try:
            return fn(record_id)
        except Exception:  # an owner's resolver failing must not break approvals reads
            return None
    path = file_for(record_type, record_id, store=store)
    if path is not None and path.is_file():
        return file_sha256(path)
    return None

"""Audit adapter for ops mutations.

Uses A7's `trialpilot_api.compliance.audit.append` when it is importable (keyword arguments are matched to
its signature). Until then — or when `TP_OPS_AUDIT_STUB=1` — entries go to an in-memory, sha256
hash-chained stub with the `AuditEntry` shape (MASTER §5), so the ops tests can assert on them.
A failure of the real audit log is NOT swallowed: an unaudited mutation must not succeed.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from ._contracts import AuditEntry

GENESIS = hashlib.sha256(b"trialpilot-genesis").hexdigest()
SYSTEM_ACTOR = "system:ops-detector"
_ROLES = {"author", "reviewer", "qa", "admin", "viewer"}

_lock = threading.Lock()
_stub: list[AuditEntry] = []
_sink: ContextVar[Any] = ContextVar("ops_audit_sink", default=None)


@contextmanager
def bound(sink):
    """Bind A5's app-specific compliance adapter, including across worker threads."""
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def _canon(obj: Any) -> str:
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def record_hash(obj: Any) -> str | None:
    return None if obj is None else hashlib.sha256(_canon(obj).encode("utf-8")).hexdigest()


def _real_append():
    if os.environ.get("TP_OPS_AUDIT_STUB", "").strip() in {"1", "true", "yes"}:
        return None
    try:
        from trialpilot_api.compliance import audit as a7  # type: ignore[import-not-found]
    except Exception:
        return None
    fn = getattr(a7, "append", None)
    return fn if callable(fn) else None


def append(*, actor: str, role: str, action: str, object_type: str, object_id: str,
           before: Any = None, after: Any = None, reason: str | None = None) -> Any:
    role = role if role in _ROLES else "viewer"
    values = {
        "actor": actor, "role": role, "action": action, "object_type": object_type, "object_id": object_id,
        "before": before, "after": after, "before_hash": record_hash(before), "after_hash": record_hash(after),
        "reason": reason,
    }
    fn = _sink.get() or _real_append()
    if fn is not None:
        params = inspect.signature(fn).parameters
        accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
        kwargs = {k: v for k, v in values.items() if accepts_any or k in params}
        if not accepts_any and "before" in params and "before_hash" not in params:
            kwargs.pop("before_hash", None)
        return fn(**kwargs)
    with _lock:
        prev = _stub[-1].entry_hash if _stub else GENESIS
        at = datetime.now(UTC)
        body = {"seq": len(_stub) + 1, "at": at.isoformat(), "actor": actor, "role": role, "action": action,
                "object_type": object_type, "object_id": object_id, "before_hash": values["before_hash"],
                "after_hash": values["after_hash"], "reason": reason, "prev_entry_hash": prev}
        entry_hash = hashlib.sha256((prev + _canon(body)).encode("utf-8")).hexdigest()
        entry = AuditEntry(**{**body, "at": at}, entry_hash=entry_hash)  # type: ignore[arg-type]
        _stub.append(entry)
        return entry


def stub_entries() -> list[AuditEntry]:
    with _lock:
        return list(_stub)


def stub_verify() -> bool:
    with _lock:
        prev = GENESIS
        for e in _stub:
            body = e.model_dump(mode="json")
            body.pop("entry_hash")
            body["at"] = e.at.isoformat()
            if e.prev_entry_hash != prev:
                return False
            if hashlib.sha256((prev + _canon(body)).encode("utf-8")).hexdigest() != e.entry_hash:
                return False
            prev = e.entry_hash
        return True


def using_stub() -> bool:
    return _real_append() is None

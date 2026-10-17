"""Audit adapter for ops mutations.

Entries go to the sink bound with `bound()` — the app's compliance adapter (A7's audit log) or an explicit
no-op for pure simulations; keyword arguments are matched to its signature. With no sink bound, `append`
raises, and a failure of the audit log is NOT swallowed: an unaudited mutation must not succeed.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

SYSTEM_ACTOR = "system:ops-detector"
_ROLES = {"author", "reviewer", "qa", "admin", "viewer"}

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


def append(*, actor: str, role: str, action: str, object_type: str, object_id: str,
           before: Any = None, after: Any = None, reason: str | None = None) -> Any:
    role = role if role in _ROLES else "viewer"
    values = {
        "actor": actor, "role": role, "action": action, "object_type": object_type, "object_id": object_id,
        "before": before, "after": after, "before_hash": record_hash(before), "after_hash": record_hash(after),
        "reason": reason,
    }
    fn = _sink.get()
    if fn is None:
        raise RuntimeError("ops audit sink is not bound")
    params = inspect.signature(fn).parameters
    accepts_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    kwargs = {k: v for k, v in values.items() if accepts_any or k in params}
    if not accepts_any and "before" in params and "before_hash" not in params:
        kwargs.pop("before_hash", None)
    return fn(**kwargs)

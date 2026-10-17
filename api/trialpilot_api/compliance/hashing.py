"""Canonical JSON, SHA-256 helpers, UTC timestamps and the injectable clock.

Everything that is hashed (audit entries, records, signatures) goes through `canonical_json`, so the
same content always produces the same hash regardless of key order or whitespace.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel

GENESIS_HASH = hashlib.sha256(b"trialpilot-genesis").hexdigest()

_ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _system_now() -> datetime:
    return datetime.now(timezone.utc)


_now: Callable[[], datetime] = _system_now


def now() -> datetime:
    """Current UTC time. Tests replace it with `set_clock` (e.g. to step past a lockout)."""
    return _now()


def set_clock(fn: Callable[[], datetime] | None) -> None:
    global _now
    _now = fn or _system_now


def iso_utc(dt: datetime) -> str:
    """ISO 8601 UTC with microseconds and a trailing `Z`. Naive datetimes are rejected."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime: compliance timestamps must be timezone-aware UTC")
    return dt.astimezone(timezone.utc).strftime(_ISO_FORMAT)


def parse_utc(value: str) -> datetime:
    return datetime.strptime(value, _ISO_FORMAT).replace(tzinfo=timezone.utc)


def _normalize(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return _normalize(obj.model_dump(mode="json"))
    if isinstance(obj, datetime):
        return iso_utc(obj)
    if isinstance(obj, dict):
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_normalize(v) for v in obj]
    if isinstance(obj, set | frozenset):
        return sorted(_normalize(v) for v in obj)
    if isinstance(obj, Path):
        return obj.as_posix()
    return obj


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8, NaN forbidden."""
    return json.dumps(
        _normalize(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def sha256_hex(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def record_hash(content: Any) -> str:
    """Hash of a record for `before_hash`/`after_hash`/signatures.

    Raw bytes are hashed as-is; anything else (pydantic model, dict, list, str) via canonical JSON.
    """
    if isinstance(content, bytes | bytearray):
        return hashlib.sha256(bytes(content)).hexdigest()
    return sha256_hex(canonical_json(content))


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()

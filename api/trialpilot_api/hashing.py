"""Canonical JSON + sha256 helpers used for cache keys and record hashes."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8 kept as-is."""
    return json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(obj: Any) -> str:
    data = obj if isinstance(obj, (bytes, str)) else canonical_json(obj)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()

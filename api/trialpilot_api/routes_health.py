"""/api/health — status + `offline` flag + which modules are live (for the UI badges)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from . import __version__
from .db import db_ok
from .deps import services

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(svc: Any = Depends(services)) -> dict[str, Any]:
    snap = svc.params.current()
    database = db_ok(svc.db_engine)
    return {
        "status": "ok" if database else "degraded",
        "offline": svc.settings.demo_offline,
        "version": __version__,
        "database": {"ok": database},
        "params": {
            "ok": snap.ok, "count": len(snap.params), "assumptions": snap.assumption_count,
            "parameter_set_version": snap.version, "problems": len(snap.problems),
            "conflicts": len(snap.conflicts),
        },
        "engine": {"ready": svc.engine.ready, **svc.engine.fns.status,
                   "cache": {"hits": svc.engine.cache.hits, "misses": svc.engine.cache.misses}},
        "compliance": dict(svc.compliance.status),
        "modules": svc.modules,
        "science_results": svc.settings.resolved_science_results.is_file(),
        "identity": "demo headers X-User / X-Role (no login; prototype only)",
    }

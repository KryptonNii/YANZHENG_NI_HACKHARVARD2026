"""Mount the routers other agents own, or 501 `not_ready` stubs until they import cleanly.

    A4 importers   trialpilot_api.importers   `router`                      -> /api/import
    A6 ops         trialpilot_api.ops         `router`                      -> /api/ops
    A7 compliance  trialpilot_api.compliance  `router` (or audit_router, approvals_router,
                                              validation_router)            -> /api/audit,
                                                                               /api/approvals,
                                                                               /api/validation
A router may declare full paths ("/api/ops/...") or paths relative to its mount ("/{trial_id}/...");
both are detected. Also serves the built web app (web/dist) at `/` when it exists (production).
"""

from __future__ import annotations

import importlib
import logging
import types
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute

from .errors import ApiError

log = logging.getLogger("trialpilot.mounts")

OPTIONAL_MODULES: list[dict[str, Any]] = [
    {"key": "importers", "module": "trialpilot_api.importers", "owner": "A4",
     "routers": {"router": ["/api/import"]}},
    {"key": "ops", "module": "trialpilot_api.ops", "owner": "A6",
     "routers": {"router": ["/api/ops"]}},
    {"key": "compliance", "module": "trialpilot_api.compliance", "owner": "A7",
     "routers": {"router": ["/api/audit", "/api/approvals", "/api/validation"],
                 "audit_router": ["/api/audit"], "approvals_router": ["/api/approvals"],
                 "validation_router": ["/api/validation"]}},
]

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def _find_router(pkg: types.ModuleType, attr: str) -> APIRouter | None:
    obj = getattr(pkg, attr, None)
    if obj is None:
        try:
            obj = importlib.import_module(f"{pkg.__name__}.{attr}")
        except ImportError:
            return None
    if isinstance(obj, types.ModuleType):
        obj = getattr(obj, "router", None)
    return obj if isinstance(obj, APIRouter) else None


def _paths(router: APIRouter) -> list[str]:
    return [r.path for r in router.routes if isinstance(r, APIRoute)]


def _include(app: FastAPI, router: APIRouter, prefixes: list[str]) -> str:
    """Include with the right prefix. Returns the prefix used ("" if paths are absolute)."""
    paths = _paths(router)
    if paths and all(p.startswith("/api/") for p in paths):
        app.include_router(router)
        return ""
    if len(prefixes) > 1:
        # One router serving several mounts with relative paths like "/audit/verify".
        app.include_router(router, prefix="/api")
        return "/api"
    app.include_router(router, prefix=prefixes[0])
    return prefixes[0]


def _stub_router(prefix: str, key: str, owner: str, reason: str) -> APIRouter:
    r = APIRouter(prefix=prefix, tags=[f"{key} (not ready)"])

    async def not_ready(request: Request) -> None:
        raise ApiError(501, "not_ready",
                       f"This part of TrialPilot ({key}, owned by {owner}) is not available yet.",
                       {"module": key, "owner": owner, "path": request.url.path,
                        "reason": reason})

    r.add_api_route("", not_ready, methods=_METHODS, include_in_schema=False)
    r.add_api_route("/{rest:path}", not_ready, methods=_METHODS, include_in_schema=False)
    return r


def mount_optional_routers(app: FastAPI, enabled: bool = True) -> dict[str, dict[str, Any]]:
    status: dict[str, dict[str, Any]] = {}
    for spec in OPTIONAL_MODULES:
        key, owner = spec["key"], spec["owner"]
        all_prefixes = sorted({p for ps in spec["routers"].values() for p in ps})
        reason = "disabled by TP_MOUNT_OPTIONAL_ROUTERS=0" if not enabled else ""
        pkg: types.ModuleType | None = None
        if enabled:
            try:
                pkg = importlib.import_module(spec["module"])
            except Exception as exc:  # missing or half-built: never take the API down
                reason = f"{type(exc).__name__}: {exc}"[:300]
        mounted: list[str] = []
        covered: set[str] = set()
        if pkg is not None:
            for attr, prefixes in spec["routers"].items():
                if covered.issuperset(prefixes):
                    continue
                try:
                    router = _find_router(pkg, attr)
                except Exception as exc:
                    reason = f"{attr}: {type(exc).__name__}: {exc}"[:300]
                    continue
                if router is None:
                    continue
                used = _include(app, router, prefixes)
                mounted.append(f"{attr}@{used or '/'}")
                covered.update(prefixes)
            if not mounted and not reason:
                reason = f"{spec['module']} has no FastAPI router ({', '.join(spec['routers'])})"
        for prefix in all_prefixes:
            if prefix not in covered:
                app.include_router(_stub_router(prefix, key, owner, reason))
        status[key] = {"status": "mounted" if mounted else "not_ready", "owner": owner,
                       "routers": mounted, "reason": reason or None}
        if not mounted:
            log.info("optional router not mounted", extra={"component": key, "reason": reason})
    return status


def mount_web(app: FastAPI, dist: Path) -> bool:
    """Serve the built SPA (production / Docker). Unknown non-API paths fall back to index.html."""
    index = dist / "index.html"
    if not index.is_file():
        return False
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise ApiError(404, "not_found", "No such endpoint.", {"path": f"/{path}"})
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)

    return True

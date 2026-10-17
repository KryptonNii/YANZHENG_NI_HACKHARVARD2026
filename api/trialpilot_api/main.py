"""FastAPI app factory (owner: A5).

    uvicorn trialpilot_api.main:create_app --factory --port 8000     # preferred
    uvicorn trialpilot_api.main:app --port 8000                       # also works (lazy app)
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from . import (
    __version__,
    routes_designs,
    routes_export,
    routes_health,
    routes_params,
    routes_scenarios,
    routes_science,
)
from .compliance_adapter import ComplianceAdapter
from .db import init_db, make_engine
from .engine_adapter import EngineAdapter, EngineFns, load_engine
from .errors import error_body, install_error_handlers
from .logs import RequestIdMiddleware, configure_logging, request_id_var
from .mounts import mount_optional_routers, mount_web
from .params_store import ParamStore
from .services import Services
from .settings import Settings, get_settings
from .sse import EventBroker

log = logging.getLogger("trialpilot.api")

DESCRIPTION = """TrialPilot API — scenario simulator + command center for clinical trials.

Every metric is a P10/P50/P90 range with provenance. Error shape for every endpoint:
`{"error": "<code>", "message": "<plain English>", "details": {...}}`.

**Demo identity only:** mutations take the acting user from `X-User`; the role (author, reviewer,
qa, admin, viewer) comes from the user registry, and an `X-Role` header that disagrees with it is
refused (403 `role_mismatch`). There is no login in this prototype.
"""


def create_app(settings: Settings | None = None, *, engine_fns: EngineFns | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    db_engine = make_engine(settings.resolved_db_path)
    init_db(db_engine)
    compliance = ComplianceAdapter(
        db_engine, settings.resolved_db_path, use_a7=settings.mount_optional_routers
    )
    svc = Services(
        settings=settings,
        db_engine=db_engine,
        params=ParamStore(settings.resolved_params_dir, db_engine),
        engine=EngineAdapter(engine_fns or load_engine(), settings.compute_cache_size,
                             settings.compute_concurrency),
        compliance=compliance,
        broker=EventBroker(),
    )

    app = FastAPI(title="TrialPilot API", version=__version__, description=DESCRIPTION)
    app.state.services = svc
    app.state.db_engine = db_engine
    app.state.settings = settings

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Compute-Ms", "X-Queue-Ms", "X-Cache", "X-Parameter-Set-Version",
                        "X-Design-Version", "X-Request-ID", "ETag", "Location"],
    )
    app.add_middleware(RequestIdMiddleware)
    install_error_handlers(app)

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError) -> JSONResponse:
        msg = str(exc.orig) if exc.orig is not None else str(exc)
        if "scenario_immutable" in msg or "scenario_status" in msg:
            code, text = "scenario_immutable", ("A submitted or approved scenario cannot change; "
                                                "create a new version.")
        elif "immutable" in msg:
            code, text = "record_immutable", "This record is immutable."
        else:
            code, text = "conflict", "A concurrent change conflicted with this one; retry."
        body = error_body(code, text, {"db": msg[:200]})
        rid = request_id_var.get()
        if rid:
            body["details"]["request_id"] = rid
        return JSONResponse(status_code=409, content=body)

    _install_compliance_error_handler(app)

    for module in (routes_health, routes_designs, routes_scenarios, routes_params,
                   routes_science, routes_export):
        app.include_router(module.router)
    svc.modules.update(mount_optional_routers(app, settings.mount_optional_routers))
    compliance.register_record_resolver(
        "scenario", partial(routes_scenarios.resolve_scenario_hash, db_engine)
    )

    # Startup work (in the factory so tests and uvicorn behave the same).
    snap = svc.params.current()
    if settings.seed_fixture_designs:
        seeded = routes_designs.seed_fixture_designs(svc, settings.resolved_fixtures_dir)
        if seeded:
            log.info("seeded fixture designs", extra={"design_ids": seeded})
    svc.modules["web"] = {"status": "served" if mount_web(app, settings.resolved_web_dist)
                          else "not_built", "owner": "A8/A9"}
    log.info("api ready", extra={
        "db": str(settings.resolved_db_path), "offline": settings.demo_offline,
        "params_ok": snap.ok, "param_count": len(snap.params), "engine_ready": svc.engine.ready,
        "modules": {k: v["status"] for k, v in svc.modules.items()},
    })
    return app


def _install_compliance_error_handler(app: FastAPI) -> None:
    """A7 raises ComplianceError(status, code, message, details); render it in the §5 shape."""
    try:
        from .compliance.errors import ComplianceError
    except Exception:  # A7 package missing or half-built
        return

    @app.exception_handler(ComplianceError)
    async def _compliance(_: Request, exc: Any) -> JSONResponse:
        body = error_body(exc.code, exc.message, dict(exc.details or {}))
        rid = request_id_var.get()
        if rid:
            body["details"].setdefault("request_id", rid)
        return JSONResponse(status_code=exc.status, content=body)


def __getattr__(name: str) -> Any:
    """`trialpilot_api.main:app` is built lazily, so importing this module has no side effects."""
    if name == "app":
        globals()["app"] = application = create_app()
        return application
    raise AttributeError(name)

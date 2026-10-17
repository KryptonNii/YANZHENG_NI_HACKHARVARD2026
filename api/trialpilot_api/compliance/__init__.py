"""Compliance layer (owner: A7): audit trail, e-signatures, roles, approval workflow.

    from trialpilot_api.compliance import audit, hashing
    audit.append(actor, role, action, object_type, object_id, before_hash, after_hash, reason)
    hashing.record_hash(model_or_dict)   # for before_hash / after_hash

    from trialpilot_api.compliance import configure, router, ComplianceError, compliance_error_handler
    configure(settings.resolved_db_path)          # once at startup (same SQLite file as the API)
    app.include_router(router)                    # absolute /api/... paths, no prefix
    app.add_exception_handler(ComplianceError, compliance_error_handler)

`router` is imported lazily so the CLI (`tpv`) can use the core without FastAPI.
"""

from __future__ import annotations

from typing import Any

from . import audit, esign, hashing, records, roles, workflow
from .errors import ComplianceError
from .store import configure, get_store

__all__ = [
    "ComplianceError",
    "audit",
    "compliance_error_handler",
    "configure",
    "esign",
    "get_store",
    "hashing",
    "records",
    "roles",
    "router",
    "workflow",
]


def __getattr__(name: str) -> Any:
    if name in ("router", "compliance_error_handler"):
        from . import routes as _routes_module

        return getattr(_routes_module, name)
    raise AttributeError(name)

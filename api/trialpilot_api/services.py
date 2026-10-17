"""Per-app service container (stored on `app.state.services`) + the audited-write helper."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from sqlalchemy.engine import Engine
from sqlmodel import Session

from .compliance_adapter import ComplianceAdapter
from .deps import Identity
from .engine_adapter import EngineAdapter
from .params_store import ParamStore
from .settings import Settings
from .sse import EventBroker

log = logging.getLogger("trialpilot.services")

T = TypeVar("T")


@dataclass
class Services:
    settings: Settings
    db_engine: Engine
    params: ParamStore
    engine: EngineAdapter
    compliance: ComplianceAdapter
    broker: EventBroker
    modules: dict[str, dict[str, Any]] = field(default_factory=dict)

    def audited_write(
        self,
        session: Session,
        ident: Identity,
        action: str,
        object_type: str,
        object_id: str,
        before_hash: str | None,
        after_hash: str | None,
        write: Callable[[Session], T],
        reason: str | None = None,
    ) -> T:
        """Audit first, then write (MASTER §5: every mutation writes an AuditEntry).

        The audit entry is committed before the data change, so a change can never exist
        without its entry. If the write then fails, a compensating `<action>.failed` entry is
        appended and the error re-raised.
        """
        session.rollback()  # end any read transaction before the audit store writes
        self.compliance.append(
            ident.user, ident.role, action, object_type, object_id, before_hash, after_hash, reason
        )
        try:
            out = write(session)
            session.commit()
            return out
        except Exception as exc:
            session.rollback()
            try:
                self.compliance.append(
                    ident.user, ident.role, f"{action}.failed", object_type, object_id,
                    before_hash, before_hash, f"change not applied: {type(exc).__name__}",
                )
            except Exception:  # pragma: no cover - never mask the original error
                log.exception("compensating audit entry failed")
            raise

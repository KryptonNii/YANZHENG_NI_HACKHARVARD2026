"""Bridge to A7's compliance layer (audit trail, approvals, signatures).

When `trialpilot_api.compliance` is importable its functions are used. Until then a stub with the
same signatures keeps every mutation audited (hash-chained, append-only `audit_stub` table) and
lets scenarios be submitted (`approvals_stub`). `/api/health` reports which one is active.

A7 surface used (handoffs/A7.md):
    compliance.configure(db_path)                         same SQLite file as the API
    compliance.audit.append(actor, role, action, object_type, object_id, before_hash,
                            after_hash, reason=None) -> AuditEntry
    compliance.workflow.create_request(record_type, record_id, author, *, record_hash, title,
                                       reason) -> ApprovalRequest
    compliance.workflow.get_request(approval_id) -> ApprovalRequest
    compliance.records.register_resolver(record_type, fn)  fn(record_id) -> current hash | None
"""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import threading
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlmodel import Session, col, select

from ._contracts import ROLES, ApprovalRequest, AuditEntry
from .db import ApprovalStubRow, AuditStubRow, utcnow_iso
from .hashing import canonical_json

log = logging.getLogger("trialpilot.compliance_adapter")

GENESIS_HASH = hashlib.sha256(b"trialpilot-genesis").hexdigest()

# Required signature meanings per record type (MASTER §9 A7: scenario reviewed -> approved).
REQUIRED_MEANINGS: dict[str, list[str]] = {
    "scenario": ["reviewed", "approved"],
    "test_protocol": ["approved"],
    "validation_report": ["approved"],
    "change_record": ["reviewed", "approved"],
}

RecordResolver = Callable[[str], "str | None"]  # record_id -> current record hash


def _approval_from_stub_row(row: ApprovalStubRow) -> ApprovalRequest:
    """Read a stub approval. Contract v3 requires record_hash and created_at.

    Rows written before those fields were required still have both on the table columns.
    Fill them from the columns so a missing key in the JSON body is not a 500.
    """
    data = json.loads(row.data)
    if not isinstance(data, dict):
        data = {}
    if not data.get("record_hash"):
        data["record_hash"] = row.record_hash
    if not data.get("created_at"):
        data["created_at"] = row.created_at
    data.setdefault("id", row.id)
    data.setdefault("record_type", row.record_type)
    data.setdefault("record_id", row.record_id)
    data.setdefault("author", row.author)
    data.setdefault("status", row.status)
    data.setdefault("title", None)
    data.setdefault("signatures", [])
    return ApprovalRequest.model_validate(data)


def _as_model(model: Any, value: Any) -> Any:
    if value is None or isinstance(value, model):
        return value
    if hasattr(value, "model_dump"):
        return model.model_validate(value.model_dump(mode="json"))
    return model.model_validate(value)


class ComplianceAdapter:
    def __init__(self, engine: Engine, db_path: Path, *, use_a7: bool = True) -> None:
        self.engine = engine
        self.db_path = db_path
        self._lock = threading.Lock()
        self._audit_mod: Any = None
        self._workflow_mod: Any = None
        self._records_mod: Any = None
        self._roles_mod: Any = None
        self.status: dict[str, str] = {}
        if use_a7:
            self._load_a7()
        self.status.setdefault("audit", "stub")
        self.status.setdefault("approvals", "stub")
        self.status.setdefault("roles", "header")

    # ---------------------------------------------------------------- A7 discovery
    def _load_a7(self) -> None:
        try:
            pkg = importlib.import_module("trialpilot_api.compliance")
            pkg.configure(self.db_path)
            audit, workflow, records = pkg.audit, pkg.workflow, pkg.records
        except Exception as exc:  # missing or half-built package: keep the stub
            log.warning("A7 compliance not usable, using the stub", extra={"error": str(exc)})
            self.status["reason"] = f"{type(exc).__name__}: {exc}"[:300]
            return
        self._audit_mod, self._workflow_mod, self._records_mod = audit, workflow, records
        try:
            roles = importlib.import_module("trialpilot_api.compliance.roles")
            self._roles_mod = roles if callable(getattr(roles, "get_user", None)) else None
        except Exception as exc:
            log.warning("A7 user registry not usable", extra={"error": str(exc)})
        self.status.update(audit="a7", approvals="a7",
                           roles="registry" if self._roles_mod is not None else "header")

    @property
    def has_user_registry(self) -> bool:
        return self._roles_mod is not None

    def registered_role(self, username: str) -> str | None:
        """Role of a registered user (A7 registry, URS-023); None if the user is unknown.

        Only meaningful when `has_user_registry`; the stub has no registry.
        """
        if self._roles_mod is None:
            return None
        user = self._roles_mod.get_user(username)
        return str(user.role) if user is not None else None

    def register_record_resolver(self, record_type: str, fn: RecordResolver) -> None:
        """Let A7 check, on every read, that a signed record still has the signed hash."""
        if self._records_mod is not None:
            self._records_mod.register_resolver(record_type, fn)

    # ---------------------------------------------------------------- audit
    def append(
        self,
        actor: str,
        role: str,
        action: str,
        object_type: str,
        object_id: str,
        before_hash: str | None,
        after_hash: str | None,
        reason: str | None = None,
    ) -> AuditEntry:
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        if self._audit_mod is not None:
            entry = self._audit_mod.append(
                actor, role, action, object_type, object_id, before_hash, after_hash, reason
            )
            return _as_model(AuditEntry, entry)
        return self._stub_append(
            actor, role, action, object_type, object_id, before_hash, after_hash, reason
        )

    def _stub_append(
        self,
        actor: str,
        role: str,
        action: str,
        object_type: str,
        object_id: str,
        before_hash: str | None,
        after_hash: str | None,
        reason: str | None,
    ) -> AuditEntry:
        with self._lock, Session(self.engine) as s:
            last = s.exec(select(AuditStubRow).order_by(col(AuditStubRow.seq).desc())).first()
            seq = (last.seq + 1) if last else 1
            prev = last.entry_hash if last else GENESIS_HASH
            body = {
                "seq": seq, "at": utcnow_iso(), "actor": actor, "role": role, "action": action,
                "object_type": object_type, "object_id": object_id, "before_hash": before_hash,
                "after_hash": after_hash, "reason": reason, "prev_entry_hash": prev,
            }
            entry_hash = hashlib.sha256((canonical_json(body) + prev).encode("utf-8")).hexdigest()
            s.add(AuditStubRow(**body, entry_hash=entry_hash))
            s.commit()
        return AuditEntry.model_validate({**body, "entry_hash": entry_hash})

    def stub_entries(self, object_id: str | None = None) -> list[AuditEntry]:
        """Entries written by the stub (tests / dev only; A7 owns the real `/api/audit`)."""
        with Session(self.engine) as s:
            q = select(AuditStubRow).order_by(col(AuditStubRow.seq))
            if object_id is not None:
                q = q.where(AuditStubRow.object_id == object_id)
            rows = s.exec(q).all()
        return [AuditEntry.model_validate(r.model_dump()) for r in rows]

    def stub_verify(self) -> dict[str, Any]:
        prev = GENESIS_HASH
        checked = 0
        with Session(self.engine) as s:
            rows = s.exec(select(AuditStubRow).order_by(col(AuditStubRow.seq))).all()
        for r in rows:
            body = r.model_dump(exclude={"entry_hash"})
            expect = hashlib.sha256((canonical_json(body) + prev).encode("utf-8")).hexdigest()
            if r.prev_entry_hash != prev or r.entry_hash != expect:
                return {"ok": False, "first_bad_seq": r.seq, "checked": checked}
            prev = r.entry_hash
            checked += 1
        return {"ok": True, "first_bad_seq": None, "checked": checked}

    # ---------------------------------------------------------------- approvals
    def create_approval(
        self, record_type: str, record_id: str, record_hash: str, author: str,
        title: str | None = None, reason: str | None = None,
    ) -> ApprovalRequest:
        if self._workflow_mod is not None:
            req = self._workflow_mod.create_request(
                record_type, record_id, author, record_hash=record_hash, title=title,
                reason=reason,
            )
            return _as_model(ApprovalRequest, req)
        meanings = REQUIRED_MEANINGS.get(record_type, ["approved"])
        # Contract v3: record_hash and created_at are required. The row columns hold the
        # same values so an older JSON body can be read back (see _approval_from_stub_row).
        req = ApprovalRequest(
            id=str(uuid.uuid4()), record_type=record_type, record_id=record_id,  # type: ignore[arg-type]
            author=author, record_hash=record_hash, required_meanings=meanings, status="pending",
            created_at=utcnow_iso(), title=title, signatures=[],
        )
        with Session(self.engine) as s:
            s.add(ApprovalStubRow(
                id=req.id, record_type=record_type, record_id=record_id, record_hash=record_hash,
                author=author, status=req.status, data=canonical_json(req),
                created_at=utcnow_iso(),
            ))
            s.commit()
        return req

    def get_approval(self, approval_id: str | None) -> ApprovalRequest | None:
        if not approval_id:
            return None
        if self._workflow_mod is not None:
            try:
                return _as_model(ApprovalRequest, self._workflow_mod.get_request(approval_id))
            except Exception:
                log.exception("A7 get_request failed", extra={"approval_id": approval_id})
                return None
        with Session(self.engine) as s:
            row = s.get(ApprovalStubRow, approval_id)
        return _approval_from_stub_row(row) if row else None

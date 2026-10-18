"""SQLite (WAL) database via SQLModel.

Tables (JSON payloads are stored as canonical JSON text; timestamps as ISO 8601 UTC strings):

    schema_version   applied schema versions (simple `create_all` + version table "migrations")
    designs          TrialDesign JSON, one immutable row per (design_id, version)
    scenarios        saved scenarios, one row per version; immutable once submitted (triggers)
    scenario_deletions  removal markers; scenario content and approvals remain available to audit
    params           parameter library rows, immutable per (id, version) (triggers)
    param_sets       parameter_set_version -> member (id, version) list, so old results stay explainable
    ops_events, alerts, interventions, effects   storage offered to A6 (see ops_repo.py)
    audit_stub, approvals_stub                   used only until A7's compliance package lands

Immutability is enforced in the database, not only in route code (MASTER §2.5).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import UniqueConstraint, event, text
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, create_engine, select

log = logging.getLogger("trialpilot.db")

SCHEMA_VERSION = 1


def utcnow_iso() -> str:
    """UTC timestamp, ISO 8601 with milliseconds and a trailing Z."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ----------------------------------------------------------------------------------------
# Tables
# ----------------------------------------------------------------------------------------
class SchemaVersionRow(SQLModel, table=True):
    __tablename__ = "schema_version"
    version: int = Field(primary_key=True)
    applied_at: str


class DesignRow(SQLModel, table=True):
    __tablename__ = "designs"
    __table_args__ = (UniqueConstraint("design_id", "version"),)
    pk: int | None = Field(default=None, primary_key=True)
    design_id: str = Field(index=True)
    version: int
    title: str
    source: str
    registry_id: str | None = None
    design_hash: str
    data: str  # TrialDesign JSON
    created_at: str
    created_by: str


class ScenarioRow(SQLModel, table=True):
    __tablename__ = "scenarios"
    __table_args__ = (UniqueConstraint("lineage_id", "version"),)
    id: str = Field(primary_key=True)  # one id per version
    lineage_id: str = Field(index=True)  # shared by every version of the same scenario
    version: int
    parent_id: str | None = None
    name: str
    description: str | None = None
    design_id: str = Field(index=True)
    design_version: int
    design_hash: str
    levers: str  # Levers JSON
    seed: int
    draws: int
    result: str  # ScenarioResult JSON
    parameter_set_version: str
    record_hash: str  # sha256 of the content a signature binds to
    author: str
    author_role: str
    status: str = "draft"  # draft | submitted | approved | rejected
    approval_id: str | None = None
    created_at: str
    submitted_at: str | None = None
    decided_at: str | None = None


class ScenarioDeletionRow(SQLModel, table=True):
    """A removed version stays intact for its lineage, exports, signatures and audit trail."""

    __tablename__ = "scenario_deletions"
    scenario_id: str = Field(primary_key=True)
    deleted_at: str
    deleted_by: str


class ParamRow(SQLModel, table=True):
    """One immutable row per distinct parameter content (a value edited without a version bump
    gets its own row too, and is reported as a conflict)."""

    __tablename__ = "params"
    id: str = Field(primary_key=True)
    content_hash: str = Field(primary_key=True)
    version: int
    data: str  # Parameter JSON
    loaded_at: str


class ParamSetRow(SQLModel, table=True):
    __tablename__ = "param_sets"
    version: str = Field(primary_key=True)  # parameter_set_version (12 hex)
    members: str  # JSON list of [id, content_hash]
    count: int
    created_at: str


class OpsEventRow(SQLModel, table=True):
    __tablename__ = "ops_events"
    seq: int | None = Field(default=None, primary_key=True)
    id: str = Field(index=True, unique=True)
    trial_id: str = Field(index=True)
    site_id: str | None = None
    type: str
    occurred_at: str
    source_system: str
    simulated: bool = True
    data: str  # OpsEvent JSON


class AlertRow(SQLModel, table=True):
    __tablename__ = "alerts"
    id: str = Field(primary_key=True)
    trial_id: str = Field(index=True)
    site_id: str | None = None
    kind: str
    severity: str
    status: str
    detected_at: str
    updated_at: str
    data: str  # Alert JSON


class InterventionRow(SQLModel, table=True):
    __tablename__ = "interventions"
    id: str = Field(primary_key=True)
    trial_id: str = Field(index=True)
    alert_id: str | None = None
    status: str
    updated_at: str
    data: str  # Intervention JSON


class EffectRow(SQLModel, table=True):
    __tablename__ = "effects"
    intervention_id: str = Field(primary_key=True)
    trial_id: str = Field(index=True)
    verdict: str
    computed_at: str
    data: str  # EffectEstimate JSON


class AuditStubRow(SQLModel, table=True):
    """Hash-chained audit log used only until A7's `compliance.audit` is importable."""

    __tablename__ = "audit_stub"
    seq: int = Field(primary_key=True)
    at: str
    actor: str
    role: str
    action: str
    object_type: str
    object_id: str
    before_hash: str | None = None
    after_hash: str | None = None
    reason: str | None = None
    prev_entry_hash: str
    entry_hash: str = Field(unique=True)


class ApprovalStubRow(SQLModel, table=True):
    """Approval requests used only until A7's workflow is importable."""

    __tablename__ = "approvals_stub"
    id: str = Field(primary_key=True)
    record_type: str
    record_id: str = Field(index=True)
    record_hash: str
    author: str
    status: str
    data: str  # ApprovalRequest JSON
    created_at: str


# ----------------------------------------------------------------------------------------
# Triggers: the database refuses forbidden changes even if route code has a bug.
# ----------------------------------------------------------------------------------------
_SCENARIO_CONTENT = (
    "id", "lineage_id", "version", "parent_id", "name", "description", "design_id",
    "design_version", "design_hash", "levers", "seed", "draws", "result",
    "parameter_set_version", "record_hash", "author", "author_role", "created_at",
)  # fmt: skip
_content_changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in _SCENARIO_CONTENT)

TRIGGERS = [
    f"""CREATE TRIGGER IF NOT EXISTS scenarios_content_frozen_after_submit
    BEFORE UPDATE ON scenarios WHEN OLD.status <> 'draft' AND ({_content_changed})
    BEGIN SELECT RAISE(ABORT,
      'scenario_immutable: a submitted scenario cannot change; create a new version'); END""",
    """CREATE TRIGGER IF NOT EXISTS scenarios_decided_frozen
    BEFORE UPDATE ON scenarios WHEN OLD.status IN ('approved', 'rejected')
    BEGIN SELECT RAISE(ABORT,
      'scenario_immutable: approved or rejected scenarios are frozen'); END""",
    """CREATE TRIGGER IF NOT EXISTS scenarios_status_flow
    BEFORE UPDATE OF status ON scenarios WHEN NOT (
        NEW.status = OLD.status
        OR (OLD.status = 'draft' AND NEW.status = 'submitted')
        OR (OLD.status = 'submitted' AND NEW.status IN ('approved', 'rejected')))
    BEGIN SELECT RAISE(ABORT, 'scenario_status: illegal status transition'); END""",
    """CREATE TRIGGER IF NOT EXISTS scenarios_no_delete_after_submit
    BEFORE DELETE ON scenarios WHEN OLD.status <> 'draft'
    BEGIN SELECT RAISE(ABORT, 'scenario_immutable: submitted scenarios cannot be deleted'); END""",
]
for _table in ("designs", "scenario_deletions", "params", "param_sets", "audit_stub"):
    TRIGGERS += [
        f"""CREATE TRIGGER IF NOT EXISTS {_table}_no_update BEFORE UPDATE ON {_table}
        BEGIN SELECT RAISE(ABORT, '{_table} rows are immutable: UPDATE is forbidden'); END""",
        f"""CREATE TRIGGER IF NOT EXISTS {_table}_no_delete BEFORE DELETE ON {_table}
        BEGIN SELECT RAISE(ABORT, '{_table} rows are immutable: DELETE is forbidden'); END""",
    ]


# ----------------------------------------------------------------------------------------
# Engine / session
# ----------------------------------------------------------------------------------------
def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn: Any, _: Any) -> None:  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    return engine


def init_db(engine: Engine) -> None:
    """Create tables + triggers (idempotent) and record the schema version."""
    SQLModel.metadata.create_all(engine)
    with engine.begin() as conn:
        for ddl in TRIGGERS:
            conn.execute(text(ddl))
    with Session(engine) as s:
        if s.get(SchemaVersionRow, SCHEMA_VERSION) is None:
            s.add(SchemaVersionRow(version=SCHEMA_VERSION, applied_at=utcnow_iso()))
            s.commit()


def db_ok(engine: Engine) -> bool:
    try:
        with Session(engine) as s:
            s.exec(select(SchemaVersionRow)).first()
        return True
    except Exception:  # pragma: no cover - reported by /api/health
        log.exception("database check failed")
        return False


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request on the app's engine."""
    with Session(request.app.state.db_engine) as session:
        yield session

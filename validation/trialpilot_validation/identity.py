"""Bridge to the compliance layer (A7's `trialpilot_api.compliance`): store, identity and PINs.

tpv never signs on anyone's behalf: every signature needs the human's username (`--as` or
TPV_USER) and PIN (interactive prompt, or TPV_PIN for scripted runs by that human).
"""

from __future__ import annotations

import getpass
import os
import sys
from typing import Any

from .context import TpvError

SYSTEM_ACTOR = "system:tpv"


def compliance() -> Any:
    try:
        from trialpilot_api import compliance as c
    except ImportError as exc:  # pragma: no cover - environment problem
        raise TpvError(
            "Cannot import trialpilot_api.compliance. Run tpv from the validation venv "
            "(`uv run --project validation tpv ...`)."
        ) from exc
    c.get_store()
    return c


def resolve_user(username: str | None) -> Any:
    c = compliance()
    name = username or os.environ.get("TPV_USER", "").strip()
    if not name:
        raise TpvError("Say who you are: --as <username> (or set TPV_USER). "
                       "Demo users: alex.author, riley.reviewer, sam.qa.")
    try:
        return c.roles.require_user(name)
    except c.ComplianceError as exc:
        raise TpvError(exc.message) from exc


def get_pin(username: str) -> str:
    pin = os.environ.get("TPV_PIN", "")
    if pin:
        return pin
    if sys.stdin is not None and sys.stdin.isatty():
        return getpass.getpass(f"PIN for {username} (re-authentication for signing): ")
    raise TpvError(f"A PIN is required to sign as {username}: run interactively or set TPV_PIN.")


def submit_for_approval(record_type: str, record_id: str, username: str | None, *, title: str,
                        reason: str) -> dict[str, Any]:
    """Submit a record for approval as `username` (or TPV_USER). Idempotent: a pending or approved
    request for this record id is returned instead of a new one (`created` False)."""
    c = compliance()
    user = resolve_user(username)
    st = c.workflow.approval_status(record_type, record_id)
    if st["approval_id"] and st["status"] in ("pending", "approved"):
        return {"approval_id": st["approval_id"], "status": st["status"], "created": False}
    try:
        req = c.workflow.create_request(record_type, record_id, user.username, title=title,
                                        reason=reason)
    except c.ComplianceError as exc:
        raise TpvError(f"{exc.code}: {exc.message}") from exc
    return {"approval_id": req.id, "status": req.status, "created": True}


def audit_event(action: str, object_type: str, object_id: str, *, user: Any = None,
                after_hash: str | None = None, reason: str | None = None) -> None:
    c = compliance()
    actor, role = (user.username, user.role) if user is not None else (SYSTEM_ACTOR, "admin")
    c.audit.append(actor, role, action, object_type, object_id, None, after_hash, reason)

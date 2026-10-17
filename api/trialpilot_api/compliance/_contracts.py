"""The ONE import point for the shared contract (MASTER §5) inside the compliance package.

`contracts/READY` exists, so this re-exports A1's `trialpilot_contracts` package directly.
"""

from __future__ import annotations

from trialpilot_contracts.models import ApprovalRequest, AuditEntry, Role, Signature

ROLES: tuple[str, ...] = ("author", "reviewer", "qa", "admin", "viewer")
MEANINGS: tuple[str, ...] = ("authored", "reviewed", "approved", "executed", "verified")
APPROVAL_RECORD_TYPES: tuple[str, ...] = (
    "scenario",
    "test_protocol",
    "validation_report",
    "change_record",
)

__all__ = [
    "APPROVAL_RECORD_TYPES",
    "MEANINGS",
    "ROLES",
    "ApprovalRequest",
    "AuditEntry",
    "Role",
    "Signature",
]

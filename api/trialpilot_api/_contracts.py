"""The ONE import point for the shared contract (MASTER §5) inside trialpilot_api.

`contracts/READY` exists, so this re-exports A1's `trialpilot_contracts` package.
"""

from trialpilot_contracts.models import *  # noqa: F403
from trialpilot_contracts.models import (  # explicit names for type checkers and readers
    Alert,
    ApprovalRequest,
    AuditEntry,
    EffectEstimate,
    EventType,
    Intervention,
    Levers,
    MetricRange,
    ModuleBreakdown,
    OpsEvent,
    Parameter,
    Procedure,
    ProvenanceItem,
    Role,
    ScenarioResult,
    Signature,
    Site,
    TrialDesign,
    Visit,
)

ROLES: tuple[str, ...] = ("author", "reviewer", "qa", "admin", "viewer")

__all__ = [
    "Alert", "ApprovalRequest", "AuditEntry", "EffectEstimate", "EventType", "Intervention",
    "Levers", "MetricRange", "ModuleBreakdown", "OpsEvent", "Parameter", "Procedure",
    "ProvenanceItem", "Role", "ROLES", "ScenarioResult", "Signature", "Site", "TrialDesign",
    "Visit",
]

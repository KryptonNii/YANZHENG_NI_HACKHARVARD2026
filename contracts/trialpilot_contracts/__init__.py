"""TrialPilot shared contracts. Import models from here: `from trialpilot_contracts import TrialDesign`."""

from .constants import (
    ALERT_IMPACT_KEYS,
    CARBON_MODULES,
    EXCLUDED_BY_DEFAULT_MODULES,
    EXTENSION_MODULES,
)
from .models import (
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
from .params import ParamValidationError, load_params, param_set_version, validate_parameter

__all__ = [
    # models (MASTER §5)
    "MetricRange",
    "ProvenanceItem",
    "Parameter",
    "Site",
    "Procedure",
    "Visit",
    "TrialDesign",
    "Levers",
    "ModuleBreakdown",
    "ScenarioResult",
    "EventType",
    "OpsEvent",
    "Alert",
    "Intervention",
    "EffectEstimate",
    "Role",
    "AuditEntry",
    "Signature",
    "ApprovalRequest",
    # constants (MASTER §6)
    "CARBON_MODULES",
    "EXTENSION_MODULES",
    "EXCLUDED_BY_DEFAULT_MODULES",
    "ALERT_IMPACT_KEYS",
    # parameter library
    "load_params",
    "param_set_version",
    "validate_parameter",
    "ParamValidationError",
]

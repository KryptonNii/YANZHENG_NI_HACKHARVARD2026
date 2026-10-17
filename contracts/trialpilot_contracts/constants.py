"""Shared constants that complement the models (MASTER §6). Exported to TypeScript by gen.py."""

from __future__ import annotations

# Low Carbon Clinical Trials Group 10-module framework (Griffiths, Fox, Williamson,
# BMJ Open 2024, https://bmjopen.bmj.com/content/14/1/e075755) + TrialPilot extension modules.
# Use these exact ids in ModuleBreakdown.module.
CARBON_MODULES: tuple[str, ...] = (
    "setup",
    "trial_management",
    "meetings_travel",
    "intervention",
    "data_collection",
    "supplies_equipment",
    "patient_assessments",
    "samples",
    "laboratory",
    "closeout",
    "drug_supply",
)

# Modules that go beyond the published method and must be flagged as such in the UI.
EXTENSION_MODULES: tuple[str, ...] = ("drug_supply",)

# Modules excluded from totals by default (MASTER §6: `intervention` excluded; see `drug_supply`).
EXCLUDED_BY_DEFAULT_MODULES: tuple[str, ...] = ("intervention",)

# Allowed keys of Alert.est_impact (MASTER §5 comment).
ALERT_IMPACT_KEYS: tuple[str, ...] = ("cost_usd", "co2e_kg", "delay_days", "site_staff_hours")

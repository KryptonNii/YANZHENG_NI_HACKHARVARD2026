# Shared contract — §5 of the brief, verbatim. Source of truth for every module.
# Only A1 edits this file; others propose changes in handoffs/<agent>_CONTRACT_CHANGES.md.
# After any edit run `uv run --project contracts python contracts/gen.py` and commit schema/ + web/src/contracts.ts.
from __future__ import annotations
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

# ---------- Ranges & provenance ----------
class MetricRange(BaseModel):
    p10: float; p50: float; p90: float
    unit: Literal["usd", "hours", "kg_co2e", "months", "patients", "percent", "kits"]

class ProvenanceItem(BaseModel):
    formula_id: str                 # e.g. "carbon.patient_travel.v1"
    description: str                # plain English: "patients × visits × round-trip km × factor"
    inputs: dict[str, float | str]  # resolved input values
    parameter_ids: list[str]        # ids in the parameter library
    assumptions: list[str] = []     # human-readable assumptions used

# ---------- Parameter library ----------
class Parameter(BaseModel):
    id: str                          # "ef.travel.car.average_km"
    label: str
    value_low: float; value_mid: float; value_high: float
    unit: str                        # "kg_co2e/km", "usd/visit", ...
    source_title: Optional[str] = None
    source_url: Optional[str] = None
    source_year: Optional[int] = None
    assumption: bool = False         # True if not directly from a source
    rationale: Optional[str] = None  # required when assumption=True
    version: int = 1
    region: Optional[str] = None     # ISO country or "global"

# ---------- Trial design ----------
class Site(BaseModel):
    id: str; name: str; city: Optional[str] = None; country: str
    lat: Optional[float] = None; lon: Optional[float] = None
    expected_enrollment: Optional[float] = None

class Procedure(BaseModel):
    code: str                        # "blood_draw", "ecg", "mri", "pk_sample", ...
    label: str
    site_minutes: Optional[float] = None
    ships_sample: bool = False
    sample_temp: Optional[Literal["ambient", "refrigerated", "frozen_-20", "frozen_-80"]] = None

class Visit(BaseModel):
    number: int; label: str; week: float
    procedures: list[Procedure] = []
    can_be_remote: bool = False      # decided by humans, default False

class TrialDesign(BaseModel):
    id: str
    source: Literal["ctgov", "protocol_pdf", "manual", "published_paper", "fixture"]
    registry_id: Optional[str] = None          # "NCT01234567" or "ISRCTN..."
    title: str
    phase: Optional[str] = None
    conditions: list[str] = []
    enrollment_target: int
    duration_months: float
    sites: list[Site]
    visits: list[Visit]
    drug_type: Literal["small_molecule", "biologic", "device", "none", "unknown"] = "unknown"
    missing_fields: list[str] = []             # what we could not get and therefore assumed

class Levers(BaseModel):
    remote_monitoring_share: float = 0.0       # 0..1 of monitoring visits done remotely
    home_visit_numbers: list[int] = []         # visit numbers moved to home nursing
    remote_visit_numbers: list[int] = []       # visit numbers moved to telehealth
    local_lab_share: float = 0.0               # 0..1 of samples analysed locally
    drug_supply_strategy: Literal["upfront", "on_demand"] = "upfront"
    removed_procedures: list[str] = []         # procedure codes removed from all visits
    excluded_site_ids: list[str] = []

class ModuleBreakdown(BaseModel):
    module: str                       # see §6 module list
    cost_usd: MetricRange
    co2e_kg: MetricRange
    provenance: list[ProvenanceItem]

class ScenarioResult(BaseModel):
    design_id: str
    levers: Levers
    cost_usd: MetricRange
    site_staff_hours: MetricRange
    patient_travel_hours: MetricRange
    co2e_kg: MetricRange
    duration_months: MetricRange       # from forecast
    drug_waste_share: MetricRange      # percent
    modules: list[ModuleBreakdown]
    warnings: list[str] = []
    parameter_set_version: str
    computed_at: datetime

# ---------- Operations (command center) ----------
EventType = Literal[
  "visit_completed", "visit_missed", "patient_enrolled", "patient_withdrawn",
  "query_opened", "query_closed", "monitoring_trip", "sample_shipment",
  "drug_shipment", "drug_dispensed", "drug_expired", "vendor_milestone", "budget_spend"]

class OpsEvent(BaseModel):
    id: str; trial_id: str; site_id: Optional[str]
    type: EventType
    occurred_at: datetime
    payload: dict
    source_system: Literal["EDC", "CTMS", "IRT", "TRAVEL", "COURIER", "FINANCE", "VENDOR"]
    simulated: bool = True

class Alert(BaseModel):
    id: str; trial_id: str; site_id: Optional[str]
    kind: Literal["enrollment_lag", "query_backlog", "drug_overstock", "drug_shortfall",
                  "costly_shipping_mode", "monitoring_inefficiency", "milestone_at_risk", "vendor_delay"]
    severity: Literal["info", "warning", "critical"]
    detected_at: datetime
    summary: str
    est_impact: dict[str, MetricRange]   # keys: cost_usd, co2e_kg, delay_days, site_staff_hours
    recommended_actions: list[str]
    status: Literal["open", "acknowledged", "action_planned", "resolved", "dismissed"]

class Intervention(BaseModel):
    id: str; trial_id: str; alert_id: Optional[str]
    action: str; owner: str; due_date: datetime
    target_site_ids: list[str]
    metric: str                           # e.g. "enrollment_rate_per_month"
    started_at: Optional[datetime] = None
    status: Literal["planned", "in_progress", "done"]

class EffectEstimate(BaseModel):
    intervention_id: str
    method: Literal["diff_in_diff"]
    effect: MetricRange                   # change in metric attributable to intervention
    treated_change: float; control_change: float
    verdict: Literal["likely_worked", "inconclusive", "likely_coincidence", "no_effect"]
    explanation: str

# ---------- Compliance ----------
Role = Literal["author", "reviewer", "qa", "admin", "viewer"]

class AuditEntry(BaseModel):
    seq: int; at: datetime; actor: str; role: Role
    action: str                            # "scenario.create", "approval.sign", ...
    object_type: str; object_id: str
    before_hash: Optional[str]; after_hash: Optional[str]
    reason: Optional[str]
    prev_entry_hash: str; entry_hash: str  # sha256 chain

class Signature(BaseModel):
    id: str; signer: str; role: Role
    meaning: Literal["authored", "reviewed", "approved", "executed", "verified"]
    signed_at: datetime
    record_type: str; record_id: str; record_hash: str

class ApprovalRequest(BaseModel):
    id: str; record_type: Literal["scenario", "test_protocol", "validation_report", "change_record"]
    record_id: str; author: str
    required_meanings: list[str]           # e.g. ["reviewed", "approved"]
    status: Literal["pending", "approved", "rejected"]
    signatures: list[Signature] = []

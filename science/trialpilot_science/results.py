"""Shape of science/out/results.json (served by A5 at GET /api/science/results, shown by A8 at /science).

`python -m science.reproduce` also writes science/out/results.schema.json from these models.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CheckId = Literal["method", "corrected", "library", "engine_library", "engine_paper_factors"]
RowStatus = Literal["match", "close", "gap", "not_reported", "unavailable"]

MATCH_PCT = 1.0   # |difference| <= 1 %  -> "match"
CLOSE_PCT = 10.0  # |difference| <= 10 % -> "close"; above -> "gap" (always explained)

MODULE_LABELS: dict[str, str] = {
    "setup": "Trial set-up",
    "trial_management": "Trial management (CTU emissions)",
    "meetings_travel": "Meetings and travel",
    "intervention": "Intervention (distribution only)",
    "data_collection": "Data collection and exchange",
    "supplies_equipment": "Supplies and equipment",
    "patient_assessments": "Patient assessments (incl. patient travel)",
    "samples": "Samples",
    "laboratory": "Laboratory",
    "closeout": "Close-out and archiving",
    "drug_supply": "Drug supply (TrialPilot extension, not in the paper)",
}


class Range(BaseModel):
    p10: float
    p50: float
    p90: float
    unit: Literal["kg_co2e"] = "kg_co2e"


class ModuleRow(BaseModel):
    module: str = Field(description="§6 module id, or 'total'")
    label: str
    published_kg: float | None = Field(description="Value printed in the paper's summary table")
    ours: Range | None = Field(description="TrialPilot's value; P10 = P50 = P90 for the deterministic checks")
    diff_pct: float | None = Field(description="(ours.p50 - published) / published x 100")
    published_within_range: bool | None = Field(description="published value inside [P10, P90]")
    status: RowStatus
    explanation: str | None = Field(description="Plain English; always present when status is 'gap'")


class LineChange(BaseModel):
    line_id: str
    module: str
    item: str
    paper_factor: float
    paper_kg: float
    library_factor_p50: float | None
    library_kg: Range | None
    parameter_ids: list[str]
    kind: Literal["independent", "same_source", "paper_factor_kept"]
    note: str


class Check(BaseModel):
    id: CheckId
    title: str
    description: str
    available: bool
    unavailable_reason: str | None = None
    total: ModuleRow | None
    modules: list[ModuleRow]
    notes: list[str] = []
    line_changes: list[LineChange] = []


class FindingOut(BaseModel):
    id: str
    severity: Literal["large", "medium", "info"]
    summary: str
    detail: str
    lines: list[str]
    effect_kg: float = Field(description="corrected minus as-published, kg CO2e (0 for info-only findings)")


class DesignInputOut(BaseModel):
    field: str
    value: str
    origin: Literal["paper", "assumption"]
    ref: str


class PublishedFigures(BaseModel):
    total_kg: float
    total_main_text_kg: float
    modules: dict[str, float]


class TrialOut(BaseModel):
    id: str
    name: str
    registry_id: str
    title: str
    phase: str
    patients: int
    sites: int
    countries: list[str]
    duration_years: float
    published: PublishedFigures
    source: str
    checks: list[Check]
    findings: list[FindingOut]
    design_inputs: list[DesignInputOut]
    summary: list[str] = Field(description="Two sentences on match quality, for the HANDOFF and the UI")


class BandTrial(BaseModel):
    design_id: str
    title: str
    registry_id: str | None
    available: bool
    reason: str | None = None
    total_t: Range | None = Field(default=None, description="tonnes CO2e (unit field says kg_co2e x 1000)")
    within_band: bool | None = None


class IndustryBand(BaseModel):
    low_t: float
    high_t: float
    trials_t: list[float]
    source: str
    note: str
    demo_trials: list[BandTrial]


class EngineInfo(BaseModel):
    available: bool
    reason: str | None = None


class ScienceResults(BaseModel):
    schema_version: Literal[1] = 1
    title: str
    simulated: Literal[False] = False
    data_label: str
    paper: dict[str, str]
    parameter_set_version: str
    seed: int
    draws: int
    thresholds_pct: dict[str, float]
    engine: EngineInfo
    trials: list[TrialOut]
    industry_band: IndustryBand
    how_to_reproduce: str

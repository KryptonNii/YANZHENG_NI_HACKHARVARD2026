"""Peer Mirror responses, deliberately separate from the shared contracts."""

from typing import Literal

from pydantic import BaseModel, Field

Metric = Literal[
    "primary_outcomes", "total_outcomes", "inclusion_criteria", "exclusion_criteria",
    "eligibility_criteria", "countries", "sites", "enrollment_target",
]


class RegistryCounts(BaseModel):
    primary_outcomes: int | None = None
    total_outcomes: int | None = None
    inclusion_criteria: int | None = None
    exclusion_criteria: int | None = None
    eligibility_criteria: int | None = None
    countries: int | None = None
    sites: int | None = None
    enrollment_target: int | None = None


class CohortRecord(BaseModel):
    registry_id: str
    source_file: str
    source_sha256: str
    phase: str | None
    condition_group: str | None
    cohort_n: int = 0
    counts: RegistryCounts
    enrollment_reported: int | None
    enrollment_type: str | None


class PeerRow(BaseModel):
    metric: Metric
    label: str
    own_count: int | None
    cohort_n: int
    available_n: int
    phase: str | None
    condition_group: str | None
    source_file: str | None
    peer_source_files: list[str]
    status: Literal["ok", "insufficient_peers", "not_reported", "record_not_cached"]
    peer_median: float | None
    percentile: float | None = Field(default=None, ge=0, le=100)
    comparison: Literal["more", "fewer", "same"] | None
    question: str
    note: str


class EstimateRange(BaseModel):
    p10: float | None
    p50: float | None
    p90: float | None
    unit: Literal["usd", "hours"]


class CostMetrics(BaseModel):
    cost_usd: EstimateRange
    site_staff_hours: EstimateRange


class ProcedureOption(BaseModel):
    code: str
    labels: list[str]
    occurrences: int
    visit_numbers: list[int]


class CostComparison(BaseModel):
    design_id: str
    design_version: int
    design_hash: str
    removed_procedures: list[str]
    baseline: CostMetrics
    counterfactual: CostMetrics
    delta: CostMetrics
    delta_method: str
    parameter_set_version: str
    seed: int
    draws: int
    warnings: list[str]


class PeerMirrorResponse(BaseModel):
    design_id: str
    design_version: int
    design_hash: str
    registry_id: str | None
    phase: str | None
    condition_group: str | None
    cohort_n: int
    source_file: str | None
    peer_source_files: list[str]
    own_counts: RegistryCounts
    enrollment_reported: int | None
    enrollment_type: str | None
    rows: list[PeerRow]
    methods: dict[str, str]
    interpretation: str
    available_procedures: list[ProcedureOption]
    cost_comparison: CostComparison | None
    cost_reason: str | None

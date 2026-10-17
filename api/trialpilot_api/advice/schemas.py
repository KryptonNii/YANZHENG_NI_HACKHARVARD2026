"""Advice response types stay local; the shared trial contracts are unchanged."""

from typing import Literal

from pydantic import BaseModel

from .._contracts import Levers, MetricRange

LeverValue = float | str | list[int] | list[str]
EndpointRole = Literal["supports_primary", "supports_secondary", "not_linked", "unknown"]
CandidateKind = Literal["lever", "procedure_removal"]


class AdviceMetrics(BaseModel):
    cost_usd: MetricRange
    site_staff_hours: MetricRange
    duration_months: MetricRange


class ProcedureRef(BaseModel):
    code: str
    label: str
    endpoint_roles: list[Literal["not_linked"]] = ["not_linked"]


class Recommendation(BaseModel):
    id: str
    label: str
    kind: CandidateKind = "lever"
    levers: dict[str, LeverValue]
    delta: AdviceMetrics
    reason: str
    stockout_probability: float | None
    procedure: ProcedureRef | None = None


class RejectedCandidate(BaseModel):
    id: str
    label: str
    kind: CandidateKind = "lever"
    levers: dict[str, LeverValue]
    reason: str
    delta: AdviceMetrics | None = None
    procedure: ProcedureRef | None = None


class StressScenario(BaseModel):
    id: Literal["slower_enrollment"] = "slower_enrollment"
    label: str
    tag: Literal["assumption"] = "assumption"
    levers: dict[str, LeverValue]
    delta: AdviceMetrics | None
    stockout_probability: float | None
    reason: str


class AdvicePolicy(BaseModel):
    max_duration_increase_months: float = 0.0
    max_stockout_probability: float
    max_recommendations: int
    note: str


class BlockedProcedure(BaseModel):
    code: str
    endpoint_roles: list[EndpointRole]
    reason: str


class AdviceResponse(BaseModel):
    design_id: str
    design_version: int
    design_hash: str
    parameter_set_version: str
    seed: int
    draws: int
    scenario_draws: int
    sampling_note: str
    delta_method: str
    baseline: AdviceMetrics
    current_levers: Levers
    policy: AdvicePolicy
    recommendations: list[Recommendation]
    rejected: list[RejectedCandidate]
    stress_scenarios: list[StressScenario]
    blocked: list[BlockedProcedure]
    warnings: list[str]

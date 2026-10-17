"""Gate each candidate against the current selection once, then rank the feasible ones."""

from dataclasses import dataclass
from math import isfinite

from .._contracts import Levers, Parameter, ScenarioResult, TrialDesign
from ..engine_adapter import EngineAdapter
from ..errors import ApiError
from ..routes_scenarios import validate_levers
from .candidates import NON_DRUG_TYPES, Candidate, slower_enrollment
from .sampling import DRAWS, SEED
from .schemas import (
    AdviceMetrics,
    AdvicePolicy,
    Recommendation,
    RejectedCandidate,
    StressScenario,
)

MAX_RECOMMENDATIONS = 3
RANKED_BELOW = (f"Met the model constraints but ranked below the top {MAX_RECOMMENDATIONS} by "
                "cost P50 change relative to the current selection.")
STRESS_AT_FLOOR = ("Enrollment is already at the model minimum, so no slower-enrollment stress "
                   "scenario was computed.")
STRESS_NO_FORECAST = ("Database-lock forecast unavailable for this scenario, so no change is "
                      "reported.")


def advice_policy(params: dict[str, Parameter]) -> AdvicePolicy:
    threshold = params.get("supply.stockout_warning_threshold")
    value = threshold.value_mid if threshold is not None else 0.05
    if not isfinite(value) or not 0 <= value <= 1:
        value = 0.05
    return AdvicePolicy(
        max_stockout_probability=value, max_recommendations=MAX_RECOMMENDATIONS,
        note="Reviewable model screening assumptions, not a clinical guarantee. A candidate "
             "needs a negative cost P50 delta relative to your current selection, no increase in "
             "duration P50 (0 months tolerance), and, for drug designs, a known stockout "
             "probability at or below the parameter-library warning threshold (0.05 fallback; "
             "not applicable to none/device designs). A reviewed visit schedule and "
             "database-lock forecasts are required. Procedures that support a primary or "
             "secondary endpoint, or whose linkage is unknown, are never recommended for removal. "
             "A not_linked procedure may be screened alone as a removal candidate; that is not "
             "clinical approval. Added countries are assumed sites, not registry sites. Slower "
             "enrollment appears only as an assumption stress scenario.",
    )


@dataclass(frozen=True)
class Screen:
    """Everything shared by the comparisons against one current selection."""

    design: TrialDesign
    engine: EngineAdapter
    params: dict[str, Parameter]
    parameter_version: str
    current: Levers
    baseline: ScenarioResult
    policy: AdvicePolicy


def has_lock_forecast(result: ScenarioResult) -> bool:
    lock = result.forecast.milestone_dates.get("database_lock") if result.forecast else None
    return lock is not None and lock.p50 is not None


def global_refusal(design: TrialDesign, baseline: ScenarioResult) -> RejectedCandidate | None:
    if (not design.visits or not any(visit.procedures for visit in design.visits)
            or "visits" in design.missing_fields):
        return RejectedCandidate(
            id="reviewed_schedule_required", label="Review visit schedule", levers={},
            reason="Reviewed visit schedule required: the schedule is still missing or assumed.")
    if not has_lock_forecast(baseline):
        return RejectedCandidate(
            id="forecast_unavailable", label="Forecast required", levers={},
            reason="Current-selection database-lock forecast unavailable; planned duration is "
                   "not a forecast.")
    return None


def measure(screen: Screen, levers: Levers) -> tuple[AdviceMetrics, ScenarioResult, list[str]]:
    """Paired deltas against the current selection, plus the candidate's own result."""
    result = screen.engine.compute(screen.design, levers, screen.params,
                                   screen.parameter_version, SEED, DRAWS).result
    delta, warnings = screen.engine.compare(screen.design, screen.current, levers, screen.params,
                                            seed=SEED, draws=DRAWS)
    return AdviceMetrics.model_validate(delta), result, [*result.warnings, *warnings]


def stockout(screen: Screen, result: ScenarioResult) -> float | None:
    if screen.design.drug_type in NON_DRUG_TYPES or result.supply is None:
        return None
    return result.supply.stockout_probability


def gate_failures(screen: Screen, delta: AdviceMetrics, result: ScenarioResult) -> list[str]:
    policy, reasons = screen.policy, []
    if not has_lock_forecast(screen.baseline) or not has_lock_forecast(result):
        reasons.append("database-lock forecast unavailable; planned duration is not a forecast")
    if delta.cost_usd.p50 is None:
        reasons.append("cost delta is unknown")
    elif delta.cost_usd.p50 >= 0:
        reasons.append("cost P50 does not improve on the current selection")
    if delta.duration_months.p50 is None:
        reasons.append("duration delta is unknown")
    elif delta.duration_months.p50 > policy.max_duration_increase_months:
        reasons.append("duration P50 increases beyond the 0-month tolerance")
    if screen.design.drug_type not in NON_DRUG_TYPES:
        risk = stockout(screen, result)
        if risk is None or not isfinite(risk):
            reasons.append("drug stockout probability is unknown")
        elif risk > policy.max_stockout_probability:
            reasons.append(f"drug stockout probability {risk:.3g} exceeds the "
                           f"{policy.max_stockout_probability:.3g} screening threshold")
    return reasons


def evaluate(
    screen: Screen, candidate: Candidate,
) -> tuple[Recommendation | RejectedCandidate, list[str]]:
    common = {"id": candidate.id, "label": candidate.label, "kind": candidate.kind,
              "levers": candidate.patch, "procedure": candidate.procedure}
    try:
        warnings = validate_levers(screen.design, candidate.levers)
    except ApiError as exc:
        if exc.status_code != 422:
            raise
        return RejectedCandidate(**common, reason=f"Candidate cannot be applied: {exc.message}"), []
    delta, result, engine_warnings = measure(screen, candidate.levers)
    warnings += engine_warnings
    reasons = gate_failures(screen, delta, result)
    if reasons:
        reason = "Failed the model constraints: " + "; ".join(reasons) + "."
        return RejectedCandidate(**common, delta=delta, reason=reason), warnings
    return Recommendation(**common, delta=delta, reason=candidate.reason,
                          stockout_probability=stockout(screen, result)), warnings


def rank_candidates(
    screen: Screen, candidates: list[Candidate],
) -> tuple[list[Recommendation], list[RejectedCandidate], list[str]]:
    feasible: list[Recommendation] = []
    rejected: list[RejectedCandidate] = []
    warnings: list[str] = []
    for candidate in candidates:
        outcome, outcome_warnings = evaluate(screen, candidate)
        warnings += outcome_warnings
        if isinstance(outcome, Recommendation):
            feasible.append(outcome)
        else:
            rejected.append(outcome)
    feasible.sort(key=lambda item: (
        item.delta.cost_usd.p50,
        item.delta.site_staff_hours.p50
        if item.delta.site_staff_hours.p50 is not None else float("inf"),
        item.id,
    ))
    top = screen.policy.max_recommendations
    rejected += [RejectedCandidate(
        id=item.id, label=item.label, kind=item.kind, levers=item.levers, delta=item.delta,
        procedure=item.procedure, reason=RANKED_BELOW,
    ) for item in feasible[top:]]
    return feasible[:top], rejected, warnings


def evaluate_stress(screen: Screen) -> tuple[list[StressScenario], list[str]]:
    """Report the slower-enrollment assumption; it is never gated into recommendations."""
    stress = slower_enrollment(screen.current)
    if stress is None:
        return [], [STRESS_AT_FLOOR]
    delta, result, warnings = measure(screen, stress.levers)
    forecast = has_lock_forecast(screen.baseline) and has_lock_forecast(result)
    return [StressScenario(
        label=stress.label, levers=stress.patch, delta=delta if forecast else None,
        stockout_probability=stockout(screen, result),
        reason=stress.reason if forecast else f"{stress.reason} {STRESS_NO_FORECAST}",
    )], warnings

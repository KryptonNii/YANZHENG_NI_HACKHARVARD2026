"""Read-only advice for an explicitly pinned stored design."""

from fastapi import APIRouter, Depends, Query, Response
from pydantic import ValidationError
from sqlmodel import Session

from .._contracts import Levers
from ..db import get_session
from ..deps import services
from ..errors import ApiError
from ..routes_designs import load_design
from ..routes_scenarios import (
    LeversIn,
    _missing_field_warnings,
    _params_snapshot,
    validate_levers,
)
from ..services import Services
from .candidates import build_candidates
from .ranking import Screen, advice_policy, evaluate_stress, global_refusal, rank_candidates
from .sampling import DELTA_METHOD, DRAWS, SEED, sampling_note
from .schemas import AdviceMetrics, AdviceResponse

router = APIRouter(prefix="/api/scenarios", tags=["advice"])


@router.get("/advice", response_model=AdviceResponse)
def get_advice(
    response: Response,
    design_id: str = Query(min_length=1),
    design_version: int | None = Query(default=None, ge=1),
    current_levers: str | None = Query(default=None),
    session: Session = Depends(get_session),
    svc: Services = Depends(services),
) -> AdviceResponse:
    if design_version is None:
        raise ApiError(422, "design_version_required",
                       "Send design_version: the saved design version on screen.",
                       {"design_id": design_id})
    stored, design = load_design(session, design_id, design_version)
    try:
        current = LeversIn.model_validate_json(current_levers) if current_levers is not None else Levers()
    except ValidationError as exc:
        raise ApiError(422, "invalid_current_levers", "current_levers must be a valid Levers JSON object.",
                       {"errors": exc.errors(include_context=False, include_input=False)}) from exc
    current = Levers.model_validate(current.model_dump())
    current_warnings = validate_levers(design, current)
    snap = _params_snapshot(svc)
    candidates, blocked, candidate_warnings = build_candidates(design, current)
    baseline = svc.engine.compute(design, current, snap.params, snap.version, SEED, DRAWS).result
    screen = Screen(design, svc.engine, snap.params, snap.version, current, baseline,
                    advice_policy(snap.params))
    refusal = global_refusal(design, baseline)
    if refusal is not None:  # no candidate or stress compute without a usable baseline
        recommendations, rejected, stress, advice_warnings = [], [refusal], [], [refusal.reason]
    else:
        recommendations, rejected, advice_warnings = rank_candidates(screen, candidates)
        stress, stress_warnings = evaluate_stress(screen)
        advice_warnings += stress_warnings
    response.headers["X-Design-Version"] = str(stored.version)
    response.headers["X-Parameter-Set-Version"] = snap.version
    response.headers["ETag"] = f'"{stored.design_hash}"'
    return AdviceResponse(
        design_id=design.id, design_version=stored.version, design_hash=stored.design_hash,
        parameter_set_version=snap.version, seed=SEED, draws=DRAWS,
        scenario_draws=svc.settings.default_draws,
        sampling_note=sampling_note(svc.settings.default_draws), delta_method=DELTA_METHOD,
        baseline=AdviceMetrics.model_validate(baseline, from_attributes=True),
        current_levers=current, policy=screen.policy,
        recommendations=recommendations, rejected=rejected, stress_scenarios=stress,
        blocked=blocked,
        warnings=list(dict.fromkeys([
            *baseline.warnings, *current_warnings, *candidate_warnings, *advice_warnings,
            *_missing_field_warnings(design, stored.version),
        ])),
    )

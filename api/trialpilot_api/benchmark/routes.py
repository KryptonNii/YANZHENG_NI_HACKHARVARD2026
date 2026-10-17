"""Read-only, version-pinned peer counts and existing-engine counterfactuals."""

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session

from .._contracts import Levers, TrialDesign
from ..db import get_session
from ..deps import services
from ..errors import ApiError
from ..routes_designs import load_design
from ..routes_scenarios import _params_snapshot, _seed_draws, validate_levers
from .cohort import (
    INTERPRETATION,
    METHODS,
    comparison_rows,
    condition_group,
    load_cohort,
    matching_peers,
    normalize_phase,
)
from .models import (
    CostComparison,
    CostMetrics,
    PeerMirrorResponse,
    ProcedureOption,
    RegistryCounts,
)

router = APIRouter(prefix="/api/designs", tags=["peers"])


def procedure_options(design: TrialDesign) -> list[ProcedureOption]:
    by_code: dict[str, ProcedureOption] = {}
    for visit in design.visits:
        for procedure in visit.procedures:
            option = by_code.setdefault(procedure.code, ProcedureOption(
                code=procedure.code, labels=[], occurrences=0, visit_numbers=[]))
            option.occurrences += 1
            if procedure.label not in option.labels:
                option.labels.append(procedure.label)
            if visit.number not in option.visit_numbers:
                option.visit_numbers.append(visit.number)
    return [by_code[code] for code in sorted(by_code)]


def cost_metrics(result: Any) -> CostMetrics:
    return CostMetrics.model_validate({
        key: getattr(result, key).model_dump() for key in ("cost_usd", "site_staff_hours")
    })


@router.get("/{design_id}/peers", response_model=PeerMirrorResponse)
def get_peers(
    design_id: str,
    response: Response,
    version: int | None = Query(default=None, ge=1),
    removed_procedures: list[str] = Query(default=[]),
    session: Session = Depends(get_session),
    svc: Any = Depends(services),
) -> PeerMirrorResponse:
    if version is None:
        raise ApiError(422, "design_version_required",
                       "Send version: the saved design version on screen.",
                       {"design_id": design_id})
    stored, design = load_design(session, design_id, version)
    records = load_cohort()
    registry_id = design.registry_id.strip().upper() if design.registry_id else None
    subject = next((record for record in records if record.registry_id == registry_id), None)
    phase, group = normalize_phase(design.phase), condition_group(design.conditions)
    peers = matching_peers(records, phase, group, registry_id)
    options = procedure_options(design)
    removed = sorted(set(removed_procedures))
    baseline_levers, counterfactual_levers = Levers(), Levers(removed_procedures=removed)
    validate_levers(design, counterfactual_levers)
    comparison = None
    reason = None
    if not design.visits or not options:
        reason = "No saved visit schedule with procedures is available; costs were not computed."
    elif "visits" in design.missing_fields:
        reason = ("The saved visit schedule is marked missing/assumed; costs were not computed. "
                  "A confirmed schedule with procedures is needed.")
    else:
        # One parameter snapshot, one immutable design, and common random numbers for both sides.
        snap = _params_snapshot(svc)
        seed, draws = _seed_draws(svc, None, None)
        baseline = svc.engine.compute(design, baseline_levers, snap.params, snap.version,
                                      seed, draws).result
        counterfactual = svc.engine.compute(design, counterfactual_levers, snap.params,
                                            snap.version, seed, draws).result
        delta, warnings = svc.engine.compare(
            design, baseline_levers, counterfactual_levers, snap.params, seed, draws)
        comparison = CostComparison(
            design_id=design.id, design_version=stored.version, design_hash=stored.design_hash,
            removed_procedures=removed, baseline=cost_metrics(baseline),
            counterfactual=cost_metrics(counterfactual),
            delta=CostMetrics.model_validate({key: delta[key].model_dump()
                                             for key in ("cost_usd", "site_staff_hours")}),
            delta_method="Existing engine per-draw counterfactual minus baseline, using common "
                         "random numbers; not subtraction of marginal percentiles. Selected codes "
                         "are removed from every visit. An empty selection compares identical levers.",
            parameter_set_version=snap.version, seed=seed, draws=draws,
            warnings=list(dict.fromkeys([*baseline.warnings, *counterfactual.warnings, *warnings])),
        )
        response.headers["X-Parameter-Set-Version"] = snap.version
    response.headers["X-Design-Version"] = str(stored.version)
    response.headers["ETag"] = f'"{stored.design_hash}"'
    return PeerMirrorResponse(
        design_id=design.id, design_version=stored.version, design_hash=stored.design_hash,
        registry_id=registry_id, phase=phase, condition_group=group, cohort_n=len(peers),
        source_file=subject.source_file if subject else None,
        peer_source_files=[peer.source_file for peer in peers],
        own_counts=subject.counts if subject else RegistryCounts(),
        enrollment_reported=subject.enrollment_reported if subject else None,
        enrollment_type=subject.enrollment_type if subject else None,
        rows=comparison_rows(subject, peers, phase, group), methods=METHODS,
        interpretation=INTERPRETATION, available_procedures=options,
        cost_comparison=comparison, cost_reason=reason,
    )

"""Offline, simulated operations API. State is isolated per app and trial."""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlmodel import Session
from sse_starlette import EventSourceResponse, ServerSentEvent

from ..deps import Identity, require_editor
from ..errors import ApiError
from ..routes_designs import load_design
from ..sse import SSEMessage, last_event_id_of
from . import actions, audit
from ._contracts import Levers, MetricRange, ProvenanceItem, ScenarioResult, TrialDesign
from .fixtures import DEMO_TRIAL_ID, load_demo_design
from .store import DEFAULT_HORIZON, DEFAULT_START_DAY, OpsError, TrialState

router = APIRouter(tags=["operations"])
_registry_lock = threading.RLock()


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ForecastBody(Input):
    months_to_full_enrollment: MetricRange
    duration_months: MetricRange
    milestone_dates: dict[str, MetricRange]
    enrollment_curve: list[tuple[float, float, float, float]] = Field(min_length=1, max_length=2000)
    patients_to_randomise: MetricRange | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance: list[ProvenanceItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered_curve(self):
        previous = -1.0
        for month, lo, mid, hi in self.enrollment_curve:
            if month <= previous or not 0 <= lo <= mid <= hi:
                raise ValueError("Forecast curve must have increasing months and ordered nonnegative bands")
            previous = month
        return self

    def to_engine(self, levers):
        from trialpilot_engine.forecast import ForecastResult

        return ForecastResult(**{name: getattr(self, name) for name in type(self).model_fields},
                              levers=levers)


class SimulateBody(Input):
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    speed: float = Field(default=0, ge=0, le=30)
    scenario: Literal["demo", "healthy"] = "demo"
    start_day: float = Field(default=DEFAULT_START_DAY, ge=0)
    horizon_days: int = Field(default=DEFAULT_HORIZON, ge=30, le=1500)
    design: TrialDesign | None = None
    scenario_result: ScenarioResult | None = None
    forecast_result: ForecastBody | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.start_day >= self.horizon_days:
            raise ValueError("start_day must be less than horizon_days")
        if self.design is not None and self.scenario_result is not None:
            if self.design.id != self.scenario_result.design_id:
                raise ValueError("scenario_result must belong to the supplied design")
        return self


class ClockBody(Input):
    advance_days: float = Field(gt=0, le=365)


class AlertPatch(Input):
    status: Literal["open", "acknowledged", "action_planned", "resolved", "dismissed"]
    reason: str | None = Field(default=None, max_length=2000)


class InterventionBody(Input):
    alert_id: str | None = None
    action: str = Field(min_length=1, max_length=2000)
    owner: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: AwareDatetime | None = None
    target_site_ids: list[str] = Field(default_factory=list, max_length=40)
    metric: str | None = None
    started_at: AwareDatetime | None = None
    status: Literal["planned", "in_progress", "done"] = "planned"
    reason: str | None = Field(default=None, max_length=2000)


class InterventionPatch(Input):
    action: str | None = Field(default=None, min_length=1, max_length=2000)
    owner: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: AwareDatetime | None = None
    target_site_ids: list[str] | None = Field(default=None, max_length=40)
    metric: str | None = None
    started_at: AwareDatetime | None = None
    status: Literal["planned", "in_progress", "done"] | None = None
    reason: str | None = Field(default=None, max_length=2000)


def registry(request: Request) -> dict[str, TrialState]:
    with _registry_lock:
        if not hasattr(request.app.state, "ops_trials"):
            request.app.state.ops_trials = {}
        return request.app.state.ops_trials


@contextmanager
def errors():
    try:
        yield
    except OpsError as exc:
        raise ApiError(exc.status, exc.code, exc.message, exc.details) from exc


def state(request: Request, trial_id: str) -> TrialState:
    with _registry_lock:
        st = registry(request).get(trial_id)
    if st is None:
        raise ApiError(404, "not_simulated", "Start the simulated feed with POST /simulate first.")
    with errors():
        st.tick()
    return st


@router.post("/{trial_id}/simulate")
def simulate(trial_id: str, body: SimulateBody, request: Request,
             ident: Identity = Depends(require_editor)):
    svc = request.app.state.services
    design = body.design
    if design is None:
        if trial_id == DEMO_TRIAL_ID:
            design = load_demo_design()
        else:
            with Session(svc.db_engine) as session:
                _, design = load_design(session, trial_id)
    if body.scenario_result and body.scenario_result.design_id != design.id:
        raise ApiError(422, "plan_design_mismatch", "The scenario result belongs to another design.")
    if design.enrollment_target <= 0 or design.duration_months <= 0 or not design.sites:
        raise ApiError(422, "invalid_design", "Operations needs a positive target, duration and sites.")
    if len({s.id for s in design.sites}) != len(design.sites):
        raise ApiError(422, "invalid_design", "Site ids must be unique.")
    if any(s.expected_enrollment is not None and s.expected_enrollment < 0 for s in design.sites):
        raise ApiError(422, "invalid_design", "Expected enrollment cannot be negative.")
    try:
        with audit.bound(svc.compliance.append):
            audit.append(actor=ident.user, role=ident.role, action="ops.simulate", object_type="ops_trial",
                         object_id=trial_id, after=body, reason="Regenerate a labelled simulated feed")
            st = TrialState(trial_id, design, body.scenario_result, body.seed, body.speed,
                            body.scenario, body.start_day, body.horizon_days,
                            audit_sink=svc.compliance.append,
                            forecast_result=body.forecast_result.to_engine(
                                body.scenario_result.levers if body.scenario_result else Levers())
                                if body.forecast_result else None)
    except ValueError as exc:
        raise ApiError(422, "invalid_simulation", str(exc)) from exc
    with _registry_lock:
        old = registry(request).get(trial_id)
        if old:
            old.replaced = True
        registry(request)[trial_id] = st
    return {**st.clock_info(), "event_count": st._visible_count(), "alerts": len(st.alerts),
            "data_label": "Simulated feed", "plan_notes": st.plan.notes}


@router.post("/{trial_id}/clock")
def clock(trial_id: str, body: ClockBody, request: Request,
          ident: Identity = Depends(require_editor)):
    with errors():
        return state(request, trial_id).advance(body.advance_days, ident.user, ident.role)


@router.get("/{trial_id}/clock")
def read_clock(trial_id: str, request: Request):
    return state(request, trial_id).clock_info()


@router.get("/{trial_id}/health")
def health(trial_id: str, request: Request):
    return state(request, trial_id).health()


@router.get("/{trial_id}/alerts")
def alerts(trial_id: str, request: Request, status: str | None = None):
    st = state(request, trial_id)
    return {"items": st.alert_list(status), "simulated": True}


@router.get("/{trial_id}/alerts/{alert_id}")
def alert_detail(trial_id: str, alert_id: str, request: Request):
    with errors():
        return state(request, trial_id).alert_detail(alert_id)


@router.post("/{trial_id}/alerts/{alert_id}")
@router.patch("/{trial_id}/alerts/{alert_id}")
def update_alert(trial_id: str, alert_id: str, body: AlertPatch, request: Request,
                 ident: Identity = Depends(require_editor)):
    with errors():
        return state(request, trial_id).set_alert_status(alert_id, body.status, ident.user,
                                                        ident.role, body.reason)


@router.get("/{trial_id}/interventions")
def interventions(trial_id: str, request: Request):
    st = state(request, trial_id)
    with st.lock:
        return {"items": list(st.interventions.values()), "simulated": True}


@router.get("/{trial_id}/interventions/{iv_id}")
def intervention(trial_id: str, iv_id: str, request: Request):
    st = state(request, trial_id)
    with st.lock:
        iv = st.interventions.get(iv_id)
        if iv is None:
            raise ApiError(404, "intervention_not_found", "No such intervention for this trial.")
        return iv


@router.post("/{trial_id}/interventions", status_code=201)
def create_intervention(trial_id: str, body: InterventionBody, request: Request,
                        ident: Identity = Depends(require_editor)):
    with errors():
        return state(request, trial_id).create_intervention(body.model_dump(exclude_none=True),
                                                            ident.user, ident.role)


@router.post("/{trial_id}/interventions/{iv_id}")
@router.patch("/{trial_id}/interventions/{iv_id}")
def update_intervention(trial_id: str, iv_id: str, body: InterventionPatch, request: Request,
                        ident: Identity = Depends(require_editor)):
    with errors():
        return state(request, trial_id).update_intervention(
            iv_id, body.model_dump(exclude_unset=True), ident.user, ident.role)


@router.delete("/{trial_id}/interventions/{iv_id}", status_code=204)
def delete_intervention(trial_id: str, iv_id: str, request: Request,
                        reason: str = Query(min_length=1, max_length=2000),
                        ident: Identity = Depends(require_editor)):
    with errors():
        state(request, trial_id).delete_intervention(iv_id, ident.user, ident.role, reason)
    return Response(status_code=204)


@router.get("/{trial_id}/effects")
def effects(trial_id: str, request: Request):
    return {"items": state(request, trial_id).effect_list(), "simulated": True}


@router.get("/{trial_id}/effects/{iv_id}")
def effect(trial_id: str, iv_id: str, request: Request):
    with errors():
        st = state(request, trial_id)
        return {**st.effect(iv_id).to_dict(st.plan), "simulated": True}


@router.get("/{trial_id}/events")
def events(trial_id: str, request: Request, limit: int = Query(default=50, ge=1, le=2000),
           since_day: float | None = Query(default=None, ge=0), site_id: str | None = None):
    items, total = state(request, trial_id).visible_events(since_day, limit, None, site_id)
    return {"items": list(reversed(items)), "total": total, "simulated": True}


@router.get("/{trial_id}/actions")
def action_catalog(trial_id: str):
    return {"items": actions.catalog(), "simulated": True}


async def stream_messages(st: TrialState, last_id: str | None):
    """A5 SSE messages from the complete run outbox, beyond the broker's bounded replay buffer."""
    seq = 0
    if last_id:
        run, _, number = last_id.rpartition(":")
        if run == st.run_id and number.isdigit():
            seq = min(int(number), st.last_seq)
    while True:
        if st.replaced:
            yield SSEMessage(seq + 1, f"{st.run_id}:{seq + 1}", "simulation_reset",
                             {"message": "Reload the simulation snapshot", "simulated": True})
            return
        await asyncio.to_thread(st.tick)
        messages = st.messages_after(seq)
        for number, kind, data in messages:
            seq = number
            yield SSEMessage(number, f"{st.run_id}:{number}", kind, data)
        if not messages:
            await asyncio.sleep(0.25)


@router.get("/{trial_id}/stream")
async def stream(trial_id: str, request: Request):
    st = await asyncio.to_thread(state, request, trial_id)
    last_id = last_event_id_of(request)
    if last_id:
        run, sep, number = last_id.rpartition(":")
        if not sep or not number.isdigit():
            raise ApiError(400, "invalid_event_id", "SSE ids have the form run_id:sequence.")
        if run != st.run_id:
            raise ApiError(409, "simulation_reset", "The simulation was reset; reload its snapshot.")
        if int(number) > st.last_seq:
            raise ApiError(409, "invalid_event_id", "SSE cursor is ahead of this simulation.")

    async def generate():
        yield ServerSentEvent(comment="connected", retry=3000)
        async for msg in stream_messages(st, last_id):
            if registry(request).get(trial_id) is not st:
                yield ServerSentEvent(event="simulation_reset", data="Reload the simulation snapshot")
                break
            if await request.is_disconnected():
                break
            yield msg.to_sse()

    return EventSourceResponse(generate(), ping=15,
                               headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

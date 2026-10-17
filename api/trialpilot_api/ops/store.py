"""In-memory command-center state per trial: simulated feed, clock, alerts, interventions, effects, outbox.

* The clock only moves forward. Detection runs at every weekly checkpoint crossed and at the new clock.
* One alert per (kind, scope); repeated findings update it; a problem that is no longer present resolves it.
* Creating/starting an intervention re-simulates the future with the simulator's response model; events
  before the clock are guaranteed unchanged (checked), so streamed event ids stay valid (replay-safe).
* Every mutation is audited through the trial's audit sink (ops.audit -> the app's compliance adapter).
* State is in memory (re-created deterministically by POST /simulate); see HANDOFF for persistence notes.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import Any

import numpy as np

from . import actions, audit, expectation
from ._contracts import Alert, EffectEstimate, Intervention, OpsEvent, ScenarioResult, TrialDesign
from .detect import Detector, Finding
from .effects import EffectDetails, direction_for, estimate_effect
from .health import compute_health
from .metrics import Feed
from .params import load_ops_params
from .plan import OpsPlan, build_plan
from .simulator import SimEvent, SimIntervention, event_uuid, simulate

DEFAULT_SEED = 42
DEFAULT_START_DAY = 406  # 2026-10-12: ~13.5 months into the simulated trial
DEFAULT_HORIZON = 600
MAX_ADVANCE_DAYS = 365
SIM_OWNER = "Simulated study team (scripted intervention)"
OPEN_STATES = ("open", "acknowledged", "action_planned")


def atomic(fn):
    """Keep the visible in-memory state unchanged if validation, audit or simulation fails."""
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        with self.lock, audit.bound(self.audit_sink):
            names = ("alerts", "alert_meta", "alert_by_key", "interventions", "iv_meta", "effects",
                     "_planted_done")
            saved = {name: deepcopy(getattr(self, name)) for name in names}
            saved.update({name: getattr(self, name) for name in
                          ("clock_day", "anchor", "sim", "events", "event_t", "feed", "detector")})
            seq = len(self.outbox)
            try:
                return fn(self, *args, **kwargs)
            except Exception:
                for name, value in saved.items():
                    setattr(self, name, value)
                del self.outbox[seq:]
                raise
    return wrapped


class OpsError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


@dataclass
class IvMeta:
    code: str
    alert_kind: str | None
    system: bool
    label: str | None = None
    expectation: dict | None = None  # prediction saved when the action was planned (never recomputed)
    exp_draws: dict | None = None  # its frozen sampling, used only for the follow-up comparison
    replan_flagged: bool = False  # the system already asked the user to re-plan this action


class TrialState:
    def __init__(self, trial_id: str, design: TrialDesign, scenario_result: ScenarioResult | None, seed: int,
                 speed: float, scenario: str, start_day: float, horizon_days: int,
                 *, audit_sink: Callable[..., Any], forecast_result=None):
        self.lock = threading.RLock()
        self.audit_sink = audit_sink
        self.trial_id, self.seed, self.scenario = trial_id, seed, scenario
        self.run_id = uuid.uuid4().hex[:12]
        self.params = load_ops_params(seed)
        self.plan: OpsPlan = build_plan(design, self.params, scenario_result, horizon_days,
                                        forecast_result=forecast_result)
        self.clock_day = 0.0
        self.speed = max(0.0, float(speed))
        self.anchor = (time.monotonic(), 0.0)
        self.alerts: dict[str, Alert] = {}
        self.alert_meta: dict[str, dict] = {}
        self.alert_by_key: dict[str, str] = {}
        self.interventions: dict[str, Intervention] = {}
        self.iv_meta: dict[str, IvMeta] = {}
        self.effects: dict[str, EffectDetails] = {}
        self.outbox: list[tuple[int, str, dict]] = []
        self._planted_done: set[str] = set()
        self.replaced = False
        self._regenerate()
        with audit.bound(self.audit_sink):
            self._advance_to(min(float(start_day), self.plan.horizon_days - 1), emit_events=False)
        self.anchor = (time.monotonic(), self.clock_day)

    # ------------------------------------------------------------------ simulation
    def _sim_interventions(self) -> list[SimIntervention]:
        out = []
        for iv in self.interventions.values():
            meta = self.iv_meta[iv.id]
            if meta.system or iv.started_at is None or iv.status == "planned":
                continue
            out.append(SimIntervention(iv.id, meta.code, list(iv.target_site_ids), self.plan.day_of(iv.started_at)))
        return out

    def _regenerate(self) -> None:
        old = getattr(self, "events", None)
        self.sim = simulate(self.plan, self.params, self.seed, self.scenario, self._sim_interventions())
        self.events: list[SimEvent] = self.sim.events
        self.event_t = np.array([e.t for e in self.events])
        self.feed = Feed(self.plan, self.events, self.params)
        self.detector = Detector(self.plan, self.feed, self.seed)
        if old is not None:  # replay safety: the visible past must not change
            n_old = int(np.searchsorted([e.t for e in old], self.clock_day, side="left"))
            n_new = int(np.searchsorted(self.event_t, self.clock_day, side="left"))
            if n_old != n_new or any(a.key != b.key or a.payload != b.payload
                                     for a, b in zip(old[:n_old], self.events[:n_new], strict=True)):
                raise OpsError(500, "replay_violation", "Re-simulation changed already visible events.")

    def to_ops_event(self, e: SimEvent) -> OpsEvent:
        return OpsEvent(id=event_uuid(self.trial_id, self.seed, self.scenario, e.key), trial_id=self.trial_id,
                        site_id=e.site_id, type=e.type,  # type: ignore[arg-type]
                        occurred_at=self.plan.date(e.t).replace(microsecond=0), payload=e.payload,
                        source_system=e.source, simulated=True)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ outbox
    def _emit(self, kind: str, data: dict) -> None:
        self.outbox.append((len(self.outbox) + 1, kind, data))

    def messages_after(self, seq: int, limit: int = 2000) -> list[tuple[int, str, dict]]:
        with self.lock:
            return self.outbox[seq: seq + limit]

    @property
    def last_seq(self) -> int:
        return len(self.outbox)

    # ------------------------------------------------------------------ clock
    @atomic
    def tick(self) -> None:
        """Auto-advance when a speed is set (simulated days per real second)."""
        if self.speed <= 0:
            return
        with self.lock:
            real0, day0 = self.anchor
            target = min(day0 + self.speed * (time.monotonic() - real0), self.plan.horizon_days - 1)
            if target - self.clock_day >= 1 / 24:
                self._advance_to(target)

    @atomic
    def advance(self, days: float, actor: str, role: str) -> dict:
        if not 0 < days <= MAX_ADVANCE_DAYS:
            raise OpsError(422, "invalid_advance", f"advance_days must be in (0, {MAX_ADVANCE_DAYS}].",
                           {"advance_days": days})
        with self.lock:
            end = self.plan.horizon_days - 1
            if self.clock_day >= end:
                raise OpsError(409, "end_of_simulation", "The simulated feed has reached its horizon.",
                               {"horizon_day": end})
            before = {"clock_day": self.clock_day, "seq": self.last_seq}
            target = min(self.clock_day + days, end)
            alerts_before = {k: (a.status, a.severity) for k, a in self.alerts.items()}
            n0 = self._visible_count()
            self._advance_to(target)
            self.anchor = (time.monotonic(), self.clock_day)
            new_alerts = [a for k, a in self.alerts.items() if k not in alerts_before]
            changed = [a for k, a in self.alerts.items() if k in alerts_before and alerts_before[k] != (
                a.status, a.severity)]
            audit.append(actor=actor, role=role, action="ops.clock.advance", object_type="ops_trial",
                         object_id=self.trial_id, before=before,
                         after={"clock_day": self.clock_day, "seq": self.last_seq},
                         reason=f"advance {days} simulated day(s)")
            return {**self.clock_info(), "new_events": self._visible_count() - n0,
                    "alerts_new": [a.model_dump(mode="json") for a in new_alerts],
                    "alerts_changed": [a.model_dump(mode="json") for a in changed]}

    def _visible_count(self) -> int:
        return int(np.searchsorted(self.event_t, self.clock_day, side="left"))

    def _advance_to(self, target: float, emit_events: bool = True) -> None:
        start = self.clock_day
        checkpoints = [float(c) for c in range(int(start // 7 + 1) * 7, int(target) + 1, 7)]
        if not checkpoints or checkpoints[-1] < target:
            checkpoints.append(float(target))
        prev = start
        for c in checkpoints:
            if emit_events:
                i0 = int(np.searchsorted(self.event_t, prev, side="left"))
                i1 = int(np.searchsorted(self.event_t, c, side="left"))
                for e in self.events[i0:i1]:
                    self._emit("ops_event", self.to_ops_event(e).model_dump(mode="json"))
            self.clock_day = c
            self._create_planted(c)
            self._apply_findings(self.detector.run(c), c, emit=emit_events)
            self._progress_interventions(c)
            prev = c
        self._refresh_effects(emit=emit_events)
        if emit_events:
            self._emit("clock", self.clock_info())

    def clock_info(self) -> dict:
        return {"trial_id": self.trial_id, "run_id": self.run_id, "clock_day": round(self.clock_day, 3),
                "now": self.plan.date(self.clock_day).isoformat(), "epoch": self.plan.epoch.isoformat(),
                "horizon_day": self.plan.horizon_days - 1, "speed_days_per_second": self.speed,
                "seed": self.seed, "scenario": self.scenario, "simulated": True}

    # ------------------------------------------------------------------ alerts
    def _alert_id(self, key: str, day: float) -> str:
        return event_uuid(self.trial_id, self.seed, self.scenario, f"alert:{key}:{int(day)}")

    def _apply_findings(self, findings: list[Finding], day: float, emit: bool = True) -> None:
        present: set[str] = set()
        for f in findings:
            key = f"{f.kind}:{f.scope}"
            present.add(key)
            aid = self.alert_by_key.get(key)
            cur = self.alerts.get(aid) if aid else None
            if cur is not None and cur.status == "dismissed":
                continue  # dismissed by a human: stay quiet for this key
            if cur is not None and cur.status in OPEN_STATES:
                upd = cur.model_copy(update={"severity": f.severity, "summary": f.summary, "est_impact": f.est_impact,
                                             "recommended_actions": f.recommended_actions})
                material = (upd.severity, upd.summary) != (cur.severity, cur.summary)
                self.alerts[cur.id] = upd
                self.alert_meta[cur.id].update(provenance=f.provenance, evidence=f.evidence, last_seen_day=day)
                if material and emit:
                    self._emit("alert_update", upd.model_dump(mode="json"))
                continue
            if not f.trigger:
                continue
            alert = Alert(id=self._alert_id(key, day), trial_id=self.trial_id, site_id=f.site_id,
                          kind=f.kind, severity=f.severity, detected_at=self.plan.date(day),  # type: ignore[arg-type]
                          summary=f.summary, est_impact=f.est_impact, recommended_actions=f.recommended_actions,
                          status="open")
            self.alerts[alert.id] = alert
            self.alert_by_key[key] = alert.id
            self.alert_meta[alert.id] = {"key": key, "scope": f.scope, "provenance": f.provenance,
                                         "evidence": f.evidence, "first_day": day, "last_seen_day": day,
                                         "history": [{"at": self.plan.date(day).isoformat(), "status": "open",
                                                      "actor": audit.SYSTEM_ACTOR}]}
            audit.append(actor=audit.SYSTEM_ACTOR, role="admin", action="ops.alert.raise", object_type="ops_alert",
                         object_id=alert.id, after=alert, reason="detection rule fired (simulated feed)")
            if emit:
                self._emit("alert_new", alert.model_dump(mode="json"))
        for aid, a in list(self.alerts.items()):
            key = self.alert_meta[aid]["key"]
            if a.status in OPEN_STATES and key not in present and self.alert_by_key.get(key) == aid:
                self._set_status(a, "resolved", audit.SYSTEM_ACTOR, "admin",
                                 "auto-resolved: the detection rule no longer finds the problem", day, emit)

    def _set_status(self, a: Alert, status: str, actor: str, role: str, reason: str | None, day: float,
                    emit: bool = True) -> Alert:
        upd = a.model_copy(update={"status": status})
        audit.append(actor=actor, role=role, action="ops.alert.status", object_type="ops_alert", object_id=a.id,
                     before=a, after=upd, reason=reason)
        self.alerts[a.id] = upd
        self.alert_meta[a.id]["history"].append({"at": self.plan.date(day).isoformat(), "status": status,
                                                 "actor": actor, "reason": reason})
        if emit:
            self._emit("alert_update", upd.model_dump(mode="json"))
        return upd

    @atomic
    def set_alert_status(self, alert_id: str, status: str, actor: str, role: str, reason: str | None) -> Alert:
        with self.lock:
            a = self.alerts.get(alert_id)
            if a is None:
                raise OpsError(404, "alert_not_found", f"No alert {alert_id} for trial {self.trial_id}.")
            if status not in ("open", "acknowledged", "action_planned", "resolved", "dismissed"):
                raise OpsError(422, "invalid_status", f"Unknown alert status {status!r}.")
            if status == a.status:
                raise OpsError(409, "status_unchanged", f"Alert is already {status}.")
            if status == "dismissed" and not (reason or "").strip():
                raise OpsError(422, "reason_required", "Dismissing an alert requires a reason (it is audited).")
            if status in OPEN_STATES and a.status in ("resolved", "dismissed"):
                cur = self.alert_by_key.get(self.alert_meta[a.id]["key"])
                if cur != a.id:
                    raise OpsError(409, "superseded", "A newer alert exists for the same problem.")
            return self._set_status(a, status, actor, role, reason, self.clock_day)

    # ------------------------------------------------------------------ interventions
    def _create_planted(self, day: float) -> None:
        for gt in self.sim.ground_truth.get("interventions", []):
            if gt["id"] in self._planted_done or gt["start_day"] > day:
                continue
            self._planted_done.add(gt["id"])
            kind = {"crf_retraining": "query_backlog", "activate_backup": "enrollment_lag"}.get(gt["code"])
            alert_id = None
            for sid in gt["target_site_ids"]:
                aid = self.alert_by_key.get(f"{kind}:{sid}") if kind else None
                if aid:
                    alert_id = aid
                    break
            start = self.plan.date(gt["start_day"])
            iv = Intervention(id=event_uuid(self.trial_id, self.seed, self.scenario, f"iv:{gt['id']}"),
                              trial_id=self.trial_id, alert_id=alert_id, action=gt["action"], owner=SIM_OWNER,
                              due_date=start + timedelta(days=28), target_site_ids=gt["target_site_ids"],
                              metric=gt["metric"], started_at=start, status="in_progress")
            self.interventions[iv.id] = iv
            self.iv_meta[iv.id] = IvMeta(gt["code"], kind, True, gt["id"])
            audit.append(actor="system:ops-simulator", role="admin", action="ops.intervention.create",
                         object_type="ops_intervention", object_id=iv.id, after=iv,
                         reason=f"scripted intervention {gt['id']} of the simulated scenario")

    def _progress_interventions(self, day: float) -> None:
        for iv in list(self.interventions.values()):
            if self.iv_meta[iv.id].system and iv.status == "in_progress" and self.plan.day_of(iv.due_date) <= day:
                self.interventions[iv.id] = iv.model_copy(update={"status": "done"})

    @atomic
    def create_intervention(self, body: dict, actor: str, role: str) -> Intervention:
        with self.lock:
            alert = None
            if body.get("alert_id"):
                alert = self.alerts.get(body["alert_id"])
                if alert is None:
                    raise OpsError(404, "alert_not_found", f"No alert {body['alert_id']} for this trial.")
            targets = list(body.get("target_site_ids") or ([alert.site_id] if alert and alert.site_id else []))
            known = {s.id for s in self.plan.sites}
            option = self._quantified_option(alert, actions.action_code(body["action"])) if alert else None
            if option is not None and option[0]["code"] == "activate_backup" and not any(
                    t in known and self.plan.site(t).backup for t in targets):
                targets = list(option[0]["target_site_ids"])  # the backup site that was predicted
            bad = [t for t in targets if t not in known]
            if not targets or bad:
                raise OpsError(422, "invalid_targets", "target_site_ids must list sites of this trial.",
                               {"unknown": bad})
            status = body.get("status") or "planned"
            started_at = body.get("started_at")
            if status != "planned" and started_at is None:
                started_at = self.plan.date(self.clock_day)
            self._check_start(started_at)
            metric = (body.get("metric") or (option[0]["metric"] if option is not None else "")
                      or actions.DEFAULT_METRIC.get(alert.kind if alert else "", ""))
            if not metric:
                raise OpsError(422, "metric_required", "metric is required when the intervention has no alert.")
            iv = Intervention(id=str(uuid.uuid4()), trial_id=self.trial_id, alert_id=alert.id if alert else None,
                              action=body["action"], owner=body.get("owner") or actor,
                              due_date=body.get("due_date") or self.plan.date(self.clock_day + 28),
                              target_site_ids=targets, metric=metric, started_at=started_at, status=status)
            self.interventions[iv.id] = iv
            self.iv_meta[iv.id] = IvMeta(actions.action_code(iv.action), alert.kind if alert else None, False)
            audit.append(actor=actor, role=role, action="ops.intervention.create", object_type="ops_intervention",
                         object_id=iv.id, after=iv, reason=body.get("reason"))
            self._attach_expectation(iv, actor, role)
            if alert is not None and alert.status in ("open", "acknowledged"):
                self._set_status(alert, "action_planned", actor, role, f"intervention {iv.id} planned",
                                 self.clock_day)
            self._after_iv_change(iv)
            return iv

    def _check_start(self, started_at: datetime | None) -> None:
        if started_at is None:
            return
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        if self.plan.day_of(started_at) < self.clock_day - 1e-6:
            raise OpsError(409, "started_at_before_clock",
                           "An intervention cannot start before the simulated clock (the past is already "
                           "streamed).", {"clock": self.plan.date(self.clock_day).isoformat()})

    @atomic
    def update_intervention(self, iv_id: str, patch: dict, actor: str, role: str) -> Intervention:
        with self.lock:
            iv = self.interventions.get(iv_id)
            if iv is None:
                raise OpsError(404, "intervention_not_found", f"No intervention {iv_id} for this trial.")
            if self.iv_meta[iv_id].system:
                raise OpsError(409, "scripted_intervention", "Scripted (simulated) interventions are read-only.")
            allowed = {"action", "owner", "due_date", "target_site_ids", "metric", "started_at", "status"}
            unknown = set(patch) - allowed - {"reason"}
            if unknown:
                raise OpsError(422, "unknown_fields", "Unknown fields in update.", {"fields": sorted(unknown)})
            upd = {k: v for k, v in patch.items() if k in allowed and v is not None}
            if iv.started_at is not None and "started_at" in upd and upd["started_at"] != iv.started_at:
                raise OpsError(409, "already_started", "started_at cannot change once the intervention started.")
            if iv.started_at is not None and ("target_site_ids" in upd or "action" in upd):
                raise OpsError(409, "already_started", "Targets and action are fixed once started.")
            if upd.get("status") in ("in_progress", "done") and iv.started_at is None and "started_at" not in upd:
                upd["started_at"] = self.plan.date(self.clock_day)
            if "started_at" in upd:
                self._check_start(upd["started_at"])
            new = Intervention.model_validate({**iv.model_dump(), **upd})
            known = {s.id for s in self.plan.sites}
            if not new.target_site_ids or any(s not in known for s in new.target_site_ids):
                raise OpsError(422, "invalid_targets", "target_site_ids must list sites of this trial.")
            if iv.started_at is not None and new.status == "planned":
                raise OpsError(409, "already_started", "A started intervention cannot return to planned.")
            if iv.started_at is not None and new.metric != iv.metric:
                raise OpsError(409, "already_started", "The metric is fixed once the intervention started.")
            self.interventions[iv_id] = new
            if "action" in upd:
                self.iv_meta[iv_id].code = actions.action_code(new.action)
            audit.append(actor=actor, role=role, action="ops.intervention.update", object_type="ops_intervention",
                         object_id=iv_id, before=iv, after=new, reason=patch.get("reason"))
            if iv.started_at is None and {"action", "target_site_ids", "metric"} & set(upd):
                self._attach_expectation(new, actor, role)  # not started: a different action needs its own prediction
            self._after_iv_change(new, previous=iv)
            return new

    @atomic
    def delete_intervention(self, iv_id: str, actor: str, role: str, reason: str | None) -> None:
        with self.lock:
            iv = self.interventions.get(iv_id)
            if iv is None:
                raise OpsError(404, "intervention_not_found", f"No intervention {iv_id} for this trial.")
            if self.iv_meta[iv_id].system or iv.started_at is not None:
                raise OpsError(409, "cannot_delete", "Only planned (not started) interventions can be deleted.")
            if not (reason or "").strip():
                raise OpsError(422, "reason_required", "Deleting an intervention requires a reason (it is audited).")
            del self.interventions[iv_id]
            del self.iv_meta[iv_id]
            audit.append(actor=actor, role=role, action="ops.intervention.delete", object_type="ops_intervention",
                         object_id=iv_id, before=iv, reason=reason)

    def _after_iv_change(self, iv: Intervention, previous: Intervention | None = None) -> None:
        sim_relevant = iv.started_at is not None and iv.status != "planned"
        was = previous is not None and previous.started_at is not None and previous.status != "planned"
        if sim_relevant != was or (sim_relevant and previous is not None and (
                previous.target_site_ids != iv.target_site_ids or previous.action != iv.action)):
            self._regenerate()
        self._refresh_effects(emit=True)

    # ------------------------------------------------------------------ effects
    def _refresh_effects(self, emit: bool) -> None:
        ivs = list(self.interventions.values())
        for iv in ivs:
            if iv.started_at is None:
                continue
            d = estimate_effect(self.plan, self.feed, iv, self.clock_day, others=ivs,
                                direction=direction_for(self.iv_meta[iv.id].alert_kind), seed=self.seed)
            old = self.effects.get(iv.id)
            self.effects[iv.id] = d
            flagged = self._check_replan(iv, d, emit)
            if emit and (flagged or old is None or old.estimate.verdict != d.estimate.verdict
                         or old.estimate.effect != d.estimate.effect):
                self._emit("effect_update", d.estimate.model_dump(mode="json"))

    def effect(self, iv_id: str) -> EffectDetails:
        with self.lock:
            iv = self.interventions.get(iv_id)
            if iv is None:
                raise OpsError(404, "intervention_not_found", f"No intervention {iv_id} for this trial.")
            if iv_id not in self.effects:
                return estimate_effect(self.plan, self.feed, iv, self.clock_day,
                                       others=list(self.interventions.values()),
                                       direction=direction_for(self.iv_meta[iv_id].alert_kind), seed=self.seed)
            return self.effects[iv_id]

    def effect_list(self) -> list[EffectEstimate]:
        with self.lock:
            return [self.effect(i).estimate for i in self.interventions]

    # ------------------------------------------------------------------ expectations
    def _option_set(self, alert: Alert) -> expectation.OptionSet:
        return expectation.options_for_alert(self.plan, self.feed, self.params, self.seed, self.clock_day, alert)

    def _quantified_option(self, alert: Alert, code: str) -> tuple[dict, dict] | None:
        if not alert.site_id or code not in expectation.QUANTIFIED.get(alert.kind, ()):
            return None
        found = self._option_set(alert)
        item = next((o for o in found.payload["items"] if o["code"] == code and o["quantified"]), None)
        return None if item is None else (item, found.draws[code])

    def _attach_expectation(self, iv: Intervention, actor: str, role: str) -> None:
        """Save the prediction as it stands now, if this action is one the planning model covers."""
        meta = self.iv_meta[iv.id]
        meta.expectation = meta.exp_draws = None
        alert = self.alerts.get(iv.alert_id) if iv.alert_id else None
        if meta.system or alert is None:
            return
        option = self._quantified_option(alert, meta.code)
        if option is None:
            return
        item, draws = option
        if item["metric"] != iv.metric or set(item["target_site_ids"]) != set(iv.target_site_ids):
            return  # the follow-up would measure something else than was predicted
        frozen = expectation.freeze(item, alert.id, self.clock_day, self.plan)
        meta.expectation, meta.exp_draws = frozen, draws
        audit.append(actor=actor, role=role, action="ops.intervention.expectation", object_type="ops_intervention",
                     object_id=iv.id, after=frozen,
                     reason="Prediction saved when the action was planned (planning model, assumed parameters)")

    def expectation_of(self, iv_id: str) -> dict | None:
        with self.lock:
            meta = self.iv_meta.get(iv_id)
            return None if meta is None else meta.expectation

    def reconciliation(self, iv_id: str) -> dict | None:
        with self.lock:
            meta = self.iv_meta.get(iv_id)
            if meta is None or meta.expectation is None or meta.exp_draws is None:
                return None
            return expectation.reconcile(self.plan, self.interventions[iv_id], meta.expectation, meta.exp_draws,
                                         self.effect(iv_id))

    def _check_replan(self, iv: Intervention, details: EffectDetails, emit: bool) -> bool:
        """Once the observed effect is clearly below the saved prediction, reopen the alert and say so."""
        meta = self.iv_meta[iv.id]
        if meta.expectation is None or meta.exp_draws is None or meta.replan_flagged:
            return False
        rec = expectation.reconcile(self.plan, iv, meta.expectation, meta.exp_draws, details)
        if not rec["needs_replan"]:
            return False
        meta.replan_flagged = True
        reason = (f"'{iv.action}' is below its predicted effect after {rec['post_weeks']} weeks "
                  f"({rec['verdict'].replace('_', ' ')}). Re-plan.")
        alert = self.alerts.get(iv.alert_id) if iv.alert_id else None
        if alert is not None and alert.status in ("action_planned", "acknowledged"):
            self._set_status(alert, "open", audit.SYSTEM_ACTOR, "admin", reason, self.clock_day, emit)
        audit.append(actor=audit.SYSTEM_ACTOR, role="admin", action="ops.intervention.replan",
                     object_type="ops_intervention", object_id=iv.id, after=rec, reason=reason)
        return True

    # ------------------------------------------------------------------ views
    def visible_events(self, since_day: float | None, limit: int, types: set[str] | None,
                       site_id: str | None, newest_first: bool = True) -> tuple[list[OpsEvent], int]:
        with self.lock:
            n = self._visible_count()
            i0 = int(np.searchsorted(self.event_t, since_day, side="left")) if since_day is not None else 0
            sel = [e for e in self.events[i0:n] if (not types or e.type in types)
                   and (site_id is None or e.site_id == site_id)]
            total = len(sel)
            sel = sel[::-1][:limit] if newest_first else sel[:limit]
            return [self.to_ops_event(e) for e in sel], total

    def health(self) -> dict:
        with self.lock:
            h = compute_health(self.plan, self.feed, self.params, self.clock_day, list(self.alerts.values()),
                               self.seed)
            h["trial_id"] = self.trial_id
            h["clock"] = self.clock_info()
            return h

    def alert_list(self, status: str | None = None) -> list[Alert]:
        with self.lock:
            out = [a for a in self.alerts.values() if status is None or a.status == status]
            sev = {"critical": 0, "warning": 1, "info": 2}
            return sorted(out, key=lambda a: (a.status not in OPEN_STATES, sev[a.severity], -a.detected_at.timestamp()))

    def alert_detail(self, alert_id: str) -> dict:
        with self.lock:
            a = self.alerts.get(alert_id)
            if a is None:
                raise OpsError(404, "alert_not_found", f"No alert {alert_id} for trial {self.trial_id}.")
            m = self.alert_meta[alert_id]
            return {"alert": a.model_dump(mode="json"), "scope": m["scope"], "evidence": _jsonable(m["evidence"]),
                    "provenance": {k: v.model_dump() for k, v in m["provenance"].items()},
                    "history": m["history"], "last_seen": self.plan.date(m["last_seen_day"]).isoformat(),
                    "interventions": [i.model_dump(mode="json") for i in self.interventions.values()
                                      if i.alert_id == alert_id],
                    "options": self._option_set(a).payload if a.status in OPEN_STATES else None,
                    "simulated": True}

    def evaluation(self) -> dict:
        from .evaluate import evaluate_state

        with self.lock:
            return evaluate_state(self)


def _jsonable(x):
    if isinstance(x, dict):
        return {k: _jsonable(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_jsonable(v) for v in x]
    if isinstance(x, np.generic):
        return x.item()
    return x

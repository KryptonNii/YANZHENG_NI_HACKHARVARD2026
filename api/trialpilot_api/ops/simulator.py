"""Seeded simulator of trial-system feeds (EDC, CTMS, IRT, TRAVEL, COURIER, FINANCE, VENDOR).

Everything produced here is SIMULATED (`OpsEvent.simulated = True`).

Determinism and replay safety
-----------------------------
All randomness is pre-drawn per (seed, stream, site) into fixed arrays indexed by day / patient slot /
visit, and interventions only change *thresholds and rates from their start day on*. Re-simulating with
an extra intervention that starts at the current clock therefore leaves every earlier event (and its id)
unchanged — the property the store relies on when a user plans an intervention mid-stream.

Scenarios
---------
* ``demo``: planted problems + scripted interventions with ground truth (see ``build_scenario``).
* ``healthy``: same trial, no planted problems or interventions (used for the "no alert storm" test).
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from . import geo
from .params import OpsParams
from .plan import DAYS_PER_MONTH, MONITORING_CYCLE_WEEKS, WEEKS_PER_MONTH, OpsPlan

# ---------------------------------------------------------------- constants (simulation knobs)
P_MAX = 120  # patient slots per site
Q_MAX = 6  # max queries per visit
BACKUP_RATE_MONTH = 1.5  # enrollment rate of an activated backup site (ground truth knob)
BACKUP_START_LAG = 14  # days from "activate backup site" to first possible enrollment
SITE_INITIATION_LAG = 14  # days from activation to the first monitoring cycle
PUSH_INTERVAL_DAYS = 84  # bulk "upfront" push schedule (12 weeks)
EXPIRY_JITTER_DAYS = 30
FIN_NOISE = 0.05  # +-5% invoice noise around the parameter mid value

STREAM_ENROLL, STREAM_PATIENT, STREAM_SUPPLY, STREAM_SHIP, STREAM_MON, STREAM_TRAIT = 1, 2, 3, 4, 5, 7


@dataclass
class SimIntervention:
    id: str
    code: str
    site_ids: list[str]
    start_day: float
    system: bool = False


@dataclass
class SimEvent:
    t: float  # days since epoch
    key: str
    type: str
    site_id: str | None
    source: str
    payload: dict


@dataclass
class SiteTruth:
    """Hidden simulator state per site. Detection code never reads this (it only sees events)."""

    rate_mult: float
    q_lambda: float
    close_mean: float
    miss_base: float
    supply_policy: str  # predictive | push_bulk
    lead_days: float  # actual depot-to-site lead time
    level_lead_days: float  # lead time assumed by the IRT stock levels
    ship_policy: str  # sop | air_always
    ship_weekday: int


@dataclass
class Scenario:
    name: str
    truths: list[SiteTruth]
    unbatched_countries: set[str]
    vendor_slip: bool
    planted: list[SimIntervention]
    problems: list[dict]
    intervention_truth: dict[str, dict]


@dataclass
class SimResult:
    events: list[SimEvent]
    scenario: Scenario
    ground_truth: dict
    seed: int
    horizon_days: int


@dataclass
class _Patient:
    slot: int
    enroll_t: float
    withdraw_t: float | None
    end_t: float
    visits: list[tuple[int, float, bool]] = field(default_factory=list)  # (visit idx, t, completed)


def event_uuid(trial_id: str, seed: int, scenario: str, key: str) -> str:
    """Deterministic, RFC-4122 version-4-formatted id (replay-safe across regeneration)."""
    h = hashlib.sha256(f"{trial_id}|{seed}|{scenario}|{key}".encode()).digest()[:16]
    return str(uuid.UUID(bytes=h, version=4))


def _rng(seed: int, stream: int, idx: int) -> np.random.Generator:
    return np.random.default_rng([seed, stream, idx])


def poisson_inv(lam: float, u: float) -> int:
    """Inverse CDF of Poisson(lam) at u (small lam), so a fixed uniform maps to a count."""
    if lam <= 0:
        return 0
    k, p = 0, math.exp(-lam)
    c = p
    while u > c and k < 60:
        k += 1
        p *= lam / k
        c += p
    return k


def is_winter(date: datetime, hemisphere: str) -> bool:
    return date.month in ((12, 1, 2) if hemisphere == "north" else (6, 7, 8))


# ---------------------------------------------------------------- scenario
_PREFERRED = {
    "slow": ["S14", "S26", "S06"],
    "never": ["S30"],
    "backlog_now": ["S04", "S23"],
    "backlog_past": ["S11", "S27"],
    "overstock": ["S14"],
    "shortfall": ["S36"],
    "air": ["S15"],
}
SLOW_MULTS = [0.35, 0.30, 0.30]


def _pick(plan: OpsPlan, role: str, n: int, taken: set[str]) -> list[str]:
    ids = [s.id for s in plan.sites if not s.backup]
    want = [i for i in _PREFERRED.get(role, []) if i in ids][:n]
    for i in ids:  # deterministic fallback for non-fixture designs
        if len(want) >= n:
            break
        if i not in want and i not in taken:
            want.append(i)
    return want


def build_scenario(plan: OpsPlan, seed: int, name: str) -> Scenario:
    truths: list[SiteTruth] = []
    for s in plan.sites:
        u = _rng(seed, STREAM_TRAIT, s.idx).random(6)
        truths.append(
            SiteTruth(
                rate_mult=0.9 + 0.3 * u[0],
                q_lambda=0.35 * (0.8 + 0.4 * u[1]),
                close_mean=8.0 + 6.0 * u[2],
                miss_base=0.07 * (0.8 + 0.4 * u[3]),
                supply_policy="predictive",
                lead_days=8.0,
                level_lead_days=8.0,
                ship_policy="sop",
                ship_weekday=s.idx % 5,
            )
        )
    if name == "healthy":
        return Scenario(name, truths, set(), False, [], [], {})
    if name != "demo":
        raise ValueError(f"unknown scenario {name!r}")

    idx = plan.site_index()
    taken: set[str] = set()
    problems: list[dict] = []

    def onset(sid: str) -> int:
        return int(plan.site(sid).activation_day or 0)

    slow = _pick(plan, "slow", 3, taken)
    taken |= set(slow)
    for sid, m in zip(slow, SLOW_MULTS, strict=False):
        truths[idx[sid]].rate_mult = m
        problems.append({"id": f"slow_{sid}", "kind": "enrollment_lag", "scope": sid, "onset_day": onset(sid),
                         "detect_within_days": 450, "description": f"{sid} enrolls at {int(m * 100)}% of plan"})
    never = _pick(plan, "never", 1, taken)
    taken |= set(never)
    for sid in never:
        truths[idx[sid]].rate_mult = 0.0
        problems.append({"id": f"never_{sid}", "kind": "enrollment_lag", "scope": sid, "onset_day": onset(sid),
                         "detect_within_days": 150, "description": f"{sid} never enrolls"})
    backlog = _pick(plan, "backlog_now", 2, taken)
    taken |= set(backlog)
    for sid in backlog:
        truths[idx[sid]].q_lambda, truths[idx[sid]].close_mean = 1.1, 45.0
        problems.append({"id": f"backlog_{sid}", "kind": "query_backlog", "scope": sid, "onset_day": onset(sid),
                         "detect_within_days": 240,
                         "description": f"{sid}: high query rate and slow query closure -> growing backlog"})
    past = _pick(plan, "backlog_past", 2, taken)
    taken |= set(past)
    for sid in past:
        truths[idx[sid]].q_lambda, truths[idx[sid]].close_mean = 1.0, 40.0
        problems.append({"id": f"backlog_{sid}", "kind": "query_backlog", "scope": sid, "onset_day": onset(sid),
                         "detect_within_days": 280,
                         "description": f"{sid}: growing backlog until staff retraining (intervention I1)"})
    over = [s for s in _pick(plan, "overstock", 1, set()) if s in slow] or slow[:1]
    for sid in over:
        truths[idx[sid]].supply_policy = "push_bulk"
        problems.append({"id": f"overstock_{sid}", "kind": "drug_overstock", "scope": sid, "onset_day": onset(sid),
                         "detect_within_days": 330,
                         "description": f"{sid}: bulk upfront pushes sized to plan + slow enrollment -> expiry waste"})
    short = _pick(plan, "shortfall", 1, taken)
    taken |= set(short)
    for sid in short:
        t = truths[idx[sid]]
        t.rate_mult, t.lead_days = 2.2, 21.0
        problems.append({"id": f"shortfall_{sid}", "kind": "drug_shortfall", "scope": sid, "onset_day": onset(sid),
                         "detect_within_days": 300,
                         "description": f"{sid}: enrolls at 2.2x plan; IRT levels assume 8-day lead time, "
                                        "actual import lead time ~21 days"})
    air = _pick(plan, "air", 1, taken)
    taken |= set(air)
    for sid in air:
        truths[idx[sid]].ship_policy = "air_always"
        problems.append({"id": f"air_{sid}", "kind": "costly_shipping_mode", "scope": sid,
                         "onset_day": onset(sid), "detect_within_days": 150,
                         "description": f"{sid}: specimens flown although ground courier is within range"})
    # monitoring: the first country with >= 2 multi-site city clusters (ES in the fixture)
    by_country: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for s in plan.sites:
        if not s.backup:
            by_country[s.country][s.city] += 1
    unbatched = {"ES"} if "ES" in by_country else set()
    if not unbatched:
        for cc, cities in by_country.items():
            if sum(1 for n in cities.values() if n >= 2) >= 1:
                unbatched = {cc}
                break
    for cc in unbatched:
        problems.append({"id": f"monitoring_{cc}", "kind": "monitoring_inefficiency", "scope": cc,
                         "onset_day": 0, "detect_within_days": 200,
                         "description": f"{cc}: monitoring visits to sites in the same city are not batched"})
    problems.append({"id": "vendor_dm_cro", "kind": "vendor_delay", "scope": "M3", "onset_day": 300,
                     "detect_within_days": 45,
                     "description": "Data-management CRO slips the DB-lock prerequisite (SDTM + edit checks)"})
    problems.append({"id": "milestone_dblock", "kind": "milestone_at_risk", "scope": "db_lock", "onset_day": 300,
                     "detect_within_days": 120,
                     "description": "Vendor slip pushes the database-lock forecast past its target"})

    # scripted interventions with ground truth
    def ids(cands: list[str], n: int) -> list[str]:
        have = [c for c in cands if c in idx]
        return have[:n] if len(have) >= min(n, 1) else []

    backups = [s.id for s in plan.sites if s.backup]
    region_we = [s.id for s in plan.sites if s.country in {"FR", "DE", "IT", "NL", "BE"} and not s.backup]
    planted = [
        SimIntervention("I1", "crf_retraining", past, 280, True),
        SimIntervention("I3", "query_reminder_email", ids(["S01", "S02", "S03", "S05", "S08"], 5), 250, True),
        SimIntervention("I4", "visit_reminder_sms", region_we[:11], 182, True),
    ]
    if backups:
        planted.insert(1, SimIntervention("I2", "activate_backup", backups[:2], 196, True))
    planted = [p for p in planted if p.site_ids]
    truth = {
        "I1": {"action": "Retrain site staff on eCRF completion guidelines", "metric": "query_rate_percent",
               "true_effect": "works", "expected_verdict": "likely_worked",
               "mechanism": "query rate x0.35 and mean closure 10 days from the start day"},
        "I2": {"action": "Activate backup sites in the same country", "metric":
               "regional_enrollment_rate_per_month", "true_effect": "works", "expected_verdict": "likely_worked",
               "mechanism": f"backup sites enroll {BACKUP_RATE_MONTH}/month from start + {BACKUP_START_LAG} d"},
        "I3": {"action": "Send weekly open-query reminder e-mails to site coordinators",
               "metric": "query_rate_percent", "true_effect": "none", "expected_verdict": "no_effect",
               "mechanism": "no change in any simulator rate"},
        "I4": {"action": "Visit-reminder SMS programme for patients", "metric": "missed_visit_rate_percent",
               "true_effect": "coincidence", "expected_verdict": "likely_coincidence",
               "mechanism": "no effect; starts the day the northern winter ends, when missed visits fall at "
                            "every northern site (winter multiplier on missed visits)"},
    }
    return Scenario(name, truths, unbatched, True, planted, problems,
                    {k: v for k, v in truth.items() if any(p.id == k for p in planted)})


# ---------------------------------------------------------------- simulator
class _Ctx:
    def __init__(self, plan: OpsPlan, params: OpsParams, seed: int, sc: Scenario,
                 interventions: list[SimIntervention]):
        self.plan, self.params, self.seed, self.sc = plan, params, seed, sc
        self.ivs = list(sc.planted) + list(interventions)
        self.events: list[SimEvent] = []
        self.H = plan.horizon_days
        self.country_of = {s.id: s.country for s in plan.sites}

    def emit(self, t: float, key: str, typ: str, site_id: str | None, source: str, payload: dict) -> None:
        if 0 <= t < self.H:
            self.events.append(SimEvent(round(t, 5), key, typ, site_id, source, payload))

    def iv(self, code: str, site_id: str, day: float) -> SimIntervention | None:
        """The earliest intervention with this code covering the site that has started by `day`."""
        best = None
        for iv in self.ivs:
            if iv.code == code and iv.start_day <= day and (
                site_id in iv.site_ids or self._country_covered(iv, site_id)
            ):
                if best is None or iv.start_day < best.start_day:
                    best = iv
        return best

    def ivs_for(self, code: str, site_id: str) -> list[SimIntervention]:
        return [iv for iv in self.ivs if iv.code == code and site_id in iv.site_ids]

    def _country_covered(self, iv: SimIntervention, site_id: str) -> bool:
        if iv.code not in ("batch_monitoring", "remote_monitoring"):
            return False
        return self.country_of.get(site_id) in {self.country_of.get(s) for s in iv.site_ids}

    def date(self, t: float) -> datetime:
        return self.plan.epoch + timedelta(days=t)

    def iso(self, t: float) -> str:
        return self.date(t).strftime("%Y-%m-%d")


def activation_day(plan: OpsPlan, site, interventions: list[SimIntervention]) -> float | None:
    """When a site opens to enrollment.

    Planned sites use the operational activation day. A backup site opens only when an
    ``activate_backup`` intervention names it, or names its country without naming a backup.
    """
    if not site.backup:
        return None if site.activation_day is None else float(site.activation_day)
    starts = []
    for iv in interventions:
        if iv.code != "activate_backup":
            continue
        named_backups = [sid for sid in iv.site_ids if plan.site(sid).backup]
        countries = {plan.site(sid).country for sid in iv.site_ids}
        if site.id in iv.site_ids or (not named_backups and site.country in countries):
            starts.append(iv.start_day + BACKUP_START_LAG)
    return min(starts) if starts else None


def _backup_activation(ctx: _Ctx, site_id: str) -> float | None:
    return activation_day(ctx.plan, ctx.plan.site(site_id), ctx.ivs)


def _enrollment(ctx: _Ctx) -> dict[int, list[float]]:
    """Day loop over all sites (study cap couples sites). Returns enrollment times per site."""
    plan, sc = ctx.plan, ctx.sc
    u_enroll = {s.idx: _rng(ctx.seed, STREAM_ENROLL, s.idx).random((ctx.H, 2)) for s in plan.sites}
    start = {}
    for s in plan.sites:
        opened = activation_day(plan, s, ctx.ivs)
        start[s.idx] = opened
        if opened is not None:
            ctx.emit(opened + 0.1, f"{s.id}:ctms:activation", "site_activated", s.id, "CTMS", {
                "activation_date": ctx.iso(opened), "country": s.country, "region": s.region,
                "status": "open_to_enrollment",
            })
    out: dict[int, list[float]] = {s.idx: [] for s in plan.sites}
    total = 0
    for d in range(ctx.H):
        for s in plan.sites:
            a = start[s.idx]
            if a is None or d < a or total >= plan.enrollment_target or len(out[s.idx]) >= P_MAX:
                continue
            base = BACKUP_RATE_MONTH if s.backup else s.planned_rate_month * sc.truths[s.idx].rate_mult
            mult = 1.0
            iv = ctx.iv("enrollment_retraining", s.id, d - 14)
            if iv is not None:
                mult *= 1.6
            if ctx.iv("close_site", s.id, d) is not None:
                mult = 0.0
            lam = base / DAYS_PER_MONTH * mult
            u = u_enroll[s.idx][d]
            n = poisson_inv(lam, float(u[0]))
            for k in range(n):
                if total >= plan.enrollment_target or len(out[s.idx]) >= P_MAX:
                    break
                out[s.idx].append(d + 0.375 + 0.3 * ((float(u[1]) + 0.37 * k) % 1.0))  # 09:00-16:12
                total += 1
    return out


def _patients(ctx: _Ctx, s, enroll_ts: list[float]) -> list[_Patient]:
    plan, truth = ctx.plan, ctx.sc.truths[s.idx]
    r = _rng(ctx.seed, STREAM_PATIENT, s.idx)
    nv = len(plan.visits)
    u_jit = r.random((P_MAX, nv))
    u_miss = r.random((P_MAX, nv))
    u_q = r.random((P_MAX, nv))
    u_qo = r.random((P_MAX, nv, Q_MAX))
    u_qc = r.random((P_MAX, nv, Q_MAX))
    u_drop = r.random((P_MAX, 2))
    u_lab = r.random((P_MAX, nv))
    ctx._u_lab = u_lab  # type: ignore[attr-defined]
    p_drop = 1.0 - math.exp(-ctx.params.mid("ops.rate.dropout_per_year") * plan.last_visit_week / 52.0)
    winter_mult = ctx.params.mid("ops.rate.missed_visit_winter_mult")
    patients: list[_Patient] = []
    sid = s.id
    sessions = sorted(iv.start_day for iv in ctx.ivs_for("query_session", sid))
    for slot, te in enumerate(enroll_ts):
        withdraw = te + 14 + float(u_drop[slot, 1]) * plan.last_visit_week * 7 if u_drop[slot, 0] < p_drop else None
        pt = _Patient(slot, te, withdraw, te + plan.last_visit_week * 7)
        pid = f"{sid}-P{slot + 1:03d}"
        ctx.emit(te, f"{sid}:enr:{slot}", "patient_enrolled", sid, "EDC",
                 {"patient_id": pid, "arm": "blinded", "enrolled_on": ctx.iso(te)})
        if withdraw is not None:
            ctx.emit(withdraw, f"{sid}:P{slot}:wd", "patient_withdrawn", sid, "EDC",
                     {"patient_id": pid, "reason": "withdrew consent"})
        for vi, vp in enumerate(plan.visits):
            if vp.week < 0:
                t = max(float(s.activation_day or te), te - 14 + 3 * float(u_jit[slot, vi]))
                t = min(t, te - 0.05)
            elif vp.week == 0:
                t = te + 0.01
            else:
                t = math.floor(te + vp.week * 7 + (float(u_jit[slot, vi]) - 0.5) * 6) + 0.4 + 0.3 * float(
                    u_jit[slot, vi])
            if withdraw is not None and t > withdraw:
                break
            if t >= ctx.H:
                break
            date = ctx.date(t)
            p_miss = truth.miss_base * (winter_mult if is_winter(date, s.hemisphere) else 1.0)
            missed = vp.week > 0 and float(u_miss[slot, vi]) < p_miss
            vkey = f"{sid}:P{slot}:V{vp.number}"
            if missed:
                ctx.emit(t, vkey + ":missed", "visit_missed", sid, "EDC",
                         {"patient_id": pid, "visit_number": vp.number, "visit_label": vp.label,
                          "week": vp.week, "reason": "patient did not attend"})
                pt.visits.append((vi, t, False))
                continue
            pt.visits.append((vi, t, True))
            ctx.emit(t, vkey + ":done", "visit_completed", sid, "EDC",
                     {"patient_id": pid, "visit_number": vp.number, "visit_label": vp.label, "mode": vp.mode,
                      "procedures": vp.procedures, "site_minutes": vp.site_minutes, "week": vp.week})
            # data queries raised by edit checks / monitors on this visit's eCRF pages
            lam_q = truth.q_lambda
            close_mean = truth.close_mean
            if ctx.iv("crf_retraining", sid, t) is not None:
                lam_q, close_mean = lam_q * 0.35, 10.0
            nq = min(Q_MAX, poisson_inv(lam_q, float(u_q[slot, vi])))
            for j in range(nq):
                t_open = t + 1.0 + 4.0 * float(u_qo[slot, vi, j])
                t_close = t_open + 0.5 - close_mean * math.log(1.0 - 0.999 * float(u_qc[slot, vi, j]))
                for st in sessions:
                    if t_open < st < t_close:
                        t_close = st + 1.0 + 6.0 * float(u_qc[slot, vi, j])
                        break
                qid = f"Q-{sid}-{slot + 1:03d}-{vp.number:02d}-{j + 1}"
                ctx.emit(t_open, vkey + f":Q{j}:open", "query_opened", sid, "EDC",
                         {"query_id": qid, "patient_id": pid, "visit_number": vp.number})
                ctx.emit(t_close, vkey + f":Q{j}:close", "query_closed", sid, "EDC",
                         {"query_id": qid, "patient_id": pid, "visit_number": vp.number,
                          "age_days": round(t_close - t_open, 1)})
        patients.append(pt)
    return patients


def _ship_mode(ctx: _Ctx, s, t: float) -> str:
    sop = "ground" if s.road_km_to_hub <= ctx.params.mid("ops.ship.ground_max_km") else "air"
    if ctx.sc.truths[s.idx].ship_policy == "air_always" and ctx.iv("ground_shipping", s.id, t) is None:
        return "air"
    return sop


def _samples(ctx: _Ctx, s, patients: list[_Patient]) -> None:
    plan = ctx.plan
    u_lab = ctx._u_lab  # type: ignore[attr-defined]
    rng = _rng(ctx.seed, STREAM_SHIP, s.idx).random(ctx.H + 7)
    pkg = ctx.params.mid("ops.ship.specimen_package_kg")
    frozen_by_day: dict[int, int] = defaultdict(int)
    fridge_by_day: dict[int, int] = defaultdict(int)
    for pt in patients:
        for vi, t, done in pt.visits:
            if not done:
                continue
            for temp in plan.visits[vi].sample_temps:
                if temp.startswith("frozen"):
                    frozen_by_day[int(t)] += 1
                elif float(u_lab[pt.slot, vi]) >= plan.local_lab_share:
                    fridge_by_day[int(t)] += 1

    def ship(t: float, temp: str, n: int, key: str) -> None:
        mode = _ship_mode(ctx, s, t)
        km = s.road_km_to_hub if mode == "ground" else s.gc_km_to_hub
        ctx.emit(t, key, "sample_shipment", s.id, "COURIER", {
            "shipment_id": f"SMP-{s.id}-{key.rsplit(':', 1)[-1]}", "temp": temp, "mode": mode, "n_samples": n,
            "weight_kg": round(pkg * (0.85 + 0.3 * float(rng[int(t) % len(rng)])), 2),
            "distance_km": round(km, 1), "destination": s.hub.label,
            "planned_transit_h": 24 if mode == "air" else (24 if km < 500 else 48)})

    for d, n in sorted(fridge_by_day.items()):
        ship(d + 0.625, "refrigerated", n, f"{s.id}:smp:fridge:{d}")
    pending, first = 0, min(frozen_by_day) if frozen_by_day else None
    if first is None:
        return
    for d in range(first, ctx.H):
        pending += frozen_by_day.get(d, 0)
        if pending and d % 7 == ctx.sc.truths[s.idx].ship_weekday:
            ship(d + 0.58, "frozen_-80", pending, f"{s.id}:smp:frozen:{d}")
            pending = 0


def _supply(ctx: _Ctx, s, patients: list[_Patient]) -> None:
    """IRT: per-site inventory with lots (FEFO), resupply policy, expiry, transfers."""
    plan, truth, params = ctx.plan, ctx.sc.truths[s.idx], ctx.params
    sid = s.id
    r = _rng(ctx.seed, STREAM_SUPPLY, s.idx).random(4096)
    shelf = params.mid("ops.supply.shelf_life_at_site")
    kit_kg = params.mid("ops.ship.kit_kg")
    kpw = plan.kits_per_patient / max(plan.last_visit_week, 1.0)
    planned_new_wk = (BACKUP_RATE_MONTH if s.backup else s.planned_rate_month) / WEEKS_PER_MONTH
    start = s.activation_day if not s.backup else _backup_activation(ctx, sid)
    if start is None:
        return
    demands: dict[int, list[tuple[float, _Patient, int, int]]] = defaultdict(list)
    for pt in patients:
        for vi, t, done in pt.visits:
            k = plan.visits[vi].dispense_kits
            if done and k:
                demands[int(t)].append((t, pt, plan.visits[vi].number, k))
    lots: list[list] = []  # [lot_id, qty, expiry_day]
    transit: list[tuple[float, str, int, float, str]] = []  # (arrive, lot, qty, expiry, ship_id)
    n_ship = 0
    closed = False
    mode = "ground" if s.road_km_to_hub <= params.mid("ops.ship.ground_max_km") else "air"
    km = s.road_km_to_hub if mode == "ground" else s.gc_km_to_hub
    transferred_at: set[float] = set()

    def on_hand() -> int:
        return int(sum(lot[1] for lot in lots))

    def dispatch(t: float, qty: int, reason: str, lead: float, ship_mode: str | None = None) -> None:
        nonlocal n_ship
        if qty <= 0:
            return
        n_ship += 1
        sm = ship_mode or mode
        dist = km if sm == mode else s.gc_km_to_hub
        lot = f"{sid}-L{n_ship:03d}"
        arrive = t + lead
        expiry = math.floor(arrive) + shelf + (float(r[n_ship % 4096]) - 0.5) * 2 * EXPIRY_JITTER_DAYS
        ship_id = f"DRG-{sid}-{n_ship:03d}"
        payload = {"shipment_id": ship_id, "direction": "inbound", "status": "dispatched", "kits": qty,
                   "lot_id": lot, "expiry_date": ctx.iso(expiry), "eta": ctx.iso(arrive), "reason": reason,
                   "origin": s.hub.label, "destination": sid, "mode": sm, "distance_km": round(dist, 1),
                   "weight_kg": round(qty * kit_kg, 2)}
        ctx.emit(t, f"{sid}:drg:{n_ship}:disp", "drug_shipment", sid, "IRT", payload)
        transit.append((arrive, lot, qty, expiry, ship_id))

    def levels(d: int) -> tuple[float, float]:
        on_treat = sum(1 for pt in patients if pt.enroll_t <= d < pt.end_t and (pt.withdraw_t is None
                                                                               or d < pt.withdraw_t))
        new_wk, lead = planned_new_wk, truth.level_lead_days
        if ctx.iv("raise_trigger", sid, d) is not None:
            recent = sum(1 for pt in patients if d - 56 <= pt.enroll_t < d) / 8.0
            new_wk, lead = max(new_wk, recent), truth.lead_days
        need = on_treat * kpw + new_wk * 2.0
        trigger = max(6.0, need * (lead / 7.0 + 2.0) + 3.0)  # +3 kits for bursts of new patients
        return trigger, max(10.0, trigger + need * 4.0 + 2.0)

    def transfer_out(t: float, keep: float, reason: str) -> None:
        nonlocal n_ship
        excess = on_hand() - int(math.ceil(keep))
        if excess <= 0:
            return
        moved: list[dict] = []
        for lot in sorted(lots, key=lambda x: -x[2]):  # move the longest-dated kits (useful elsewhere)
            if excess <= 0:
                break
            q = min(lot[1], excess)
            if q > 0:
                lot[1] -= q
                excess -= q
                moved.append({"lot_id": lot[0], "kits": int(q)})
        n_ship += 1
        ctx.emit(t, f"{sid}:drg:{n_ship}:out", "drug_shipment", sid, "IRT", {
            "shipment_id": f"DRG-{sid}-{n_ship:03d}", "direction": "outbound", "status": "dispatched",
            "kits": int(sum(m["kits"] for m in moved)), "lots": moved, "reason": reason,
            "origin": sid, "destination": s.hub.label, "mode": mode, "distance_km": round(km, 1),
            "weight_kg": round(sum(m["kits"] for m in moved) * kit_kg, 2)})

    # the initial supply is dispatched so that it is on site at activation
    first_day = int(math.floor(start - truth.lead_days))
    next_push = float(first_day)
    for d in range(first_day, ctx.H):
        # receipts (10:00)
        for item in [x for x in transit if x[0] < d + 1]:
            arrive, lot, qty, expiry, ship_id = item
            transit.remove(item)
            lots.append([lot, qty, expiry])
            ctx.emit(max(arrive, d + 0.41), f"{sid}:drg:{ship_id}:recv", "drug_shipment", sid, "IRT", {
                "shipment_id": ship_id, "direction": "inbound", "status": "received", "kits": qty, "lot_id": lot,
                "expiry_date": ctx.iso(expiry)})
        # expiry (00:30)
        for lot in lots:
            if lot[1] > 0 and lot[2] <= d + 1:
                ctx.emit(d + 0.02, f"{sid}:exp:{lot[0]}", "drug_expired", sid, "IRT",
                         {"lot_id": lot[0], "kits": int(lot[1]), "expiry_date": ctx.iso(lot[2])})
                lot[1] = 0
        # dispensing (FEFO)
        for t, pt, vnum, k in sorted(demands.get(d, []), key=lambda x: x[0]):
            need, used = k, []
            for lot in sorted(lots, key=lambda x: x[2]):
                if need <= 0:
                    break
                q = min(lot[1], need)
                if q > 0:
                    lot[1] -= q
                    need -= q
                    used.append({"lot_id": lot[0], "kits": int(q)})
            ctx.emit(t + 0.01, f"{sid}:disp:P{pt.slot}:V{vnum}", "drug_dispensed", sid, "IRT", {
                "patient_id": f"{sid}-P{pt.slot + 1:03d}", "visit_number": vnum, "kits": int(k - need),
                "kits_short": int(need), "lots": used})
        if closed:
            continue
        # interventions acting on stock
        for code, reason in (("supply_on_demand", "transfer_excess"), ("transfer_excess", "transfer_excess"),
                             ("close_site", "site_closed")):
            iv = ctx.iv(code, sid, d - 2)
            if iv is not None and (code, iv.start_day) not in transferred_at:
                transferred_at.add((code, iv.start_day))  # type: ignore[arg-type]
                keep = 0.0 if code == "close_site" else levels(d)[1]
                transfer_out(d + 0.45, keep, reason)
                if code == "close_site":
                    closed = True
        if closed:
            continue
        iv = ctx.iv("emergency_resupply", sid, d - 1)
        if iv is not None and ("emergency", iv.start_day) not in transferred_at:
            transferred_at.add(("emergency", iv.start_day))  # type: ignore[arg-type]
            dispatch(d + 0.5, int(math.ceil(levels(d)[1])), "emergency", 2.0, "air")
        policy = truth.supply_policy
        if ctx.iv("supply_on_demand", sid, d) is not None:
            policy = "predictive"
        in_transit = sum(x[2] for x in transit)
        if policy == "push_bulk":
            if d >= next_push:
                ahead = sum(plan.planned_on_treatment(s.idx, d + w * 7) for w in range(12)) * kpw
                qty = max(6, int(math.ceil(ahead + planned_new_wk * 12 * 2.0)))
                dispatch(d + 0.6, qty, "scheduled_push" if d > first_day else "initial", truth.lead_days)
                next_push += PUSH_INTERVAL_DAYS
        else:
            trigger, mx = levels(d)
            if on_hand() + in_transit < trigger:
                dispatch(d + 0.66, int(math.ceil(mx - on_hand() - in_transit)),
                         "initial" if n_ship == 0 else "resupply", truth.lead_days)


def _monitoring(ctx: _Ctx, first_enroll: dict[str, float]) -> None:
    plan, params = ctx.plan, ctx.params
    road = params.mid("ops.dist.road_factor")
    clusters: dict[str, list] = defaultdict(list)
    for s in plan.sites:
        clusters[s.cluster].append(s)
    base: dict[str, object] = {}
    for s in plan.sites:
        base.setdefault(s.country, s)
    cycle_days = MONITORING_CYCLE_WEEKS * 7
    for ci, (cl, sites) in enumerate(sorted(clusters.items())):
        r = _rng(ctx.seed, STREAM_MON, ci).random((200, 4))
        b = base[sites[0].country]
        gc = geo.haversine_km(b.lat, b.lon, sites[0].lat, sites[0].lon)  # type: ignore[attr-defined]
        if gc < 30:
            mode, rt_km = "car", 30.0
        else:
            one_way = gc * road
            if one_way <= 250:
                mode, rt_km = "car", 2 * one_way
            elif one_way <= 700:
                mode = "rail" if sites[0].region in geo.RAIL_REGIONS else "car"
                rt_km = 2 * one_way
            else:
                mode, rt_km = "flight", 2 * gc
        starts = [x for x in (first_enroll.get(s.id) for s in sites) if x is not None]
        if not starts:
            continue
        c0 = min(starts) + SITE_INITIATION_LAG
        for c in range(200):
            cs = c0 + c * cycle_days
            if cs >= ctx.H:
                break
            due = [s for s in sites if first_enroll.get(s.id) is not None and first_enroll[s.id] <= cs
                   and ctx.iv("close_site", s.id, cs) is None]
            if not due:
                continue
            if ctx.iv("remote_monitoring", due[0].id, cs) is not None:
                remote = c % 2 == 1  # alternate cycles become remote source-data review
            else:
                remote = float(r[c, 0]) < plan.remote_monitoring_share
            batched = sites[0].country not in ctx.sc.unbatched_countries or ctx.iv(
                "batch_monitoring", due[0].id, cs) is not None
            groups = [due] if batched else [[s] for s in due]
            for k, grp in enumerate(groups):
                t = cs + 1 + (7 * k if not batched else 0) + math.floor(3 * float(r[c, 1 + min(k, 2)])) + 0.29
                ctx.emit(t, f"mon:{cl}:{c}:{k}", "monitoring_trip", grp[0].id, "TRAVEL", {
                    "trip_id": f"TRIP-{grp[0].country}-{ci:02d}-{c:03d}-{k}", "cra_id": f"CRA-{grp[0].country}",
                    "site_ids": [g.id for g in grp], "city": grp[0].city, "country": grp[0].country,
                    "region": grp[0].region, "mode": "remote" if remote else mode,
                    "round_trip_km": 0.0 if remote else round(rt_km, 1), "site_days": len(grp), "remote": remote})


def _vendor(ctx: _Ctx) -> None:
    plan = ctx.plan
    dbl = plan.dblock_target_day
    milestones = [
        ("M1", "EDC vendor", "Mid-study EDC update (protocol amendment 1)", 240, False, -4),
        ("M2", "Central lab", "Interim lab data transfer #1", 330, False, 3),
        ("M3", "Data-management CRO", "SDTM datasets + edit-check package ready for database lock",
         dbl - 60, True, None),
        ("M4", "IRT vendor", "IRT configuration for open-label extension", 450, False, 0),
    ]
    for d in range(120, ctx.H):
        date = ctx.date(d)
        if date.day != 1:
            continue
        for mid, vendor, label, planned, critical, actual_slip in milestones:
            if actual_slip is not None:
                done_day = planned + actual_slip
                if d > done_day + 31:
                    continue
                slip = actual_slip if d >= planned - 60 else 0
                status = "complete" if d >= done_day else "on_track"
            else:
                slip = _vendor_slip(ctx, d) if ctx.sc.vendor_slip else 0
                status = "on_track" if slip <= 7 else "at_risk" if slip <= 30 else "delayed"
            ctx.emit(d + 0.5, f"ven:{mid}:{d}", "vendor_milestone", None, "VENDOR", {
                "vendor": vendor, "milestone_id": mid, "milestone": label, "planned_date": ctx.iso(planned),
                "forecast_date": ctx.iso(planned + slip), "status": status, "critical_path": critical,
                "report_date": ctx.iso(d)})


def _vendor_slip(ctx: _Ctx, d: int) -> int:
    ramp = [(300, 35), (330, 80), (360, 110), (390, 130), (420, 140)]
    slip = 0
    for day, v in ramp:
        if d >= day:
            slip = v
    iv = None
    for x in ctx.ivs:
        if x.code == "vendor_resourcing" and x.start_day <= d:
            iv = x
            break
    if iv is not None and slip:
        months = min(2.0, (d - iv.start_day) / 30.0)
        slip = int(round(slip * (1 - 0.3 * months)))  # recovers 60% of the slip over two months
    return slip


def _finance(ctx: _Ctx) -> None:
    """Monthly invoices for the previous month, aggregated from the operational events."""
    p = ctx.params
    fee, day_cost, travel = p.mid("ops.cost.site_visit_fee"), p.mid("ops.cost.monitoring_site_day"), p.mid(
        "ops.cost.monitoring_trip_travel")
    c_ground, c_air, kit = p.mid("ops.cost.courier_ground"), p.mid("ops.cost.courier_air"), p.mid(
        "ops.cost.drug_kit")
    emergency = p.mid("ops.cost.emergency_resupply")
    agg: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for e in ctx.events:
        period = ctx.date(e.t).strftime("%Y-%m")
        pl = e.payload
        if e.type == "visit_completed":
            agg[(period, e.site_id or "", "site_fees")]["visits"] += 1
        elif e.type == "sample_shipment":
            agg[(period, e.site_id or "", "courier")][pl["mode"]] += 1
        elif e.type == "drug_shipment" and pl.get("status") == "dispatched" and pl.get("direction") == "inbound":
            agg[(period, e.site_id or "", "drug_supply")]["kits"] += pl["kits"]
            if pl.get("reason") == "emergency":
                agg[(period, e.site_id or "", "drug_supply")]["emergency"] += 1
        elif e.type == "monitoring_trip" and not pl.get("remote"):
            key = (period, "country:" + pl["country"], "monitoring")
            agg[key]["site_days"] += pl["site_days"]
            agg[key]["trips"] += 1
    for (period, scope, cat), basis in sorted(agg.items()):
        y, m = int(period[:4]), int(period[5:])
        nxt = datetime(y + (m == 12), m % 12 + 1, 3, 9, tzinfo=UTC)
        t = (nxt - ctx.plan.epoch).total_seconds() / 86400
        if cat == "site_fees":
            amount = basis["visits"] * fee
        elif cat == "courier":
            amount = basis.get("ground", 0) * c_ground + basis.get("air", 0) * c_air
        elif cat == "drug_supply":
            amount = basis["kits"] * kit + basis.get("emergency", 0) * emergency
        else:
            amount = basis["site_days"] * day_cost + basis["trips"] * travel
        h = int(hashlib.sha256(f"{ctx.seed}|{period}|{scope}|{cat}".encode()).hexdigest()[:8], 16)
        amount *= 1 + FIN_NOISE * (2 * (h / 0xFFFFFFFF) - 1)
        site_id = None if scope.startswith("country:") else scope
        ctx.emit(t, f"fin:{scope}:{period}:{cat}", "budget_spend", site_id, "FINANCE", {
            "category": cat, "period": period, "amount_usd": round(amount, 2), "currency": "USD",
            "basis": {k: v for k, v in basis.items()},
            **({"country": scope.split(":", 1)[1]} if site_id is None else {})})


def simulate(plan: OpsPlan, params: OpsParams, seed: int = 42, scenario: str = "demo",
             interventions: list[SimIntervention] | None = None) -> SimResult:
    sc = build_scenario(plan, seed, scenario)
    ctx = _Ctx(plan, params, seed, sc, interventions or [])
    enroll = _enrollment(ctx)
    first_enroll: dict[str, float] = {}
    for s in plan.sites:
        ts = enroll[s.idx]
        if ts:
            first_enroll[s.id] = ts[0]
        patients = _patients(ctx, s, ts)
        _samples(ctx, s, patients)
        _supply(ctx, s, patients)
    _monitoring(ctx, first_enroll)
    _vendor(ctx)
    _finance(ctx)
    ctx.events.sort(key=lambda e: (e.t, e.key))
    gt = ground_truth(plan, sc, seed, interventions or [])
    return SimResult(ctx.events, sc, gt, seed, ctx.H)


def _json_day(day: float) -> int | float:
    return int(day) if float(day).is_integer() else day


def ground_truth(plan: OpsPlan, sc: Scenario, seed: int,
                 interventions: list[SimIntervention] | None = None) -> dict:
    ivs = list(sc.planted) + list(interventions or [])
    activations = []
    for s in plan.sites:
        day = activation_day(plan, s, ivs)
        if day is None:
            continue
        activations.append({
            "site_id": s.id, "activation_day": _json_day(day), "backup": s.backup,
            "event_type": "site_activated", "source_system": "CTMS",
            "activation_date": (plan.epoch + timedelta(days=day)).date().isoformat(),
            "country": s.country, "region": s.region, "status": "open_to_enrollment",
        })
    return {
        "simulated": True,
        "note": "Ground truth of the SIMULATED feed (planted problems and scripted interventions). "
                "The detection and effect-estimation code never reads it; it is only used for evaluation.",
        "seed": seed,
        "scenario": sc.name,
        "epoch": plan.epoch.isoformat(),
        "horizon_days": plan.horizon_days,
        "season": {"missed_visit_winter_months": {"north": [12, 1, 2], "south": [6, 7, 8]}},
        "problems": [{**p, "onset_date": (plan.epoch + timedelta(days=p["onset_day"])).date().isoformat()}
                     for p in sc.problems],
        "interventions": [
            {"id": iv.id, "code": iv.code, "target_site_ids": iv.site_ids, "start_day": iv.start_day,
             "start_date": (plan.epoch + timedelta(days=iv.start_day)).date().isoformat(),
             **sc.intervention_truth.get(iv.id, {})}
            for iv in sc.planted
        ],
        "site_truth": {
            s.id: {"rate_mult": round(t.rate_mult, 3), "query_lambda": round(t.q_lambda, 3),
                   "query_close_mean_days": round(t.close_mean, 1), "supply_policy": t.supply_policy,
                   "lead_days": t.lead_days, "ship_policy": t.ship_policy}
            for s, t in zip(plan.sites, sc.truths, strict=True)
        },
        "activations": activations,
    }

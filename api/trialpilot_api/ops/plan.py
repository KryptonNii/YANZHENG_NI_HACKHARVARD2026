"""The operational plan the command center compares actuals against.

Built from a `TrialDesign` (+ optional `ScenarioResult` levers). Enrollment bands come from A3's
forecast when available; until then a labelled stub Poisson–gamma forecast is used (same model
family A3 documents: site rate ~ Gamma, counts ~ Poisson), and `OpsPlan.notes` says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import numpy as np

from . import geo
from ._contracts import ScenarioResult, TrialDesign
from .params import OpsParams

EPOCH = datetime(2025, 9, 1, tzinfo=UTC)  # simulated first-site activation (a Monday)
DAYS_PER_MONTH = 365.25 / 12
WEEKS_PER_MONTH = DAYS_PER_MONTH / 7
MAX_SITES = 40
PLAN_RATE_SHAPE = 12.0  # Gamma shape for site-rate uncertainty in the plan (CV ≈ 0.29) — assumption
ACTIVATION_SPREAD_DAYS = 56
MONITORING_CYCLE_WEEKS = 6
SCHEDULE_CONTINGENCY_DAYS = 30  # plan buffer between expected DB lock and the DB-lock target — assumption
KIT_WEEKS = 4  # one kit = 4 weeks of treatment (fixture assumption)


@dataclass
class PlanSite:
    idx: int
    id: str
    name: str
    city: str
    country: str  # ISO2
    region: str
    hemisphere: str
    lat: float
    lon: float
    activation_day: int | None  # None = backup site (not in the enrollment plan)
    planned_total: float
    planned_rate_month: float
    hub: geo.Hub
    gc_km_to_hub: float
    road_km_to_hub: float

    @property
    def backup(self) -> bool:
        return self.activation_day is None

    @property
    def cluster(self) -> str:
        return f"{self.country}|{self.city}"


@dataclass
class VisitPlan:
    number: int
    label: str
    week: float
    procedures: list[str]
    site_minutes: float
    sample_temps: list[str]
    dispense_kits: int
    mode: str  # on_site | remote | home


@dataclass
class OpsPlan:
    design: TrialDesign
    epoch: datetime
    horizon_days: int
    enrollment_target: int
    enrollment_end_day: int
    sites: list[PlanSite]
    visits: list[VisitPlan]
    supply_strategy: str
    remote_monitoring_share: float
    local_lab_share: float
    kits_per_patient: int
    site_band: np.ndarray  # [S, W+1, 3] cumulative enrollment P10/P50/P90 at end of week w
    study_band: np.ndarray  # [W+1, 3]
    lpi_target_day: int
    lplv_target_day: int
    dblock_target_day: int
    last_visit_week: float
    notes: list[str] = field(default_factory=list)
    scenario_meta: dict[str, object] = field(default_factory=dict)

    @property
    def n_weeks(self) -> int:
        return self.horizon_days // 7

    def site(self, site_id: str) -> PlanSite:
        for s in self.sites:
            if s.id == site_id:
                return s
        raise KeyError(site_id)

    def site_index(self) -> dict[str, int]:
        return {s.id: s.idx for s in self.sites}

    def date(self, day: float) -> datetime:
        return self.epoch + timedelta(days=day)

    def day_of(self, when: datetime) -> float:
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        return (when - self.epoch).total_seconds() / 86400.0

    def planned_on_treatment(self, site_idx: int, day: float) -> float:
        """Expected patients on treatment at a site on `day` under the plan (linear enrollment)."""
        s = self.sites[site_idx]
        if s.activation_day is None or day <= s.activation_day:
            return 0.0
        rate_day = s.planned_rate_month / DAYS_PER_MONTH
        enrolling = min(day, self.enrollment_end_day) - s.activation_day
        treat_days = self.last_visit_week * 7
        # patients enrolled in (day - treat_days, day] are still on treatment
        window_start = max(s.activation_day, day - treat_days)
        window_end = min(day, self.enrollment_end_day)
        return max(0.0, rate_day * max(0.0, window_end - window_start)) if enrolling > 0 else 0.0


def _visit_plans(design: TrialDesign, levers: dict) -> tuple[list[VisitPlan], int]:
    visits = sorted(design.visits, key=lambda v: v.week)
    removed = set(levers.get("removed_procedures") or [])
    remote = set(levers.get("remote_visit_numbers") or [])
    home = set(levers.get("home_visit_numbers") or [])
    out: list[VisitPlan] = []
    for i, v in enumerate(visits):
        procs = [p for p in v.procedures if p.code not in removed]
        nxt = visits[i + 1].week if i + 1 < len(visits) else v.week
        dispense = any(p.code == "ip_dispense" for p in procs)
        kits = max(1, math.ceil((nxt - v.week) / KIT_WEEKS)) if dispense and nxt > v.week else 0
        mode = "remote" if v.number in remote else "home" if v.number in home else "on_site"
        out.append(
            VisitPlan(
                number=v.number,
                label=v.label,
                week=v.week,
                procedures=[p.code for p in procs],
                site_minutes=float(sum(p.site_minutes if p.site_minutes is not None else 15.0 for p in procs)),
                sample_temps=[p.sample_temp for p in procs if p.ships_sample and p.sample_temp],
                dispense_kits=kits,
                mode=mode,
            )
        )
    return out, sum(v.dispense_kits for v in out)


def _stub_forecast_bands(
    sites: list[PlanSite], n_weeks: int, enrollment_end_day: int, draws: int = 1000, seed: int = 7
) -> tuple[np.ndarray, np.ndarray]:
    """Plan enrollment bands: rate_i ~ Gamma(k, rate/k), N_i(t) ~ Poisson(rate_i * exposure_i(t))."""
    rng = np.random.default_rng(seed)
    weeks = np.arange(n_weeks + 1)
    end_days = weeks * 7.0
    n = len(sites)
    exposure = np.zeros((n, n_weeks + 1))
    rates = np.zeros(n)
    for s in sites:
        if s.activation_day is None:
            continue
        exposure[s.idx] = np.clip(np.minimum(end_days, enrollment_end_day) - s.activation_day, 0, None)
        rates[s.idx] = s.planned_rate_month / DAYS_PER_MONTH
    lam = rng.gamma(PLAN_RATE_SHAPE, 1.0 / PLAN_RATE_SHAPE, size=(draws, n)) * rates  # per day
    counts = rng.poisson(lam[:, :, None] * exposure[None, :, :])  # [draws, S, W+1]
    site_band = np.quantile(counts, [0.1, 0.5, 0.9], axis=0).transpose(1, 2, 0)
    study_band = np.quantile(counts.sum(axis=1), [0.1, 0.5, 0.9], axis=0).T
    return site_band, study_band


def build_plan(
    design: TrialDesign,
    params: OpsParams,
    scenario: ScenarioResult | None = None,
    horizon_days: int = 600,
    epoch: datetime = EPOCH,
    forecast_result=None,
) -> OpsPlan:
    levers = scenario.levers.model_dump() if scenario is not None else {}
    excluded = set(levers.get("excluded_site_ids") or [])
    raw_sites = [s for s in design.sites if s.id not in excluded][:MAX_SITES]
    if not raw_sites:
        raise ValueError("design has no sites to simulate")
    visit_plans, kits_per_patient = _visit_plans(design, levers)
    last_visit_week = max((v.week for v in visit_plans), default=52.0)

    # Enrollment period: what remains of the trial after treatment/follow-up, cleaning and close-out.
    cleaning_days = params.mid("ops.time.db_lock_cleaning")
    total_days = design.duration_months * DAYS_PER_MONTH
    enrollment_end_day = int(
        max(180.0, total_days - last_visit_week * 7 - cleaning_days - SCHEDULE_CONTINGENCY_DAYS)
    )

    expected = [s.expected_enrollment for s in raw_sites]
    active_mask = [e is None or e > 0 for e in expected]
    n_active = sum(active_mask)
    known = sum(e for e in expected if e)
    unknown = sum(1 for e, a in zip(expected, active_mask, strict=True) if a and e is None)
    target = design.enrollment_target
    notes: list[str] = []
    if unknown:
        notes.append(f"{unknown} site(s) without expected_enrollment: target split evenly (assumption).")

    # deterministic activation schedule over the first 8 weeks (plan input not in the contract)
    order = np.random.default_rng(20250901).permutation(n_active)
    activation_rank = iter(order.tolist())
    sites: list[PlanSite] = []
    for i, s in enumerate(raw_sites):
        cc = geo.iso2(s.country)
        region = geo.region_of(cc)
        lat = s.lat if s.lat is not None else 0.0
        lon = s.lon if s.lon is not None else 0.0
        hub = geo.hub_for_region(region)
        gc = geo.haversine_km(lat, lon, hub.lat, hub.lon) if s.lat is not None else 500.0
        if active_mask[i]:
            rank = next(activation_rank)
            act: int | None = int(round(ACTIVATION_SPREAD_DAYS * rank / max(1, n_active - 1)))
            share = (s.expected_enrollment or 0.0) if known and s.expected_enrollment else None
            if share is None:
                planned_total = target / n_active
            else:
                planned_total = share / max(known, 1e-9) * target * (n_active - unknown) / n_active
        else:
            act, planned_total = None, 0.0
        months = (enrollment_end_day - act) / DAYS_PER_MONTH if act is not None else 1.0
        sites.append(
            PlanSite(
                idx=i,
                id=s.id,
                name=s.name,
                city=s.city or s.name,
                country=cc,
                region=region,
                hemisphere=geo.hemisphere_of(cc, s.lat),
                lat=lat,
                lon=lon,
                activation_day=act,
                planned_total=planned_total,
                planned_rate_month=planned_total / months if act is not None else 0.0,
                hub=hub,
                gc_km_to_hub=gc,
                road_km_to_hub=gc * params.mid("ops.dist.road_factor"),
            )
        )
    if len(design.sites) > MAX_SITES:
        notes.append(f"Design has {len(design.sites)} sites; the ops simulation uses the first {MAX_SITES}.")

    n_weeks = horizon_days // 7
    site_band, study_band = _stub_forecast_bands(sites, n_weeks, enrollment_end_day)
    notes.append(
        "Site enrollment bands: operational Poisson-gamma plan; "
        f"site-rate shape k={PLAN_RATE_SHAPE} (assumption)."
    )
    lpi = enrollment_end_day
    lplv = int(lpi + last_visit_week * 7)
    dblock = int(lplv + cleaning_days + SCHEDULE_CONTINGENCY_DAYS)
    meta: dict[str, object] = {}
    if scenario is not None:
        meta = {
            "design_id": scenario.design_id,
            "parameter_set_version": scenario.parameter_set_version,
            "scenario_cost_usd": scenario.cost_usd.model_dump(),
            "scenario_co2e_kg": scenario.co2e_kg.model_dump(),
            "scenario_duration_months": scenario.duration_months.model_dump(),
        }
    plan = OpsPlan(
        design=design,
        epoch=epoch,
        horizon_days=horizon_days,
        enrollment_target=target,
        enrollment_end_day=enrollment_end_day,
        sites=sites,
        visits=visit_plans,
        supply_strategy=str(levers.get("drug_supply_strategy") or "upfront"),
        remote_monitoring_share=float(levers.get("remote_monitoring_share") or 0.0),
        local_lab_share=float(levers.get("local_lab_share") or 0.0),
        kits_per_patient=kits_per_patient,
        site_band=site_band,
        study_band=study_band,
        lpi_target_day=lpi,
        lplv_target_day=lplv,
        dblock_target_day=dblock,
        last_visit_week=last_visit_week,
        notes=notes,
        scenario_meta=meta,
    )
    if any(p.site_minutes is None for v in design.visits for p in v.procedures):
        plan.notes.append("Missing procedure site_minutes filled with 15 minutes per procedure "
                          "(assumption; replace with protocol timings).")
    if any(s.lat is None or s.lon is None for s in raw_sites):
        plan.notes.append("Missing site coordinates: logistics distance uses a 500-km hub distance "
                          "assumption; map coordinates are unknown.")
    from .forecast_adapter import prepare

    prepare(plan, supplied=forecast_result)
    return plan

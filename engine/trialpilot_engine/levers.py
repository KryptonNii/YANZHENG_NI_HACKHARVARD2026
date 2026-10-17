"""Design + levers → activity data: who travels where how often, which samples ship, how many kits.

This is the only place where levers change *activity*. Each lever's effect, in one line:
- `remote_monitoring_share`: splits monitoring visits into on-site trips × (1 − share) and remote reviews × share.
- `home_visit_numbers` / `remote_visit_numbers`: set those visits' mode to home / remote (no patient travel).
- `local_lab_share`: share of samples analysed locally instead of shipped to the central lab.
- `drug_supply_strategy`: picks the kit waste share (or A3's simulation when passed in).
- `removed_procedures`: drops those procedure codes from every visit.
- `excluded_site_ids`: removes those sites; the enrollment target is redistributed over the others.
Parameter *values* never appear here except the labelled fall-backs for incomplete designs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

import numpy as np

from ._contracts import Levers, MetricRange, Parameter, Procedure, Site, TrialDesign, Visit
from .provenance import Inputs, ParamStore, slug
from .uncertainty import FloatArray, draws_from_range

VisitMode = Literal["site", "home", "remote"]
TempClass = Literal["ambient", "refrigerated", "frozen"]
TEMP_CLASSES: tuple[TempClass, ...] = ("ambient", "refrigerated", "frozen")

# Calendar constants (not trial parameters).
WEEKS_PER_YEAR = 365.25 / 7
DAYS_PER_MONTH = 365.25 / 12
MONTHS_PER_YEAR = 12.0

# Procedure codes that mean "investigational product handed out / given at this visit".
DISPENSING_MARKERS = ("dispens", "imp_admin", "drug_admin", "ip_admin", "dosing", "infusion")


class EngineInputError(ValueError):
    """The design or levers cannot be computed. `code` is a stable error code (A5 → HTTP 422)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ForecastLike(Protocol):
    """What the engine reads from A3's ForecastResult."""

    @property
    def duration_months(self) -> MetricRange: ...


class SupplyLike(Protocol):
    """What the engine reads from A3's SupplyResult."""

    @property
    def kits_produced(self) -> MetricRange: ...

    @property
    def waste_share(self) -> MetricRange: ...

    @property
    def shipments(self) -> MetricRange: ...


@dataclass(frozen=True)
class CountryGroup:
    code: str  # lowercase ISO 3166 alpha-2 ("gb"), a slug when unrecognised, or "global"
    sites: int
    patients: float


@dataclass(frozen=True)
class PlannedVisit:
    number: int
    label: str
    week: float
    mode: VisitMode
    procedures: tuple[Procedure, ...]

    @property
    def dispenses(self) -> bool:
        return any(m in slug(p.code) for p in self.procedures for m in DISPENSING_MARKERS)


@dataclass(frozen=True)
class Activity:
    """Deterministic structure of the trial after levers (same for every Monte Carlo draw)."""

    patients: float
    countries: tuple[CountryGroup, ...]
    visits: tuple[PlannedVisit, ...]
    dispensing_visits: int  # per patient
    remote_monitoring_share: float
    local_lab_share: float
    supply_strategy: Literal["upfront", "on_demand"]
    drug_type: str
    warnings: tuple[str, ...]
    notes: tuple[str, ...]  # assumptions shown in provenance of the affected terms

    @property
    def sites(self) -> int:
        return sum(g.sites for g in self.countries)

    def visits_in(self, mode: VisitMode) -> int:
        return sum(1 for v in self.visits if v.mode == mode)

    @property
    def visits_per_patient(self) -> int:
        return len(self.visits)

    def samples_per_patient(self) -> dict[TempClass, int]:
        """Sample-shipping procedures per patient, by temperature class (all visit modes)."""
        counts: dict[TempClass, int] = dict.fromkeys(TEMP_CLASSES, 0)
        for v in self.visits:
            for p in v.procedures:
                if p.ships_sample:
                    counts[temp_class(p)] += 1
        return counts

    @property
    def stores_minus80(self) -> bool:
        return any(p.ships_sample and p.sample_temp == "frozen_-80" for v in self.visits for p in v.procedures)

    @property
    def follow_up_years(self) -> float:
        """Per-patient participation: first to last scheduled visit, in years."""
        if not self.visits:
            return 0.0
        weeks = [v.week for v in self.visits]
        return (max(weeks) - min(weeks)) / WEEKS_PER_YEAR


@dataclass(frozen=True)
class Context:
    """Everything a formula needs for one scenario computation."""

    act: Activity
    ps: ParamStore
    duration_months: FloatArray  # per draw
    supply: SupplyLike | None
    seed: int

    @property
    def n(self) -> int:
        return self.ps.n

    def zeros(self) -> FloatArray:
        return np.zeros(self.ps.n)


def temp_class(p: Procedure) -> TempClass:
    if p.sample_temp in ("frozen_-20", "frozen_-80"):
        return "frozen"
    if p.sample_temp == "refrigerated":
        return "refrigerated"
    return "ambient"  # "ambient" or not stated (noted in build_activity)


# ---------------------------------------------------------------- countries

_COUNTRY_CODES: dict[str, str] = {
    "united states": "us", "usa": "us", "us": "us", "united states of america": "us",
    "united kingdom": "gb", "uk": "gb", "great britain": "gb", "england": "gb", "scotland": "gb",
    "wales": "gb", "northern ireland": "gb", "spain": "es", "australia": "au", "germany": "de",
    "france": "fr", "italy": "it", "canada": "ca", "netherlands": "nl", "the netherlands": "nl",
    "belgium": "be", "poland": "pl", "japan": "jp", "china": "cn", "korea, republic of": "kr",
    "south korea": "kr", "republic of korea": "kr", "brazil": "br", "mexico": "mx",
    "argentina": "ar", "india": "in", "russian federation": "ru", "russia": "ru", "czechia": "cz",
    "czech republic": "cz", "hungary": "hu", "israel": "il", "sweden": "se", "denmark": "dk",
    "norway": "no", "finland": "fi", "austria": "at", "switzerland": "ch", "ireland": "ie",
    "portugal": "pt", "greece": "gr", "turkey": "tr", "türkiye": "tr", "turkiye": "tr",
    "south africa": "za", "new zealand": "nz", "taiwan": "tw", "singapore": "sg",
    "hong kong": "hk", "romania": "ro", "bulgaria": "bg", "ukraine": "ua", "chile": "cl",
    "colombia": "co", "peru": "pe", "thailand": "th", "malaysia": "my", "philippines": "ph",
    "vietnam": "vn", "viet nam": "vn", "egypt": "eg", "saudi arabia": "sa", "slovakia": "sk",
    "serbia": "rs", "croatia": "hr", "estonia": "ee", "latvia": "lv", "lithuania": "lt",
    "slovenia": "si", "georgia": "ge", "puerto rico": "pr",
}


def country_code(country: str) -> str:
    """'United Kingdom' / 'GB' / 'gb' → 'gb'; unknown names → slug (falls back to `.global` params)."""
    key = country.strip().casefold()
    if key in _COUNTRY_CODES:
        return _COUNTRY_CODES[key]
    if len(key) == 2 and key.isalpha():
        return key
    return slug(country) if key and key != "global" else "global"


# ---------------------------------------------------------------- build

def _assumed_count(params: Mapping[str, Parameter], pid: str, what: str) -> float:
    p = params.get(pid)
    if p is None:
        raise EngineInputError(
            "design_incomplete",
            f"The design has no {what} and the parameter library has no `{pid}` to assume one.",
        )
    return p.value_mid


def _validate_levers(design: TrialDesign, levers: Levers) -> None:
    for name in ("remote_monitoring_share", "local_lab_share"):
        value = getattr(levers, name)
        if not 0.0 <= value <= 1.0:
            raise EngineInputError("invalid_levers", f"`{name}` must be between 0 and 1, got {value}.")
    if design.enrollment_target < 0:
        raise EngineInputError("invalid_design", "`enrollment_target` must not be negative.")
    if design.duration_months < 0:
        raise EngineInputError("invalid_design", "`duration_months` must not be negative.")


def _sites(
    design: TrialDesign, levers: Levers, params: Mapping[str, Parameter], warnings: list[str]
) -> tuple[list[Site], list[str]]:
    notes: list[str] = []
    excluded = set(levers.excluded_site_ids)
    unknown = sorted(excluded - {s.id for s in design.sites})
    if unknown:
        warnings.append(f"Excluded site ids not in the design were ignored: {', '.join(unknown)}.")
    if not design.sites:
        per_site = _assumed_count(params, "assume.design.patients_per_site", "site list")
        n = max(1, math.ceil(design.enrollment_target / per_site)) if per_site > 0 else 1
        warnings.append(
            f"The design lists no sites: {n} sites assumed (enrollment {design.enrollment_target} ÷ "
            f"`assume.design.patients_per_site` {per_site:g}), country unknown → global parameters."
        )
        notes.append(f"{n} sites assumed from `assume.design.patients_per_site`.")
        return [Site(id=f"assumed-{i + 1}", name=f"Assumed site {i + 1}", country="global") for i in range(n)], notes
    active = [s for s in design.sites if s.id not in excluded]
    if not active:
        raise EngineInputError("invalid_levers", "All sites are excluded; at least one site must remain.")
    return active, notes


def _allocate_patients(sites: list[Site], total: float, notes: list[str]) -> list[float]:
    """Split the enrollment target over active sites by expected enrollment (equal if unknown)."""
    known = [s.expected_enrollment for s in sites if s.expected_enrollment is not None and s.expected_enrollment > 0]
    if not known:
        if len(sites) > 1:
            notes.append("Site expected enrollment not given: patients split equally across sites.")
        weights = [1.0] * len(sites)
    else:
        fill = sum(known) / len(known)
        if len(known) < len(sites):
            notes.append(
                f"{len(sites) - len(known)} sites have no expected enrollment: given the mean of the others."
            )
        weights = [
            s.expected_enrollment if s.expected_enrollment is not None and s.expected_enrollment > 0 else fill
            for s in sites
        ]
    scale = total / sum(weights)
    return [w * scale for w in weights]


def _visits(
    design: TrialDesign, levers: Levers, params: Mapping[str, Parameter], warnings: list[str]
) -> tuple[list[PlannedVisit], list[str]]:
    notes: list[str] = []
    source: list[Visit] = sorted(design.visits, key=lambda v: (v.week, v.number))
    if not source:
        k = max(1, round(_assumed_count(params, "assume.design.visits_per_patient", "visit schedule")))
        span_weeks = design.duration_months / MONTHS_PER_YEAR * WEEKS_PER_YEAR
        step = span_weeks / (k - 1) if k > 1 else 0.0
        source = [Visit(number=i + 1, label=f"Assumed visit {i + 1}", week=i * step) for i in range(k)]
        warnings.append(
            f"Visit schedule missing → {k} visits assumed (`assume.design.visits_per_patient`), evenly "
            "spaced, with no procedures: site staff time counts visit admin only."
        )
        notes.append(f"{k} visits assumed from `assume.design.visits_per_patient`.")

    numbers = {v.number for v in source}
    home, remote = set(levers.home_visit_numbers), set(levers.remote_visit_numbers)
    for name, chosen in (("home_visit_numbers", home), ("remote_visit_numbers", remote)):
        stray = sorted(chosen - numbers)
        if stray:
            warnings.append(f"`{name}` lists visits not in the schedule (ignored): {stray}.")
    both = sorted(home & remote)
    if both:
        warnings.append(f"Visits {both} are in both home and telehealth lists: treated as home visits.")

    removed = {slug(c) for c in levers.removed_procedures}
    present = {slug(p.code) for v in source for p in v.procedures}
    not_found = sorted(removed - present)
    if not_found:
        warnings.append(f"Removed procedures not in any visit (no effect): {', '.join(not_found)}.")

    planned: list[PlannedVisit] = []
    without_procedures: list[int] = []
    unknown_temp = 0
    for v in source:
        mode: VisitMode = "home" if v.number in home else "remote" if v.number in remote else "site"
        procs = tuple(p for p in v.procedures if slug(p.code) not in removed)
        if mode != "site" and not v.can_be_remote:
            warnings.append(
                f"Visit {v.number} ({v.label}) is not marked remote-capable in the design but was moved "
                f"to {'home nursing' if mode == 'home' else 'telehealth'} by a lever."
            )
        if mode == "remote" and any(p.ships_sample for p in procs):
            warnings.append(
                f"Telehealth visit {v.number} ({v.label}) has sample-collecting procedures; samples are "
                "still counted (needs home phlebotomy or a local lab)."
            )
        if not procs and design.visits:
            without_procedures.append(v.number)
        unknown_temp += sum(1 for p in procs if p.ships_sample and p.sample_temp is None)
        planned.append(PlannedVisit(v.number, v.label, v.week, mode, procs))

    if without_procedures:
        warnings.append(
            f"Visits {without_procedures} list no procedures: only visit admin time is counted for them."
        )
    if unknown_temp:
        warnings.append(
            f"{unknown_temp} sample-shipping procedures (per patient) have no storage temperature: shipped "
            "as ambient (understates frozen shipping and dry ice if they are frozen)."
        )
    return planned, notes


def build_activity(design: TrialDesign, levers: Levers, params: Mapping[str, Parameter]) -> Activity:
    """Apply levers to the design. Raises EngineInputError for designs that cannot be computed."""
    _validate_levers(design, levers)
    warnings: list[str] = []
    sites, site_notes = _sites(design, levers, params, warnings)
    allocation = _allocate_patients(sites, float(design.enrollment_target), site_notes)
    by_country: dict[str, tuple[int, float]] = {}
    for site, patients in zip(sites, allocation, strict=True):
        code = country_code(site.country)
        n_sites, n_patients = by_country.get(code, (0, 0.0))
        by_country[code] = (n_sites + 1, n_patients + patients)
    countries = tuple(CountryGroup(c, s, p) for c, (s, p) in sorted(by_country.items()))

    visits, visit_notes = _visits(design, levers, params, warnings)
    dispensing = sum(1 for v in visits if v.dispenses)
    notes = [*site_notes, *visit_notes]
    if design.drug_type != "none" and dispensing == 0 and visits:
        dispensing = len(visits)
        warnings.append(
            "No dispensing procedure found in the schedule: every visit is assumed to dispense kits "
            "(drug_supply may be overstated)."
        )
    return Activity(
        patients=float(design.enrollment_target),
        countries=countries,
        visits=tuple(visits),
        dispensing_visits=dispensing,
        remote_monitoring_share=levers.remote_monitoring_share,
        local_lab_share=levers.local_lab_share,
        supply_strategy=levers.drug_supply_strategy,
        drug_type=design.drug_type,
        warnings=tuple(warnings),
        notes=tuple(notes),
    )


# ---------------------------------------------------------------- derived activity (per draw)

def monitoring_visits(ctx: Context) -> tuple[dict[str, FloatArray], dict[str, FloatArray], Inputs]:
    """Monitoring visits per country: on-site = sites × rate × months × (1 − remote share); remote = rest."""
    act = ctx.act
    rate = ctx.ps.get("rate.monitoring.onsite_visits_per_site_month")
    onsite: dict[str, FloatArray] = {}
    remote: dict[str, FloatArray] = {}
    for g in act.countries:
        total = g.sites * rate * ctx.duration_months
        onsite[g.code] = total * (1.0 - act.remote_monitoring_share)
        remote[g.code] = total * act.remote_monitoring_share
    inputs: Inputs = {
        "active_sites": act.sites,
        "remote_monitoring_share": act.remote_monitoring_share,
        "duration_months_p50": float(np.median(ctx.duration_months)),
    }
    return onsite, remote, inputs


def sample_shipments(ctx: Context) -> tuple[dict[tuple[str, TempClass], FloatArray], Inputs]:
    """Central-lab shipments per (country, temperature): patients × samples × (1 − local share) ÷ batch."""
    act = ctx.act
    per_patient = act.samples_per_patient()
    central = 1.0 - act.local_lab_share
    out: dict[tuple[str, TempClass], FloatArray] = {}
    if central == 0.0 or not any(per_patient.values()):
        return out, {}
    batch = ctx.ps.get("supply.sample.samples_per_shipment")
    for g in act.countries:
        for temp in TEMP_CLASSES:
            if per_patient[temp]:
                out[(g.code, temp)] = g.patients * per_patient[temp] * central / batch
    inputs: Inputs = {f"samples_per_patient.{t}": float(c) for t, c in per_patient.items() if c}
    inputs["central_lab_share"] = central
    return out, inputs


@dataclass(frozen=True)
class KitFlow:
    kits_made: FloatArray
    waste_share: FloatArray  # 0..1
    shipments: FloatArray
    inputs: Inputs
    source: str


def drug_kits(ctx: Context) -> KitFlow | None:
    """Kits made, waste share and depot→site shipments; None when the trial has no drug."""
    act, ps = ctx.act, ctx.ps
    if act.drug_type == "none" or act.patients == 0 or act.dispensing_visits == 0:
        return None
    if ctx.supply is not None:
        s = ctx.supply
        made = draws_from_range(s.kits_produced, ctx.seed, "a3.supply", ctx.n)
        waste = draws_from_range(s.waste_share, ctx.seed, "a3.supply", ctx.n)
        if s.waste_share.unit == "percent":
            waste = waste / 100.0
        shipments = draws_from_range(s.shipments, ctx.seed, "a3.supply", ctx.n)
        inputs: Inputs = {
            "kits_produced_p50": s.kits_produced.p50,
            "waste_share_p50": s.waste_share.p50,
            "shipments_p50": s.shipments.p50,
        }
        return KitFlow(made, waste, shipments, inputs, "A3 drug supply simulation")
    needed = act.patients * act.dispensing_visits * ps.get("supply.kits_per_dispensing_visit")
    waste = ps.get(f"supply.waste_share.{act.supply_strategy}")
    made = np.where(waste < 1.0, needed / np.maximum(1.0 - waste, 1e-12), np.nan)
    made = np.where(np.isnan(waste), np.nan, made)
    shipments = act.sites * ps.get(f"supply.shipments_per_site.{act.supply_strategy}")
    inputs = {
        "patients": act.patients,
        "dispensing_visits_per_patient": act.dispensing_visits,
        "strategy": act.supply_strategy,
        "active_sites": act.sites,
    }
    return KitFlow(made, waste, shipments, inputs, "parameter library (no supply simulation passed)")

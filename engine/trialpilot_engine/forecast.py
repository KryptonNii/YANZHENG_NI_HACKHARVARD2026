"""Enrollment, milestone and duration forecast (owner: A3). Pure functions, no I/O.

Model (full write-up: docs/model_forecast.md)
---------------------------------------------
Poisson–gamma recruitment (Anisimov & Fedorov, "Modelling, prediction and adaptive adjustment of
recruitment in multicentre trials", Stat Med 2007;26(27):4958–75, doi:10.1002/sim.2956):

* site i opens at aᵢ ~ Triangular(site.activation_months) and then randomises patients as a Poisson
  process with rate λᵢ ~ Gamma(shape α, mean = m · wᵢ) (m: mean rate, wᵢ: site weight, α = 1/CV²);
* cumulative intensity M(t) = Σᵢ λᵢ · (t − aᵢ)⁺ is piecewise linear, and by the time-change theorem
  the k-th randomisation happens at M⁻¹(Γₖ) with Γₖ ~ Gamma(k, 1). We invert M exactly, vectorised
  over draws × sites, so there is no time grid and no per-patient loop;
* patients to randomise n = ⌈target / (1 − dropout)⌉; duration = last patient in + follow-up
  (last scheduled visit) + closeout (last patient last visit → database lock).

Every number comes from the parameter library. An id missing from the library falls back to a
built-in `assumption: true` default (with rationale and range) and the result carries a warning
naming it — never silently.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from ._contracts import Levers, MetricRange, Parameter, ProvenanceItem, Site, TrialDesign

__all__ = [
    "FORECAST_DEFAULTS",
    "ForecastDraws",
    "ForecastError",
    "ForecastResult",
    "ParameterResolver",
    "estimate_rate_hyperparameters",
    "forecast",
    "update_with_actuals",
]

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
Unit = Literal["usd", "hours", "kg_co2e", "months", "patients", "percent", "kits"]

WEEKS_PER_MONTH = 52.0 / 12.0  # calendar conversion, not a model parameter
MILESTONES = ("first_patient_in", "last_patient_in", "last_patient_last_visit", "database_lock")
_MAX_CURVE_POINTS = 121
_CURVE_DRAWS = 500  # the enrollment-curve bands use the first 500 draws (speed)
_MAX_DROPOUT = 0.95  # guard: a dropout rate ≥ 1 would make the enrolment target infinite


class ForecastError(ValueError):
    """The design cannot be forecast (no sites, no target, inconsistent actuals). User-facing message."""


# ---------------------------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------------------------


def _assumed(pid: str, label: str, low: float, mid: float, high: float, unit: str, why: str) -> Parameter:
    return Parameter(
        id=pid, label=label, value_low=low, value_mid=mid, value_high=high, unit=unit,
        assumption=True, rationale=why, region="global",
    )


# Built-in fallbacks, used ONLY when the id is absent from the parameter library (A10). Each use is
# reported in ForecastResult.warnings. These are explicit assumptions, not sourced values.
FORECAST_DEFAULTS: dict[str, Parameter] = {
    p.id: p
    for p in (
        _assumed(
            "site.activation_months", "Site activation delay after study start (per-site spread)",
            1.0, 4.0, 10.0, "months/site",
            "Placeholder spread of site start-up times for a multinational Phase 3; replace with a "
            "sourced benchmark or the sponsor's activation plan.",
        ),
        _assumed(
            "site.enrollment_rate_per_month", "Mean randomisation rate per active site",
            0.1, 0.5, 1.5, "patients/site/month",
            "Used only when the design's own planned duration cannot be used to derive the rate. "
            "Deliberately wide: recruitment rates differ by orders of magnitude between indications.",
        ),
        _assumed(
            "site.enrollment_rate_shape", "Gamma shape α of between-site recruitment rates",
            0.7, 1.5, 4.0, "dimensionless",
            "Gamma-distributed site rates (Anisimov & Fedorov 2007); α = 1/CV², so 0.7–4 spans a "
            "between-site CV of 1.2–0.5. Placeholder heterogeneity; estimate from historical site "
            "data with estimate_rate_hyperparameters().",
        ),
        _assumed(
            "forecast.plan_rate_multiplier", "Realised vs planned recruitment rate",
            0.75, 1.0, 1.25, "ratio",
            "Symmetric ±25% uncertainty around the rate implied by the registered plan; no "
            "directional (optimism) bias is assumed without a source.",
        ),
        _assumed(
            "patient.dropout_rate", "Share of randomised patients who drop out before the last visit",
            0.05, 0.15, 0.25, "share",
            "Placeholder; replace with the protocol's planned dropout or a sourced benchmark.",
        ),
        _assumed(
            "trial.closeout_months", "Last patient last visit to database lock",
            2.0, 4.0, 6.0, "months",
            "Placeholder; replace with the sponsor's data-management timeline or a sourced benchmark.",
        ),
        _assumed(
            "trial.followup_months", "Follow-up per patient when the design has no visit schedule",
            6.0, 12.0, 24.0, "months",
            "Only used when TrialDesign.visits is empty; the schedule of activities always wins.",
        ),
        _assumed(
            "lever.decentralised.recruitment_uplift",
            "Relative recruitment-rate change if all visits were home/remote",
            0.0, 0.0, 0.0, "share",
            "No benefit assumed by default (never silently assume benefits). Set a sourced range to "
            "explore it; the effect scales with the share of visits moved.",
        ),
        _assumed(
            "lever.decentralised.dropout_reduction",
            "Relative dropout reduction if all visits were home/remote",
            0.0, 0.0, 0.0, "share",
            "No benefit assumed by default (never silently assume benefits). Set a sourced range to "
            "explore it; the effect scales with the share of visits moved.",
        ),
    )
}


class ParameterResolver:
    """Looks parameters up in the library; missing ids fall back to built-in assumptions, loudly."""

    def __init__(self, params: Mapping[str, Parameter], defaults: Mapping[str, Parameter]) -> None:
        self._params = params
        self._defaults = defaults
        self.used: dict[str, Parameter] = {}
        self.fallbacks: dict[str, Parameter] = {}

    def has(self, pid: str) -> bool:
        return pid in self._params

    def get(self, *ids: str) -> Parameter:
        """First of `ids` found in the library, else the built-in default of the last id."""
        for pid in ids:
            p = self._params.get(pid)
            if p is not None:
                self.used[pid] = p
                return p
        p = self._defaults[ids[-1]]
        self.used[p.id] = p
        self.fallbacks[p.id] = p
        return p

    def warnings(self) -> list[str]:
        return [
            f"Parameter '{p.id}' is missing from the parameter library; used built-in assumption "
            f"{_fmt(p.value_low)}/{_fmt(p.value_mid)}/{_fmt(p.value_high)} {p.unit} "
            f"(low/mid/high) — {p.rationale}"
            for p in self.fallbacks.values()
        ]


def _fmt(x: float) -> str:
    return f"{x:.4g}"


def _stream(seed: int, *keys: str) -> np.random.Generator:
    """Independent random stream keyed by (seed, keys): adding/removing a site or a parameter does
    not shift any other stream, so scenarios compare on common random numbers."""
    return np.random.default_rng([seed % 2**32, *(zlib.crc32(k.encode()) for k in keys)])


def _tri_ppf(u: FloatArray, low: Any, mid: Any, high: Any) -> FloatArray:
    """Inverse CDF of Triangular(low, mid, high), elementwise; low == high gives the constant."""
    lo = np.asarray(low, dtype=np.float64)
    mo = np.asarray(mid, dtype=np.float64)
    hi = np.asarray(high, dtype=np.float64)
    span = hi - lo
    c = np.where(span > 0, (mo - lo) / np.where(span > 0, span, 1.0), 0.0)
    left = lo + np.sqrt(u * span * (mo - lo))
    right = hi - np.sqrt((1.0 - u) * span * (hi - mo))
    return np.asarray(np.where(u < c, left, right), dtype=np.float64)


def draw_parameter(p: Parameter, seed: int, n: int) -> FloatArray:
    """n triangular(low, mid, high) draws of a parameter, keyed by (seed, parameter id)."""
    return _tri_ppf(_stream(seed, "param", p.id).random(n), p.value_low, p.value_mid, p.value_high)


def _triangular_mean(p: Parameter) -> float:
    return (p.value_low + p.value_mid + p.value_high) / 3.0


def metric_range(x: FloatArray | Sequence[float], unit: Unit) -> MetricRange:
    p10, p50, p90 = np.percentile(np.asarray(x, dtype=np.float64), [10.0, 50.0, 90.0])
    return MetricRange(p10=float(p10), p50=float(p50), p90=float(p90), unit=unit)


# ---------------------------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ForecastDraws:
    """Per-draw recruitment state, consumed by supply.simulate_supply (arrays: D draws × S sites).

    Patients still to come: `new_patients[d]` arrivals between `accrual_start[d, i]` and `t_full[d]`,
    spread over sites ∝ rates[d, i] · (t_full − accrual_start)⁺. Patients already randomised
    (update_with_actuals only): `fixed_counts[d, i]`, uniform over [activation, fixed_until[d]].
    """

    site_ids: tuple[str, ...]
    activation: FloatArray
    accrual_start: FloatArray
    rates: FloatArray
    t_full: FloatArray
    new_patients: IntArray
    fixed_counts: IntArray
    fixed_until: FloatArray
    planned_rate: FloatArray  # (S,) planner's expected patients/month per site (no hindsight)
    dropout: FloatArray
    followup_months: FloatArray
    enrollment_closed_at: FloatArray  # (D,) month the target was reached (= t_full)
    duration: FloatArray  # (D,) study start → database lock, months

    @property
    def n_draws(self) -> int:
        return int(self.t_full.shape[0])

    def take(self, n: int) -> ForecastDraws:
        """The first n draws (supply runs on a subset to stay fast)."""
        n = min(n, self.n_draws)
        return ForecastDraws(
            site_ids=self.site_ids, activation=self.activation[:n],
            accrual_start=self.accrual_start[:n], rates=self.rates[:n], t_full=self.t_full[:n],
            new_patients=self.new_patients[:n], fixed_counts=self.fixed_counts[:n],
            fixed_until=self.fixed_until[:n], planned_rate=self.planned_rate,
            dropout=self.dropout[:n], followup_months=self.followup_months[:n],
            enrollment_closed_at=self.enrollment_closed_at[:n], duration=self.duration[:n],
        )


@dataclass
class ForecastResult:
    months_to_full_enrollment: MetricRange
    duration_months: MetricRange  # enrollment + follow-up (last visit week) + closeout
    milestone_dates: dict[str, MetricRange]  # months from study start, keys = MILESTONES
    enrollment_curve: list[tuple[float, float, float, float]]  # (month, p10, p50, p90) cumulative
    # --- A3 extensions (additive; not part of the shared contract) ---
    patients_to_randomise: MetricRange | None = None  # target inflated for dropout
    warnings: list[str] = field(default_factory=list)
    provenance: list[ProvenanceItem] = field(default_factory=list)
    levers: Levers = field(default_factory=Levers)
    draws: ForecastDraws | None = field(default=None, repr=False, compare=False)

    @property
    def duration_draws(self) -> FloatArray | None:
        """Per-draw duration in months (length = draws); A2's engine uses it directly when the
        draw counts match, keeping the duration ↔ cost correlation."""
        return None if self.draws is None else self.draws.duration

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready view (without the raw draws)."""
        return {
            "months_to_full_enrollment": self.months_to_full_enrollment.model_dump(),
            "duration_months": self.duration_months.model_dump(),
            "milestone_dates": {k: v.model_dump() for k, v in self.milestone_dates.items()},
            "enrollment_curve": [list(row) for row in self.enrollment_curve],
            "patients_to_randomise": (
                self.patients_to_randomise.model_dump() if self.patients_to_randomise else None
            ),
            "warnings": list(self.warnings),
            "provenance": [p.model_dump() for p in self.provenance],
        }


# ---------------------------------------------------------------------------------------------
# Core maths
# ---------------------------------------------------------------------------------------------


def _invert_cumulative_intensity(starts: FloatArray, rates: FloatArray, target: FloatArray) -> FloatArray:
    """Per row d: the t with Σᵢ rates[d,i]·(t − starts[d,i])⁺ = target[d] (inf if unreachable)."""
    order = np.argsort(starts, axis=1, kind="stable")
    s = np.take_along_axis(starts, order, axis=1)
    r = np.take_along_axis(rates, order, axis=1)
    slope = np.cumsum(r, axis=1)  # slope of M on [s_k, s_{k+1})
    m_at = np.zeros_like(s)  # M at each breakpoint
    m_at[:, 1:] = np.cumsum(slope[:, :-1] * np.diff(s, axis=1), axis=1)
    k = (m_at <= target[:, None]).sum(axis=1) - 1
    rows = np.arange(s.shape[0])
    sl = slope[rows, k]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = s[rows, k] + (target - m_at[rows, k]) / sl
    return np.asarray(np.where(sl > 0, t, np.inf), dtype=np.float64)


def _cumulative_intensity(starts: FloatArray, rates: FloatArray, t: float) -> FloatArray:
    return np.asarray((rates * np.clip(t - starts, 0.0, None)).sum(axis=1), dtype=np.float64)


def _bridge_counts(
    m_t: FloatArray, gamma_total: FloatArray, n_total: IntArray, rng: np.random.Generator
) -> FloatArray:
    """Arrivals by a time with intensity m_t, given the n-th arrival is at intensity gamma_total.

    Conditional on Γₙ, the first n−1 arrival intensities are uniform on [0, Γₙ], so the count is
    Binomial(n − 1, M(t)/Γₙ) before the n-th arrival and n from then on (enrolment stops at target).
    """
    n = np.maximum(n_total, 0)
    reached = m_t >= gamma_total
    with np.errstate(divide="ignore", invalid="ignore"):
        p = np.where(gamma_total > 0, np.clip(m_t / gamma_total, 0.0, 1.0), 1.0)
    before = rng.binomial(np.maximum(n - 1, 0), np.where(reached, 0.0, p))
    return np.asarray(np.where(reached, n, before), dtype=np.float64)


def _curve_grid(horizon: float, start: float = 0.0) -> FloatArray:
    horizon = max(horizon, start + 1.0)
    step = max(1.0, math.ceil((horizon - start) / (_MAX_CURVE_POINTS - 1)))
    grid = np.arange(0.0, math.ceil(horizon) + step, step, dtype=np.float64)
    if start > 0 and not np.any(np.isclose(grid, start)):
        grid = np.sort(np.append(grid, start))
    return grid


def _curve_rows(grid: FloatArray, counts: list[FloatArray]) -> list[tuple[float, float, float, float]]:
    rows = []
    for t, c in zip(grid, counts, strict=True):
        p10, p50, p90 = np.percentile(c, [10.0, 50.0, 90.0])
        rows.append((round(float(t), 3), float(p10), float(p50), float(p90)))
    return rows


def estimate_rate_hyperparameters(
    counts: Sequence[float] | FloatArray, exposure_months: Sequence[float] | FloatArray
) -> tuple[float, float]:
    """Method-of-moments fit of the Poisson–gamma model to per-site data → (mean rate, CV).

    kᵢ ~ Poisson(λᵢ τᵢ), λᵢ ~ Gamma(α, mean μ): E kᵢ = μτᵢ, Var kᵢ = μτᵢ + μ²τᵢ²/α.
    μ̂ = Σk/Στ; 1/α̂ = Σ[(kᵢ − μ̂τᵢ)² − μ̂τᵢ] / Σ μ̂²τᵢ² (floored at 0); CV = √(1/α̂).
    Use it to turn historical site performance into `site.enrollment_rate_per_month` (μ̂) and
    `site.enrollment_rate_shape` (α̂ = 1/CV²) parameters.
    """
    k = np.asarray(counts, dtype=np.float64)
    tau = np.asarray(exposure_months, dtype=np.float64)
    if k.shape != tau.shape or k.size == 0:
        raise ForecastError("counts and exposure_months must be non-empty and the same length")
    if np.any(k < 0) or np.any(tau < 0) or tau.sum() <= 0:
        raise ForecastError("counts and exposures must be ≥ 0 with positive total exposure")
    mu = float(k.sum() / tau.sum())
    denom = float((mu**2 * tau**2).sum())
    phi = float(((k - mu * tau) ** 2 - mu * tau).sum() / denom) if denom > 0 else 0.0
    return mu, math.sqrt(max(phi, 0.0))


# ---------------------------------------------------------------------------------------------
# Shared set-up: sites, parameters, structural draws
# ---------------------------------------------------------------------------------------------


@dataclass
class _Setup:
    sites: list[Site]
    weights: FloatArray  # (S,)
    rate_mean: FloatArray  # (D,) mean patients/site/month before site weights
    planned_rate: FloatArray  # (S,)
    alpha: FloatArray  # (D,)
    activation: FloatArray  # (D, S)
    rates: FloatArray  # (D, S) realised prior rates
    n_needed: IntArray  # (D,)
    dropout: FloatArray  # (D,)
    followup: FloatArray  # (D,)
    closeout: FloatArray  # (D,)
    dct_share: float
    resolver: ParameterResolver
    warnings: list[str]
    assumptions: list[str]
    inputs: dict[str, float | str]

    @property
    def n_draws(self) -> int:
        return int(self.rate_mean.shape[0])


def _site_weights(sites: list[Site], warnings: list[str]) -> FloatArray:
    """Relative recruitment weight per site from expected_enrollment (mean 1 over known sites)."""
    known = [s.expected_enrollment for s in sites if s.expected_enrollment and s.expected_enrollment > 0]
    if not known:
        return np.ones(len(sites), dtype=np.float64)
    mean_known = sum(known) / len(known)
    n_unknown = len(sites) - len(known)
    if n_unknown:
        warnings.append(
            f"{n_unknown} of {len(sites)} sites have no expected enrollment; they were given the "
            "average site weight."
        )
    return np.array(
        [
            (s.expected_enrollment / mean_known)
            if s.expected_enrollment and s.expected_enrollment > 0
            else 1.0
            for s in sites
        ],
        dtype=np.float64,
    )


def _schedule_weeks(design: TrialDesign) -> tuple[float, float] | None:
    """(baseline week, last visit week) of the schedule, or None without visits."""
    if not design.visits:
        return None
    weeks = [v.week for v in design.visits]
    on_study = [w for w in weeks if w >= 0]
    baseline = min(on_study) if on_study else 0.0
    return baseline, max(weeks)


def decentralised_share(design: TrialDesign, levers: Levers) -> float:
    """Share of on-study visits (week ≥ baseline) moved to home nursing or telehealth."""
    sched = _schedule_weeks(design)
    if sched is None:
        return 0.0
    on_study = [v for v in design.visits if v.week >= sched[0]]
    if not on_study:
        return 0.0
    moved = set(levers.home_visit_numbers) | set(levers.remote_visit_numbers)
    return sum(v.number in moved for v in on_study) / len(on_study)


def _expected_open_months(window: float, act: Parameter) -> float:
    """E[(window − a)⁺] for a ~ Triangular(site.activation_months), by midpoint quadrature."""
    u = (np.arange(2000, dtype=np.float64) + 0.5) / 2000
    a = _tri_ppf(u, act.value_low, act.value_mid, act.value_high)
    return float(np.clip(window - a, 0.0, None).mean())


def _setup(
    design: TrialDesign, levers: Levers, params: Mapping[str, Parameter], seed: int, draws: int
) -> _Setup:
    if draws < 1:
        raise ForecastError("draws must be at least 1")
    if design.enrollment_target < 1:
        raise ForecastError(
            f"enrollment_target must be at least 1 patient (got {design.enrollment_target})."
        )
    if not design.sites:
        raise ForecastError("The design has no sites; add at least one site to forecast enrollment.")
    excluded = set(levers.excluded_site_ids)
    sites = [s for s in design.sites if s.id not in excluded]
    if not sites:
        raise ForecastError(
            f"All {len(design.sites)} sites are excluded by the levers; keep at least one site to "
            "forecast enrollment."
        )
    warnings: list[str] = []
    assumptions: list[str] = []
    unknown = excluded - {s.id for s in design.sites}
    if unknown:
        warnings.append(f"Excluded site ids not in the design were ignored: {sorted(unknown)}")

    res = ParameterResolver(params, FORECAST_DEFAULTS)
    d = draws
    all_weights = _site_weights(list(design.sites), warnings)
    keep = np.array([s.id not in excluded for s in design.sites])
    weights = all_weights[keep]

    act = res.get("site.activation_months")
    shape_p = res.get("site.enrollment_rate_shape")
    drop_p = res.get("patient.dropout_rate")
    close_p = res.get("trial.closeout_months")
    uplift_p = res.get("lever.decentralised.recruitment_uplift")
    dred_p = res.get("lever.decentralised.dropout_reduction")

    sched = _schedule_weeks(design)
    if sched is not None:
        follow_months = max(0.0, sched[1] - sched[0]) / WEEKS_PER_MONTH
        followup = np.full(d, follow_months)
        follow_mid = follow_months
    else:
        fu_p = res.get("trial.followup_months")
        followup = draw_parameter(fu_p, seed, d)
        follow_mid = fu_p.value_mid
        warnings.append(
            f"The design has no visit schedule; follow-up per patient taken from "
            f"'{fu_p.id}' ({_fmt(fu_p.value_low)}–{_fmt(fu_p.value_high)} months)."
        )

    share = decentralised_share(design, levers)
    dred = draw_parameter(dred_p, seed, d) * share
    uplift = draw_parameter(uplift_p, seed, d) * share
    if share > 0 and dred_p.value_high == 0 and uplift_p.value_high == 0:
        assumptions.append(
            f"{share:.0%} of visits are home/remote; no recruitment or retention benefit assumed "
            "(lever.decentralised.* = 0)."
        )
    dropout = np.clip(draw_parameter(drop_p, seed, d) * (1.0 - dred), 0.0, _MAX_DROPOUT)
    target = design.enrollment_target
    n_needed = np.ceil(target / (1.0 - dropout) - 1e-9).astype(np.int64)
    assumptions.append(
        "Enrollment target treated as patients needed to complete; randomisations inflated by "
        "1/(1 − dropout). Set patient.dropout_rate to 0 if the target already includes dropouts."
    )
    n_mid = math.ceil(target / (1.0 - min(drop_p.value_mid, _MAX_DROPOUT)) - 1e-9)

    # Mean recruitment rate: explicit library value > rate implied by the registered plan > fallback.
    plan_rate: float | None = None
    window = design.duration_months - follow_mid - close_p.value_mid
    if (
        not res.has("site.enrollment_rate_per_month")
        and design.duration_months > 0
        and "duration_months" not in design.missing_fields
        and window > 0
    ):
        open_months = float(all_weights.sum()) * _expected_open_months(window, act)
        if open_months > 0.5:
            plan_rate = n_mid / open_months
    if plan_rate is not None:
        mult_p = res.get("forecast.plan_rate_multiplier")
        rate_mean = plan_rate * draw_parameter(mult_p, seed, d)
        rate_mid = plan_rate * mult_p.value_mid
        assumptions.append(
            f"Mean recruitment rate derived from the registered plan: {n_mid} patients over a "
            f"{window:.1f}-month enrollment window across {len(design.sites)} sites = "
            f"{plan_rate:.3f} patients/site/month (× {mult_p.id})."
        )
        rate_source = "plan"
    else:
        rate_p = res.get("site.enrollment_rate_per_month")
        rate_mean = draw_parameter(rate_p, seed, d)
        rate_mid = rate_p.value_mid
        rate_source = "library" if rate_p.id not in res.fallbacks else "built-in assumption"
        if res.has("site.enrollment_rate_per_month"):
            assumptions.append("Mean recruitment rate taken from site.enrollment_rate_per_month.")
        else:
            warnings.append(
                "Recruitment rate could not be derived from the design (no usable planned duration); "
                "the generic fallback rate is very uncertain."
            )
    rate_mean = rate_mean * (1.0 + uplift)
    rate_mid *= 1.0 + float(uplift_p.value_mid) * share

    alpha = np.maximum(draw_parameter(shape_p, seed, d), 1e-3)
    n_sites = len(sites)
    activation = np.empty((d, n_sites))
    rates = np.empty((d, n_sites))
    for j, site in enumerate(sites):
        u = _stream(seed, "site.activation", site.id).random(d)
        activation[:, j] = _tri_ppf(u, act.value_low, act.value_mid, act.value_high)
        g = _stream(seed, "site.rate", site.id).standard_gamma(alpha)
        rates[:, j] = rate_mean * weights[j] * g / alpha

    inputs: dict[str, float | str] = {
        "sites_active": float(n_sites),
        "sites_excluded": float(len(design.sites) - n_sites),
        "enrollment_target": float(target),
        "patients_to_randomise_mid": float(n_mid),
        "recruitment_rate_mid_per_site_month": round(rate_mid, 4),
        "recruitment_rate_source": rate_source,
        "rate_gamma_shape_mid": shape_p.value_mid,
        "activation_months_low_mid_high": f"{act.value_low}/{act.value_mid}/{act.value_high}",
        "dropout_mid": drop_p.value_mid,
        "decentralised_visit_share": round(share, 4),
        "followup_months_mid": round(follow_mid, 3),
        "closeout_months_mid": close_p.value_mid,
        "draws": float(d),
        "seed": float(seed),
    }
    return _Setup(
        sites=sites, weights=weights, rate_mean=rate_mean,
        planned_rate=rate_mid * weights, alpha=alpha, activation=activation, rates=rates,
        n_needed=n_needed, dropout=dropout, followup=followup,
        closeout=draw_parameter(close_p, seed, d), dct_share=share, resolver=res,
        warnings=warnings, assumptions=assumptions, inputs=inputs,
    )


def _provenance(st: _Setup, extra_assumptions: Sequence[str] = ()) -> list[ProvenanceItem]:
    res = st.resolver
    enrol_ids = [
        pid for pid in (
            "site.activation_months", "site.enrollment_rate_per_month", "forecast.plan_rate_multiplier",
            "site.enrollment_rate_shape", "patient.dropout_rate", "lever.decentralised.recruitment_uplift",
            "lever.decentralised.dropout_reduction",
        ) if pid in res.used
    ]
    common = [
        "Sites recruit independently with constant rates once open; no site caps; rates count "
        "randomisations (screen failures not modelled separately).",
        *st.assumptions,
        *extra_assumptions,
        *(f"'{pid}' not in library — built-in assumption used." for pid in res.fallbacks),
    ]
    dur_ids = [pid for pid in ("trial.followup_months", "trial.closeout_months") if pid in res.used]
    return [
        ProvenanceItem(
            formula_id="forecast.enrollment.poisson_gamma.v1",
            description=(
                "Each open site randomises as a Poisson process with rate λᵢ ~ Gamma(shape α, "
                "mean = rate × site weight), opening at aᵢ ~ Triangular(site.activation_months). "
                "The n-th patient arrives at M⁻¹(Gamma(n, 1)), M(t) = Σ λᵢ·(t − aᵢ)⁺, with "
                "n = ⌈target / (1 − dropout)⌉ (Anisimov & Fedorov 2007)."
            ),
            inputs=dict(st.inputs),
            parameter_ids=enrol_ids,
            assumptions=common,
        ),
        ProvenanceItem(
            formula_id="forecast.duration.v1",
            description=(
                "duration = last patient in + follow-up (last scheduled visit week − baseline week, "
                "÷ 52/12) + closeout (last patient last visit → database lock)."
            ),
            inputs={
                "followup_months_mid": st.inputs["followup_months_mid"],
                "closeout_months_mid": st.inputs["closeout_months_mid"],
            },
            parameter_ids=dur_ids,
            assumptions=[pa for pa in common if "follow-up" in pa or "built-in" in pa],
        ),
    ]


def _milestones(
    fpi: FloatArray, lpi: FloatArray, followup: FloatArray, closeout: FloatArray
) -> tuple[dict[str, MetricRange], FloatArray]:
    lplv = lpi + followup
    dbl = lplv + closeout
    ms = {
        "first_patient_in": metric_range(fpi, "months"),
        "last_patient_in": metric_range(lpi, "months"),
        "last_patient_last_visit": metric_range(lplv, "months"),
        "database_lock": metric_range(dbl, "months"),
    }
    return ms, dbl


def _check_reachable(t_full: FloatArray) -> None:
    if not np.all(np.isfinite(t_full)):
        raise ForecastError(
            "Enrollment can never reach the target: every active site has a zero recruitment rate. "
            "Check site expected enrollment and recruitment-rate parameters."
        )


def _horizon_warning(t_full: FloatArray, warnings: list[str]) -> None:
    p90 = float(np.percentile(t_full, 90))
    if p90 > 120:
        warnings.append(
            f"P90 time to full enrollment is {p90:.0f} months (> 10 years); check the recruitment "
            "rate and the number of sites."
        )


# ---------------------------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------------------------


def forecast(
    design: TrialDesign,
    levers: Levers,
    params: Mapping[str, Parameter],
    seed: int = 7,
    draws: int = 2000,
) -> ForecastResult:
    """Enrollment, milestones and duration as P10/P50/P90 (months from study start)."""
    st = _setup(design, levers, params, seed, draws)
    rng = _stream(seed, "forecast.arrivals")
    e1 = rng.standard_exponential(st.n_draws)
    gamma_n = e1 + rng.standard_gamma(np.maximum(st.n_needed - 1, 0).astype(np.float64))
    t_full = _invert_cumulative_intensity(st.activation, st.rates, gamma_n)
    _check_reachable(t_full)
    fpi = _invert_cumulative_intensity(st.activation, st.rates, e1)
    milestones, dbl = _milestones(fpi, t_full, st.followup, st.closeout)

    grid = _curve_grid(float(np.percentile(t_full, 95)) + 1.0)
    crng = _stream(seed, "forecast.curve")
    c = min(st.n_draws, _CURVE_DRAWS)
    act_c, rates_c = st.activation[:c], st.rates[:c]
    counts = [
        _bridge_counts(_cumulative_intensity(act_c, rates_c, float(t)), gamma_n[:c], st.n_needed[:c], crng)
        for t in grid
    ]
    warnings = st.warnings + st.resolver.warnings()
    _horizon_warning(t_full, warnings)
    draws_out = ForecastDraws(
        site_ids=tuple(s.id for s in st.sites),
        activation=st.activation,
        accrual_start=st.activation,
        rates=st.rates,
        t_full=t_full,
        new_patients=st.n_needed,
        fixed_counts=np.zeros(st.activation.shape, dtype=np.int64),
        fixed_until=np.zeros(st.n_draws),
        planned_rate=st.planned_rate,
        dropout=st.dropout,
        followup_months=st.followup,
        enrollment_closed_at=t_full,
        duration=dbl,
    )
    return ForecastResult(
        months_to_full_enrollment=metric_range(t_full, "months"),
        duration_months=metric_range(dbl, "months"),
        milestone_dates=milestones,
        enrollment_curve=_curve_rows(grid, counts),
        patients_to_randomise=metric_range(st.n_needed.astype(np.float64), "patients"),
        warnings=warnings,
        provenance=_provenance(st),
        levers=levers,
        draws=draws_out,
    )


def _parse_actuals(
    design: TrialDesign,
    sites: list[Site],
    actuals: Mapping[str, Sequence[tuple[float, int]]],
    warnings: list[str],
) -> tuple[float, dict[str, list[tuple[float, int]]]]:
    known = {s.id for s in design.sites}
    active = {s.id for s in sites}
    obs: dict[str, list[tuple[float, int]]] = {}
    for sid, series in actuals.items():
        if sid not in known:
            warnings.append(f"Actuals for unknown site '{sid}' were ignored.")
            continue
        if sid not in active:
            warnings.append(f"Actuals for excluded site '{sid}' were ignored.")
            continue
        pts = sorted((float(m), int(c)) for m, c in series)
        for m, c in pts:
            if m < 0 or c < 0 or not math.isfinite(m):
                raise ForecastError(f"Site '{sid}': months and counts must be ≥ 0 (got {m}, {c}).")
        for (_, c0), (m1, c1) in zip(pts, pts[1:], strict=False):
            if c1 < c0:
                raise ForecastError(
                    f"Site '{sid}': enrolment must be cumulative (non-decreasing); got {c1} at month "
                    f"{m1:g} after {c0}."
                )
        if pts:
            obs[sid] = pts
    t_now = max((pts[-1][0] for pts in obs.values()), default=0.0)
    return t_now, obs


def update_with_actuals(
    prior: ForecastResult,
    design: TrialDesign,
    actual_enrolment_by_site: Mapping[str, Sequence[tuple[float, int]]],
    params: Mapping[str, Parameter],
    seed: int = 7,
) -> ForecastResult:
    """Re-forecast after observing enrolment (conjugate Gamma update per site).

    `actual_enrolment_by_site[site_id]` = [(month since study start, CUMULATIVE patients randomised
    at that site by then), ...]. The data cut-off is the latest month reported by any site.

    Per draw: prior λᵢ ~ Gamma(α, rate β = α/meanᵢ); a site with kᵢ patients over τᵢ open months
    has posterior λᵢ ~ Gamma(α + kᵢ, β + τᵢ), τᵢ = (cut-off − aᵢ)⁺ with aᵢ capped at its first
    recorded patient. Sites without data are not assumed to have zero patients: their enrolment to
    date is drawn from the prior predictive. The remaining n − K patients are forecast from the cut-off.
    """
    levers = prior.levers
    draws = prior.draws.n_draws if prior.draws is not None else 2000
    st = _setup(design, levers, params, seed, draws)
    warnings = list(st.warnings)
    t_now, obs = _parse_actuals(design, st.sites, actual_enrolment_by_site, warnings)
    d, n_sites = st.activation.shape
    rng = _stream(seed, "update.arrivals")

    reported = np.array([s.id in obs for s in st.sites])
    k_obs = np.array([obs[s.id][-1][1] if s.id in obs else 0 for s in st.sites], dtype=np.int64)
    first_pos = np.array(
        [next((m for m, c in obs.get(s.id, []) if c > 0), np.inf) for s in st.sites], dtype=np.float64
    )
    act = np.minimum(st.activation, first_pos[None, :])
    tau = np.clip(t_now - act, 0.0, None)
    beta = st.alpha[:, None] / np.maximum(st.rate_mean[:, None] * st.weights[None, :], 1e-12)

    post = np.empty_like(st.rates)
    k_sim = np.zeros((d, n_sites), dtype=np.int64)
    for j, site in enumerate(st.sites):
        if reported[j]:
            g = _stream(seed, "site.rate.post", site.id).standard_gamma(st.alpha + k_obs[j])
            post[:, j] = g / (beta[:, j] + tau[:, j])
        else:
            post[:, j] = st.rates[:, j]
            k_sim[:, j] = _stream(seed, "site.unreported", site.id).poisson(st.rates[:, j] * tau[:, j])
    k_fixed = np.where(reported[None, :], k_obs[None, :], k_sim)
    k_total = k_fixed.sum(axis=1)
    remaining = np.maximum(st.n_needed - k_total, 0)

    starts = np.maximum(act, t_now)
    e1 = rng.standard_exponential(d)
    gamma_r = e1 + rng.standard_gamma(np.maximum(remaining - 1, 0).astype(np.float64))
    t_full = np.where(remaining > 0, _invert_cumulative_intensity(starts, post, gamma_r), t_now)
    _check_reachable(t_full)

    if k_obs.sum() > 0:
        fpi = np.full(d, float(first_pos.min()))
    else:
        unrep_fpi = _invert_cumulative_intensity(st.activation, st.rates, e1)
        next_fpi = _invert_cumulative_intensity(starts, post, e1)
        fpi = np.where(k_total > 0, np.minimum(unrep_fpi, t_now), next_fpi)
    milestones, dbl = _milestones(fpi, t_full, st.followup, st.closeout)

    # Curve: observed (reported sites) + prior-predictive (unreported) up to the cut-off, then forecast.
    grid = _curve_grid(float(np.percentile(t_full, 95)) + 1.0, start=t_now)
    crng = _stream(seed, "update.curve")
    unrep = ~reported
    m_unrep_now = _cumulative_intensity(st.activation[:, unrep], st.rates[:, unrep], t_now)
    k_unrep = k_sim[:, unrep].sum(axis=1)
    counts: list[FloatArray] = []
    for t in grid:
        if t <= t_now:
            seen = sum(_step_value(obs[s.id], float(t)) for s in st.sites if s.id in obs)
            m_t = _cumulative_intensity(st.activation[:, unrep], st.rates[:, unrep], float(t))
            with np.errstate(divide="ignore", invalid="ignore"):
                p = np.where(m_unrep_now > 0, np.clip(m_t / m_unrep_now, 0.0, 1.0), 1.0)
            counts.append(seen + crng.binomial(k_unrep, p).astype(np.float64))
        else:
            m_t = _cumulative_intensity(starts, post, float(t))
            counts.append(k_total + _bridge_counts(m_t, gamma_r, remaining, crng))

    n_rep = int(reported.sum())
    note = (
        f"Updated with actual enrolment up to month {t_now:g}: {int(k_obs.sum())} patients at "
        f"{n_rep} reporting sites"
        + (
            f"; {n_sites - n_rep} sites without data drawn from the prior predictive (not assumed zero)."
            if n_rep < n_sites
            else "."
        )
    )
    warnings += st.resolver.warnings()
    _horizon_warning(t_full, warnings)
    provenance = _provenance(st, [note])
    provenance.append(
        ProvenanceItem(
            formula_id="forecast.enrollment.posterior_update.v1",
            description=(
                "Conjugate update per site: λᵢ | kᵢ, τᵢ ~ Gamma(α + kᵢ, α/meanᵢ + τᵢ); remaining "
                "n − K patients forecast from the data cut-off with the posterior rates."
            ),
            inputs={
                "data_cutoff_month": t_now,
                "patients_observed": float(k_obs.sum()),
                "sites_reporting": float(n_rep),
                "sites_without_data": float(n_sites - n_rep),
            },
            parameter_ids=[p for p in ("site.enrollment_rate_shape",) if p in st.resolver.used],
            assumptions=[
                "Actuals are cumulative randomisations per site; data cut-off = latest month reported.",
                "Site activation before the cut-off is not observed: drawn from the prior, capped at "
                "the site's first recorded patient.",
            ],
        )
    )
    draws_out = ForecastDraws(
        site_ids=tuple(s.id for s in st.sites),
        activation=act,
        accrual_start=starts,
        rates=post,
        t_full=t_full,
        new_patients=remaining,
        fixed_counts=k_fixed,
        fixed_until=np.full(d, t_now),
        planned_rate=st.planned_rate,
        dropout=st.dropout,
        followup_months=st.followup,
        enrollment_closed_at=t_full,
        duration=dbl,
    )
    return ForecastResult(
        months_to_full_enrollment=metric_range(t_full, "months"),
        duration_months=metric_range(dbl, "months"),
        milestone_dates=milestones,
        enrollment_curve=_curve_rows(grid, counts),
        patients_to_randomise=metric_range(st.n_needed.astype(np.float64), "patients"),
        warnings=[*warnings, note],
        provenance=provenance,
        levers=levers,
        draws=draws_out,
    )


def _step_value(points: list[tuple[float, int]], t: float) -> int:
    """Cumulative count at month t from sorted (month, cumulative) observations (0 before the first)."""
    value = 0
    for m, c in points:
        if m <= t + 1e-9:
            value = c
        else:
            break
    return value

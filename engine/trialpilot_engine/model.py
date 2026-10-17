"""Public engine API: compute_scenario, compare, compare_levers, drivers, missing_parameters.

Pipeline: levers.build_activity (design + levers → activity) → burden / workload / carbon / cost
(activity × parameter draws → per-draw Terms) → totals per module and per metric → P10/P50/P90.
A Term with any unknown (NaN) draw is excluded from totals and named in `warnings`; a total with no
known term at all is NaN ("unknown"), never zero.
"""

from __future__ import annotations

import weakref
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from trialpilot_contracts import CARBON_MODULES, EXCLUDED_BY_DEFAULT_MODULES, param_set_version

from . import burden, carbon, cost, workload
from ._contracts import Levers, MetricRange, ModuleBreakdown, Parameter, ScenarioResult, TrialDesign
from .levers import (
    Context,
    EngineInputError,
    ForecastLike,
    SupplyLike,
    build_activity,
    drug_kits,
)
from .provenance import Metric, ParamStore, Term
from .uncertainty import (
    DEFAULT_DRAWS,
    DEFAULT_SEED,
    FloatArray,
    Unit,
    draws_from_range,
    to_range,
    variance_shares,
)

TOP_METRICS: dict[str, Unit] = {
    "cost_usd": "usd",
    "site_staff_hours": "hours",
    "patient_travel_hours": "hours",
    "co2e_kg": "kg_co2e",
    "duration_months": "months",
    "drug_waste_share": "percent",
}
METRIC_LABEL: dict[Metric, str] = {
    "cost_usd": "Cost",
    "co2e_kg": "Carbon",
    "site_staff_hours": "Site staff time",
    "patient_travel_hours": "Patient time",
}
FORECAST_KEY = "a3.forecast.duration_months"


class DrawsUnavailableError(ValueError):
    """`compare` needs the per-draw values of both results, which only live in this process."""


@dataclass(frozen=True)
class ScenarioDraws:
    """Per-draw values behind a ScenarioResult. Keys: TOP_METRICS, plus `cost_usd.<module>` and
    `co2e_kg.<module>` for every §6 module."""

    seed: int
    n: int
    metrics: dict[str, FloatArray]


_DRAWS: dict[int, tuple[weakref.ref[ScenarioResult], ScenarioDraws]] = {}


def _remember(result: ScenarioResult, draws: ScenarioDraws) -> None:
    key = id(result)

    def forget(_: object, key: int = key) -> None:
        _DRAWS.pop(key, None)

    _DRAWS[key] = (weakref.ref(result, forget), draws)


def scenario_draws(result: ScenarioResult) -> ScenarioDraws | None:
    """Per-draw values of a result computed in this process (None after a JSON round trip)."""
    entry = _DRAWS.get(id(result))
    return entry[1] if entry is not None and entry[0]() is result else None


# ---------------------------------------------------------------- evaluation

def _duration_draws(design: TrialDesign, forecast: ForecastLike | None, seed: int, n: int) -> FloatArray:
    if forecast is None:
        return np.full(n, float(design.duration_months))
    exact = getattr(forecast, "duration_draws", None)
    if isinstance(exact, np.ndarray) and exact.shape == (n,):
        return exact.astype(np.float64)
    return draws_from_range(forecast.duration_months, seed, FORECAST_KEY, n)


def _total(terms: list[Term], n: int) -> FloatArray:
    """Sum of known terms; NaN if there are terms but none is known; 0 if there are none."""
    known = [t.values for t in terms if t.known]
    if not known:
        return np.full(n, np.nan) if terms else np.zeros(n)
    return np.sum(known, axis=0)


def _missing_warning(t: Term) -> str:
    what = ", ".join(f"`{m}`" for m in t.trace.missing) or "an invalid value"
    return (
        f"{METRIC_LABEL[t.metric]} excludes '{t.description}' [{t.formula_id}, module {t.module}]: "
        f"missing parameter(s) {what}. Reported as unknown, not zero; the total is understated."
    )


def _evaluate(
    design: TrialDesign,
    levers: Levers,
    params: Mapping[str, Parameter],
    seed: int,
    draws: int,
    forecast: ForecastLike | None,
    supply: SupplyLike | None,
) -> tuple[ScenarioResult, ScenarioDraws, dict[str, FloatArray]]:
    if draws < 1:
        raise EngineInputError("invalid_request", f"`draws` must be at least 1, got {draws}.")
    ps = ParamStore(params, seed, draws)
    act = build_activity(design, levers, params)
    duration = _duration_draws(design, forecast, seed, draws)
    ctx = Context(act=act, ps=ps, duration_months=duration, supply=supply, seed=seed)

    terms = _all_terms(ctx)

    metrics: dict[str, FloatArray] = {}
    modules: list[ModuleBreakdown] = []
    for module in CARBON_MODULES:
        in_module = [t for t in terms if t.module == module]
        module_cost = _total([t for t in in_module if t.metric == "cost_usd"], draws)
        module_co2e = _total([t for t in in_module if t.metric == "co2e_kg"], draws)
        metrics[f"cost_usd.{module}"] = module_cost
        metrics[f"co2e_kg.{module}"] = module_co2e
        modules.append(ModuleBreakdown(
            module=module,
            cost_usd=to_range(module_cost, "usd"),
            co2e_kg=to_range(module_co2e, "kg_co2e"),
            provenance=[t.provenance(extra_assumptions=act.notes) for t in in_module],
        ))
    counted = [t for t in terms if t.module not in EXCLUDED_BY_DEFAULT_MODULES]
    metric: Metric
    for metric in ("cost_usd", "co2e_kg", "site_staff_hours", "patient_travel_hours"):
        metrics[metric] = _total([t for t in counted if t.metric == metric], draws)
    metrics["duration_months"] = duration
    flow = drug_kits(ctx)
    metrics["drug_waste_share"] = flow.waste_share * 100.0 if flow is not None else np.zeros(draws)

    warnings = [*act.warnings, *(_missing_warning(t) for t in terms if not t.known)]
    warnings.append(
        "Module 'intervention' is excluded (drug manufacture is excluded in the published method); "
        "the 'drug_supply' extension estimates kits separately and is included in the totals."
    )
    if forecast is None:
        warnings.append(
            "Duration is the design's planned duration (no enrollment forecast supplied): a point value."
        )
    if flow is None:
        warnings.append("No drug kits modelled (drug type 'none', no patients or no dispensing visits).")

    result = ScenarioResult(
        design_id=design.id,
        levers=levers,
        cost_usd=to_range(metrics["cost_usd"], "usd"),
        site_staff_hours=to_range(metrics["site_staff_hours"], "hours"),
        patient_travel_hours=to_range(metrics["patient_travel_hours"], "hours"),
        co2e_kg=to_range(metrics["co2e_kg"], "kg_co2e"),
        duration_months=to_range(duration, "months"),
        drug_waste_share=to_range(metrics["drug_waste_share"], "percent"),
        modules=modules,
        warnings=list(dict.fromkeys(warnings)),
        parameter_set_version=param_set_version(params),
        computed_at=datetime.now(UTC),
    )
    inputs = ps.used_draws()
    if forecast is not None and np.ptp(duration) > 0:
        inputs[FORECAST_KEY] = duration
    return result, ScenarioDraws(seed=seed, n=draws, metrics=metrics), inputs


# ---------------------------------------------------------------- public API

def compute_scenario(
    design: TrialDesign,
    levers: Levers,
    params: Mapping[str, Parameter],
    seed: int = DEFAULT_SEED,
    draws: int = DEFAULT_DRAWS,
    forecast: ForecastLike | None = None,
    supply: SupplyLike | None = None,
) -> ScenarioResult:
    """Cost, site staff time, patient time, carbon, duration and drug waste as P10/P50/P90.

    Pure and deterministic for a given seed (except `computed_at`). `forecast` / `supply` are A3's
    ForecastResult / SupplyResult; without them duration is the planned duration and kit waste comes
    from `supply.waste_share.<strategy>`. Raises EngineInputError for designs/levers that cannot be computed.
    """
    result, sd, _ = _evaluate(design, levers, params, seed, draws, forecast, supply)
    _remember(result, sd)
    return result


def compare(a: ScenarioResult, b: ScenarioResult) -> dict[str, MetricRange]:
    """Deltas b − a computed per draw (common random numbers), not P50 − P50.

    Keys: the six headline metrics plus `cost_usd.<module>` and `co2e_kg.<module>`. Both results must
    come from `compute_scenario` in this process with the same seed and draws; otherwise raises
    DrawsUnavailableError — use `compare_levers` (recomputes both) instead.
    """
    da, db = scenario_draws(a), scenario_draws(b)
    if da is None or db is None:
        raise DrawsUnavailableError(
            "Per-draw values are not available for these results (e.g. loaded from storage); "
            "use compare_levers(...) to recompute both scenarios with common random numbers."
        )
    if (da.seed, da.n) != (db.seed, db.n):
        raise DrawsUnavailableError(
            f"Results use different seeds/draws ({da.seed}/{da.n} vs {db.seed}/{db.n}); per-draw "
            "deltas need the same seed and number of draws."
        )
    return {
        key: to_range(db.metrics[key] - da.metrics[key], _unit_of(key))
        for key in da.metrics
        if key in db.metrics
    }


def compare_levers(
    design: TrialDesign,
    levers_a: Levers,
    levers_b: Levers,
    params: Mapping[str, Parameter],
    seed: int = DEFAULT_SEED,
    draws: int = DEFAULT_DRAWS,
    forecast_a: ForecastLike | None = None,
    forecast_b: ForecastLike | None = None,
    supply_a: SupplyLike | None = None,
    supply_b: SupplyLike | None = None,
) -> tuple[ScenarioResult, ScenarioResult, dict[str, MetricRange]]:
    """Compute scenarios A and B with the same seed and return (a, b, compare(a, b))."""
    a = compute_scenario(design, levers_a, params, seed, draws, forecast_a, supply_a)
    b = compute_scenario(design, levers_b, params, seed, draws, forecast_b, supply_b)
    return a, b, compare(a, b)


def drivers(
    design: TrialDesign,
    levers: Levers,
    params: Mapping[str, Parameter],
    metric: str,
    top: int = 5,
    seed: int = DEFAULT_SEED,
    draws: int = DEFAULT_DRAWS,
    forecast: ForecastLike | None = None,
    supply: SupplyLike | None = None,
) -> list[tuple[str, float]]:
    """Top parameters by share of the metric's variance (squared correlation, 0..1), largest first.

    `metric`: a headline metric (`cost_usd`, `co2e_kg`, ...) or `cost_usd.<module>` / `co2e_kg.<module>`.
    The A3 forecast duration appears as `a3.forecast.duration_months` when it varies.
    """
    _, sd, inputs = _evaluate(design, levers, params, seed, draws, forecast, supply)
    if metric not in sd.metrics:
        raise EngineInputError("invalid_metric", f"Unknown metric {metric!r}; valid: {sorted(sd.metrics)}.")
    return variance_shares(sd.metrics[metric], inputs)[:top]


def missing_parameters(
    design: TrialDesign, levers: Levers, params: Mapping[str, Parameter]
) -> list[str]:
    """Parameter ids this design + levers ask for that the library does not have (sorted)."""
    n = 8
    ps = ParamStore(params, DEFAULT_SEED, n)
    act = build_activity(design, levers, params)
    ctx = Context(act=act, ps=ps, duration_months=np.full(n, float(design.duration_months)),
                  supply=None, seed=DEFAULT_SEED)
    _all_terms(ctx)
    return sorted(ps.missing)


def _all_terms(ctx: Context) -> list[Term]:
    return [*burden.terms(ctx), *workload.terms(ctx), *carbon.terms(ctx), *cost.terms(ctx)]


def _unit_of(key: str) -> Unit:
    """'cost_usd.samples' → 'usd'."""
    return TOP_METRICS[key.split(".", 1)[0]]

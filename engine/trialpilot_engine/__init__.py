"""TrialPilot calculation engine: pure functions, no I/O (A2; forecast/supply: A3).

    from trialpilot_engine import compute_scenario, compare, compare_levers, drivers
    result = compute_scenario(design, levers, params, seed=7, draws=2000, forecast=None, supply=None)

A3's forecast and supply simulation live in `trialpilot_engine.forecast` / `trialpilot_engine.supply`.
Formulas, parameters and lever logic: docs/model.md.
"""

from .levers import EngineInputError, ForecastLike, SupplyLike
from .model import (
    DrawsUnavailableError,
    ScenarioDraws,
    compare,
    compare_levers,
    compute_scenario,
    drivers,
    missing_parameters,
    scenario_draws,
)
from .provenance import PARAMETER_CATALOG

__all__ = [
    "compute_scenario",
    "compare",
    "compare_levers",
    "drivers",
    "missing_parameters",
    "scenario_draws",
    "ScenarioDraws",
    "EngineInputError",
    "DrawsUnavailableError",
    "ForecastLike",
    "SupplyLike",
    "PARAMETER_CATALOG",
]

"""Bridge to the calculation engine (A2: compute_scenario / compare_levers / drivers;
A3: forecast + simulate_supply).

There is NO placeholder engine in production code (MASTER §2.1): if the engine is missing or
raises NotImplementedError the API answers 501 `engine_not_ready`. Tests inject a fake engine.

Results are cached in-process by (design hash, levers hash, parameter_set_version, seed, draws).
"""

from __future__ import annotations

import importlib
import inspect
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ._contracts import Levers, MetricRange, Parameter, ScenarioResult, TrialDesign
from .errors import ApiError
from .hashing import sha256_hex

log = logging.getLogger("trialpilot.engine_adapter")

METRICS = (
    "cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg", "duration_months",
    "drug_waste_share",
)  # fmt: skip


@dataclass
class EngineFns:
    compute: Callable[..., Any] | None = None
    compare_levers: Callable[..., Any] | None = None  # recompute a and b, common random numbers
    drivers: Callable[..., Any] | None = None
    forecast: Callable[..., Any] | None = None
    simulate_supply: Callable[..., Any] | None = None
    status: dict[str, str] = field(default_factory=dict)


def load_engine() -> EngineFns:
    fns = EngineFns()
    try:
        eng = importlib.import_module("trialpilot_engine")
    except Exception as exc:
        fns.status["engine"] = f"not_installed: {type(exc).__name__}: {exc}"[:200]
        return fns
    for slot, attr in (("compute", "compute_scenario"), ("compare_levers", "compare_levers"),
                       ("drivers", "drivers")):
        setattr(fns, slot, getattr(eng, attr, None))
        fns.status[attr] = "available" if getattr(fns, slot) else "missing"
    for mod_name, attr, slot in (
        ("trialpilot_engine.forecast", "forecast", "forecast"),
        ("trialpilot_engine.supply", "simulate_supply", "simulate_supply"),
    ):
        try:
            fn = getattr(importlib.import_module(mod_name), attr, None)
        except Exception as exc:
            fns.status[slot] = f"missing: {type(exc).__name__}"
            continue
        setattr(fns, slot, fn)
        fns.status[slot] = "available" if fn else "missing"
    return fns


def _accepts(fn: Callable[..., Any], name: str) -> bool:
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def _not_ready(what: str) -> ApiError:
    return ApiError(
        501, "engine_not_ready",
        f"The calculation engine ({what}) is not available yet. No numbers are shown rather "
        "than placeholder numbers.",
        {"component": what, "owner": "A2/A3"},
    )


def _engine_failure(exc: Exception, what: str) -> ApiError:
    if isinstance(exc, NotImplementedError):
        return _not_ready(what)
    if isinstance(exc, (ValueError, KeyError)):
        # EngineInputError(code, message) and friends: the input cannot be computed -> 422.
        code = getattr(exc, "code", None) or "engine_rejected_input"
        return ApiError(422, str(code), f"The engine could not compute this: {exc}",
                        {"component": what, "exception": type(exc).__name__})
    log.exception("engine error", extra={"component": what})
    return ApiError(500, "engine_error", f"The engine failed while computing ({what}).",
                    {"component": what, "exception": type(exc).__name__})


class ComputeCache:
    def __init__(self, size: int) -> None:
        self.size = size
        self._data: OrderedDict[tuple[Any, ...], ScenarioResult] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: tuple[Any, ...]) -> ScenarioResult | None:
        with self._lock:
            val = self._data.get(key)
            if val is None:
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return val.model_copy(deep=True)

    def put(self, key: tuple[Any, ...], value: ScenarioResult) -> None:
        if self.size <= 0:
            return
        with self._lock:
            self._data[key] = value.model_copy(deep=True)
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)


@dataclass
class ComputeOutcome:
    result: ScenarioResult
    cache_hit: bool
    compute_ms: float


@dataclass
class A3Inputs:
    kwargs: dict[str, Any]  # forecast=..., supply=... for the engine call (only what is available)
    warnings: list[str]


class EngineAdapter:
    def __init__(self, fns: EngineFns, cache_size: int) -> None:
        self.fns = fns
        self.cache = ComputeCache(cache_size)

    @property
    def ready(self) -> bool:
        return self.fns.compute is not None

    @staticmethod
    def cache_key(
        design: TrialDesign, levers: Levers, param_version: str, seed: int, draws: int
    ) -> tuple[Any, ...]:
        return (sha256_hex(design), sha256_hex(levers), param_version, seed, draws)

    # ---------------------------------------------------------------- A3 forecast + supply
    def a3_inputs(
        self, target: Callable[..., Any], design: TrialDesign, levers: Levers,
        params: dict[str, Parameter], seed: int, draws: int,
    ) -> A3Inputs:
        """Run A3's forecast and supply simulation when available and when `target` (an engine
        function) takes them. Failures become honest warnings, never silent defaults."""
        kwargs: dict[str, Any] = {}
        warnings: list[str] = []
        if self.fns.forecast is None or not _accepts(target, "forecast"):
            return A3Inputs(kwargs, warnings)
        try:
            fc = self.fns.forecast(design, levers, params, seed=seed, draws=draws)
            kwargs["forecast"] = fc
        except Exception as exc:
            log.warning("forecast failed", extra={"error": repr(exc)})
            warnings.append(f"Enrollment forecast unavailable ({type(exc).__name__}: {exc}); "
                            "duration is the design's planned duration.")
            return A3Inputs(kwargs, warnings)
        if self.fns.simulate_supply is not None and _accepts(target, "supply"):
            try:
                kwargs["supply"] = self.fns.simulate_supply(design, levers, params, fc, seed=seed)
            except Exception as exc:
                log.warning("supply simulation failed", extra={"error": repr(exc)})
                warnings.append(f"Drug supply simulation unavailable ({type(exc).__name__}: "
                                f"{exc}); kit waste uses the parameter library.")
        return A3Inputs(kwargs, warnings)

    # ---------------------------------------------------------------- compute
    def compute(
        self,
        design: TrialDesign,
        levers: Levers,
        params: dict[str, Parameter],
        param_version: str,
        seed: int,
        draws: int,
    ) -> ComputeOutcome:
        start = time.perf_counter()
        key = self.cache_key(design, levers, param_version, seed, draws)
        cached = self.cache.get(key)
        if cached is not None:
            return ComputeOutcome(cached, True, (time.perf_counter() - start) * 1000)
        compute = self.fns.compute
        if compute is None:
            raise _not_ready("compute_scenario")
        a3 = self.a3_inputs(compute, design, levers, params, seed, draws)
        kwargs: dict[str, Any] = {"seed": seed, **a3.kwargs}
        if _accepts(compute, "draws"):
            kwargs["draws"] = draws
        try:
            result = compute(design, levers, params, **kwargs)
        except Exception as exc:
            raise _engine_failure(exc, "compute_scenario") from exc
        if a3.warnings:
            result = result.model_copy(update={"warnings": [*result.warnings, *a3.warnings]})
        self.cache.put(key, result)
        return ComputeOutcome(result, False, (time.perf_counter() - start) * 1000)

    # ---------------------------------------------------------------- compare
    def compare(
        self,
        design: TrialDesign,
        levers_a: Levers,
        levers_b: Levers,
        params: dict[str, Parameter],
        seed: int,
        draws: int,
    ) -> tuple[dict[str, MetricRange], list[str]]:
        """Per-draw deltas b − a for two lever sets on one design (common random numbers)."""
        fn = self.fns.compare_levers
        if fn is None:
            raise _not_ready("compare_levers")
        target = self.fns.compute or fn
        a3a = self.a3_inputs(target, design, levers_a, params, seed, draws)
        a3b = self.a3_inputs(target, design, levers_b, params, seed, draws)
        kwargs: dict[str, Any] = {"seed": seed, "draws": draws}
        for side, a3 in (("a", a3a), ("b", a3b)):
            for name, value in a3.kwargs.items():
                if _accepts(fn, f"{name}_{side}"):
                    kwargs[f"{name}_{side}"] = value
        try:
            _, _, deltas = fn(design, levers_a, levers_b, params, **kwargs)
        except Exception as exc:
            raise _engine_failure(exc, "compare_levers") from exc
        return dict(deltas), list(dict.fromkeys([*a3a.warnings, *a3b.warnings]))

    # ---------------------------------------------------------------- drivers
    def drivers(
        self,
        design: TrialDesign,
        levers: Levers,
        params: dict[str, Parameter],
        metric: str,
        top: int,
        seed: int,
        draws: int,
    ) -> tuple[list[tuple[str, float]], list[str]]:
        fn = self.fns.drivers
        if fn is None:
            raise _not_ready("drivers")
        a3 = self.a3_inputs(fn, design, levers, params, seed, draws)
        kwargs: dict[str, Any] = {"metric": metric, "top": top, **a3.kwargs}
        for name, value in (("seed", seed), ("draws", draws)):
            if _accepts(fn, name):
                kwargs[name] = value
        try:
            out = fn(design, levers, params, **kwargs)
        except Exception as exc:
            raise _engine_failure(exc, "drivers") from exc
        return [(str(pid), float(share)) for pid, share in out], a3.warnings

"""Bridge to the calculation engine (A2: compute_scenario / compare / drivers; A3: forecast, supply).

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
    compare: Callable[..., Any] | None = None
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
    fns.compute = getattr(eng, "compute_scenario", None)
    fns.compare = getattr(eng, "compare", None)
    fns.drivers = getattr(eng, "drivers", None)
    for name in ("compute", "compare", "drivers"):
        fns.status[name] = "available" if getattr(fns, name) else "missing"
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


def _as_result(obj: Any) -> ScenarioResult:
    if isinstance(obj, ScenarioResult):
        return obj
    if hasattr(obj, "model_dump"):
        return ScenarioResult.model_validate(obj.model_dump(mode="json"))
    return ScenarioResult.model_validate(obj)


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
        # Engine rejected the input (e.g. zero sites, missing parameter): plain-English 422.
        return ApiError(422, "engine_rejected_input", f"The engine could not compute this "
                        f"scenario: {exc}", {"component": what, "exception": type(exc).__name__})
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

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


@dataclass
class ComputeOutcome:
    result: ScenarioResult
    cache_hit: bool
    compute_ms: float


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
        if self.fns.compute is None:
            raise _not_ready("compute_scenario")
        result = self._run_compute(design, levers, params, seed, draws)
        self.cache.put(key, result)
        return ComputeOutcome(result, False, (time.perf_counter() - start) * 1000)

    def _run_compute(
        self,
        design: TrialDesign,
        levers: Levers,
        params: dict[str, Parameter],
        seed: int,
        draws: int,
    ) -> ScenarioResult:
        compute = self.fns.compute
        assert compute is not None
        e_design, e_levers, e_params = design, levers, params
        kwargs: dict[str, Any] = {"seed": seed}
        if _accepts(compute, "draws"):
            kwargs["draws"] = draws
        extra_warnings: list[str] = []
        # A3 forecast/supply: pass them only if A2's compute_scenario takes them as inputs.
        fc = None
        if self.fns.forecast is not None and _accepts(compute, "forecast"):
            try:
                fc = self.fns.forecast(e_design, e_levers, e_params, seed=seed, draws=draws)
                kwargs["forecast"] = fc
            except NotImplementedError:
                extra_warnings.append("Enrollment forecast not available yet (A3); duration "
                                      "uses the design's planned duration.")
            except Exception as exc:
                log.exception("forecast failed")
                extra_warnings.append(f"Enrollment forecast failed ({type(exc).__name__}); "
                                      "duration uses the design's planned duration.")
        if fc is not None and self.fns.simulate_supply is not None and _accepts(compute, "supply"):
            try:
                sp = self.fns.simulate_supply(e_design, e_levers, e_params, fc, seed=seed)
                kwargs["supply"] = sp
            except NotImplementedError:
                extra_warnings.append("Drug supply simulation not available yet (A3).")
            except Exception as exc:
                log.exception("supply simulation failed")
                extra_warnings.append(f"Drug supply simulation failed ({type(exc).__name__}).")
        try:
            raw = compute(e_design, e_levers, e_params, **kwargs)
        except Exception as exc:
            raise _engine_failure(exc, "compute_scenario") from exc
        result = _as_result(raw)
        if extra_warnings:
            result = result.model_copy(update={"warnings": [*result.warnings, *extra_warnings]})
        return result

    def compare(self, a: ScenarioResult, b: ScenarioResult) -> dict[str, MetricRange]:
        if self.fns.compare is None:
            raise _not_ready("compare")
        try:
            out = self.fns.compare(a, b)
        except Exception as exc:
            raise _engine_failure(exc, "compare") from exc
        return {
            k: v if isinstance(v, MetricRange) else MetricRange.model_validate(
                v.model_dump() if hasattr(v, "model_dump") else v)
            for k, v in dict(out).items()
        }

    def drivers(
        self,
        design: TrialDesign,
        levers: Levers,
        params: dict[str, Parameter],
        metric: str,
        top: int,
        seed: int,
        draws: int,
    ) -> list[tuple[str, float]]:
        if self.fns.drivers is None:
            raise _not_ready("drivers")
        e_design, e_levers, e_params = design, levers, params
        kwargs: dict[str, Any] = {"metric": metric, "top": top}
        if _accepts(self.fns.drivers, "seed"):
            kwargs["seed"] = seed
        if _accepts(self.fns.drivers, "draws"):
            kwargs["draws"] = draws
        try:
            out = self.fns.drivers(e_design, e_levers, e_params, **kwargs)
        except Exception as exc:
            raise _engine_failure(exc, "drivers") from exc
        return [(str(pid), float(share)) for pid, share in out]

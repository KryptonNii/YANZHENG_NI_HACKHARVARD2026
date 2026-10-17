"""Bridge to the calculation engine (A2: compute_scenario / compare_levers / drivers;
A3: forecast + simulate_supply).

There is NO placeholder engine in production code (MASTER §2.1): if the engine is missing or
raises NotImplementedError the API answers 501 `engine_not_ready`. Tests inject a fake engine.

Results are cached in-process by (design hash, levers hash, parameter_set_version, seed, draws).
At most `max_concurrency` engine runs execute at once (numpy work in threads contends for the GIL;
measured: 4 parallel runs were slower in total than queueing them), the rest wait for a slot.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError
from trialpilot_contracts.params import param_set_version

from ._contracts import (
    ForecastView,
    Levers,
    MetricRange,
    Parameter,
    ScenarioResult,
    SupplyView,
    TrialDesign,
)
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


_FORECAST_KEYS = (
    "months_to_full_enrollment", "milestone_dates", "enrollment_curve",
    "draws_requested", "draws_used", "curve_draws_used", "provenance",
)
_SUPPLY_KEYS = (
    "kits_needed", "kits_produced", "kits_wasted", "waste_share", "shipments",
    "stockout_probability",
    "draws_requested", "draws_used", "provenance",
)


def _producer_dict(obj: Any) -> dict[str, Any] | None:
    """Display subset source. A3's `to_dict()`; a bare dict is accepted in tests."""
    if obj is None:
        return None
    to_dict = getattr(obj, "to_dict", None)
    raw = to_dict() if callable(to_dict) else obj
    return raw if isinstance(raw, dict) else None


def _subset(raw: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: raw[key] for key in keys if key in raw}


def _fit_view(model: type[Any], data: dict[str, Any]) -> Any | None:
    try:
        return model.model_validate(data)
    except ValidationError:
        return None


def _sampling_notes(supply: Any) -> list[str]:
    """The producer's own statement of how many draws the supply ranges used.

    Prefer A3's warning or provenance sentence. Only if those are absent, name
    `draws_used` — the count the simulation actually ran, not the scenario's draw request.
    """
    if supply is None:
        return []
    found: list[str] = []
    blobs: list[Any] = []
    warnings = getattr(supply, "warnings", None)
    if isinstance(warnings, list):
        blobs.extend(warnings)
    for item in getattr(supply, "provenance", []) or []:
        assumptions = getattr(item, "assumptions", None)
        if isinstance(assumptions, list):
            blobs.extend(assumptions)
    for text in blobs:
        if isinstance(text, str) and "draw" in text.lower() and text not in found:
            found.append(text)
    if found:
        return found
    used = getattr(supply, "draws_used", None)
    if isinstance(used, int) and used > 0:
        return [f"Drug supply simulated on {used} forecast draws."]
    return []


def _with_a3_views(result: ScenarioResult, forecast: Any, supply: Any) -> ScenarioResult:
    """Attach contract v4 forecast/supply from the producer display subset.

    Extra producer keys are dropped. A value that does not validate is left null
    and named in warnings — percentiles are never rewritten to 0, and shipment
    counts keep the unit the producer sent (`count`, not `kits`).
    """
    extra: list[str] = []
    update: dict[str, Any] = {}
    forecast_raw = _producer_dict(forecast)
    if forecast_raw is not None:
        data = _subset(forecast_raw, _FORECAST_KEYS)
        view = _fit_view(ForecastView, data)
        if view is None and "enrollment_curve" in data:
            view = _fit_view(ForecastView, {k: v for k, v in data.items() if k != "enrollment_curve"})
            if view is not None:
                extra.append(
                    "Enrollment curve omitted: a row was not four finite numbers. "
                    "Missing points are not shown as zero."
                )
        if view is None:
            extra.append(
                "Enrollment forecast detail omitted: it did not match the contract. "
                "Unknown stays unreported, not zero."
            )
        else:
            update["forecast"] = view
    supply_raw = _producer_dict(supply)
    if supply_raw is not None:
        view = _fit_view(SupplyView, _subset(supply_raw, _SUPPLY_KEYS))
        if view is None:
            extra.append(
                "Drug supply detail omitted: it did not match the contract. "
                "Unknown stays unreported, not zero."
            )
        else:
            update["supply"] = view
    extra.extend(_sampling_notes(supply))
    for raw in (forecast_raw, supply_raw):
        if raw:
            extra.extend(w for w in raw.get("warnings", []) if isinstance(w, str))
    if not update and not extra:
        return result
    warnings = list(dict.fromkeys([*result.warnings, *extra]))
    return result.model_copy(update={**update, "warnings": warnings})


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


class _LRU:
    """Tiny thread-safe LRU for A3 results (treated as immutable, so no copies)."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._data: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[Any, ...]) -> Any:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]
            return None

    def put(self, key: tuple[Any, ...], value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)


# Levers A3's forecast/supply do not read (checked against forecast.py / supply.py, 21:40 ET).
# Listing the EXCLUDED fields means a lever field added later is part of the A3 cache key by default.
NOT_READ_BY_A3 = {"remote_monitoring_share", "local_lab_share", "removed_procedures"}


@dataclass
class ComputeOutcome:
    result: ScenarioResult
    cache_hit: bool
    compute_ms: float  # whole call, including queue_ms
    queue_ms: float = 0.0  # time spent waiting for a free engine slot


@dataclass
class A3Inputs:
    kwargs: dict[str, Any]  # forecast=..., supply=... for the engine call (only what is available)
    warnings: list[str]


class EngineAdapter:
    def __init__(self, fns: EngineFns, cache_size: int, max_concurrency: int = 2) -> None:
        self.fns = fns
        self.cache = ComputeCache(cache_size)
        self._a3_cache = _LRU(64)
        self._slots = threading.BoundedSemaphore(max(1, max_concurrency))

    @contextmanager
    def _slot(self) -> Iterator[float]:
        """Wait for an engine slot; yields the milliseconds spent waiting."""
        t = time.perf_counter()
        with self._slots:
            yield (time.perf_counter() - t) * 1000

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
        function) takes them. Failures become honest warnings, never silent defaults.

        Both are cached on the inputs A3 reads: every lever except the ones in
        NOT_READ_BY_A3, so a remote-monitoring slider drag never re-runs the ~1 s supply
        simulation, while the supply strategy toggle re-runs supply but reuses the forecast."""
        kwargs: dict[str, Any] = {}
        warnings: list[str] = []
        if self.fns.forecast is None or not _accepts(target, "forecast"):
            return A3Inputs(kwargs, warnings)
        a3_levers = levers.model_dump(exclude=NOT_READ_BY_A3)
        base_key = (sha256_hex(design), param_set_version(params), seed, draws)
        fc_key = (*base_key, sha256_hex({k: v for k, v in a3_levers.items()
                                         if k != "drug_supply_strategy"}))
        fc = self._a3_cache.get(("forecast", *fc_key))
        if fc is None:
            try:
                fc = self.fns.forecast(design, levers, params, seed=seed, draws=draws)
            except Exception as exc:
                log.warning("forecast failed", extra={"error": repr(exc)})
                warnings.append(f"Enrollment forecast unavailable ({type(exc).__name__}: {exc}); "
                                "duration is the design's planned duration.")
                return A3Inputs(kwargs, warnings)
            self._a3_cache.put(("forecast", *fc_key), fc)
        kwargs["forecast"] = fc
        if self.fns.simulate_supply is not None and _accepts(target, "supply"):
            sp_key = ("supply", *fc_key, levers.drug_supply_strategy)
            sp = self._a3_cache.get(sp_key)
            if sp is None:
                try:
                    sp = self.fns.simulate_supply(design, levers, params, fc, seed=seed)
                except Exception as exc:
                    log.warning("supply simulation failed", extra={"error": repr(exc)})
                    warnings.append(f"Drug supply simulation unavailable ({type(exc).__name__}: "
                                    f"{exc}); kit waste uses the parameter library.")
                    return A3Inputs(kwargs, warnings)
                self._a3_cache.put(sp_key, sp)
            kwargs["supply"] = sp
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
        with self._slot() as queue_ms:
            cached = self.cache.get(key)  # an identical request may have finished meanwhile
            if cached is not None:
                return ComputeOutcome(cached, True, (time.perf_counter() - start) * 1000,
                                      queue_ms)
            a3 = self.a3_inputs(compute, design, levers, params, seed, draws)
            kwargs: dict[str, Any] = {"seed": seed, **a3.kwargs}
            if _accepts(compute, "draws"):
                kwargs["draws"] = draws
            try:
                result = compute(design, levers, params, **kwargs)
            except Exception as exc:
                raise _engine_failure(exc, "compute_scenario") from exc
        result = _with_a3_views(result, a3.kwargs.get("forecast"), a3.kwargs.get("supply"))
        if a3.warnings:
            result = result.model_copy(update={
                "warnings": list(dict.fromkeys([*result.warnings, *a3.warnings]))})
        self.cache.put(key, result)
        return ComputeOutcome(result, False, (time.perf_counter() - start) * 1000, queue_ms)

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
            with self._slot():
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
            with self._slot():
                out = fn(design, levers, params, **kwargs)
        except Exception as exc:
            raise _engine_failure(exc, "drivers") from exc
        return [(str(pid), float(share)) for pid, share in out], a3.warnings

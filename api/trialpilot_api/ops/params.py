"""Ops parameters: `data/fixtures/ops/ops_params.yaml` (all assumptions) + sourced overrides from A10's library.

`OpsParams.draws(pid, n)` samples triangular(low, mid, high) with common random numbers keyed by
(seed, parameter id), so plan and actual use the same draws and results are reproducible.
"""

from __future__ import annotations

import os
import zlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from ._contracts import Parameter, ProvenanceItem

# ops id -> preferred id in A10's sourced library (data/params). Used when present there.
LIBRARY_ALIASES: dict[str, str] = {
    "ops.ef.car_km": "ef.travel.car.average_km",
    "ops.ef.rail_pkm": "ef.travel.rail.national_pkm",
    "ops.ef.flight_pkm": "ef.travel.flight.short_haul_pkm",
    "ops.ef.freight_road_tkm": "ef.freight.van.average_tkm",
    "ops.ef.freight_air_tkm": "ef.freight.air.average_tkm",
    "ops.cost.monitoring_site_day": "cost.monitoring.onsite_visit",
    "ops.cost.site_visit_fee": "cost.site.visit_fee",
    "ops.cost.drug_kit": "cost.drug_supply.kit",
}


def repo_root() -> Path:
    env = os.environ.get("TP_REPO_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data" / "fixtures" / "ops").is_dir():
            return parent
    return here.parents[3]


def ops_data_dir() -> Path:
    env = os.environ.get("TP_OPS_DATA_DIR")
    return Path(env) if env else repo_root() / "data" / "fixtures" / "ops"


def _load_yaml_params(path: Path) -> dict[str, Parameter]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = doc.get("defaults") or {}
    out: dict[str, Parameter] = {}
    for raw in doc.get("parameters") or []:
        p = Parameter.model_validate({**defaults, **raw})
        if not p.value_low <= p.value_mid <= p.value_high:
            raise ValueError(f"{p.id}: need low <= mid <= high")
        if p.assumption and not (p.rationale or "").strip():
            raise ValueError(f"{p.id}: assumption=true requires a rationale")
        out[p.id] = p
    return out


def _load_library() -> dict[str, Parameter]:
    """A10's sourced library, if present and valid. Never fatal: ops falls back to its assumptions."""
    lib_dir = repo_root() / "data" / "params"
    if not lib_dir.is_dir():
        return {}
    try:
        from trialpilot_contracts.params import load_params  # type: ignore[import-not-found]

        return {k: Parameter.model_validate(v.model_dump()) for k, v in load_params(lib_dir).items()}
    except Exception:  # library half-built or contracts package absent: use assumptions only
        return {}


@dataclass
class OpsParams:
    params: dict[str, Parameter]
    resolved_from: dict[str, str] = field(default_factory=dict)  # ops id -> library id actually used
    seed: int = 0

    def get(self, pid: str) -> Parameter:
        return self.params[pid]

    def mid(self, pid: str) -> float:
        return self.params[pid].value_mid

    def draws(self, pid: str, n: int, seed: int | None = None) -> np.ndarray:
        p = self.params[pid]
        rng = np.random.default_rng([self.seed if seed is None else seed, zlib.crc32(pid.encode())])
        if p.value_low == p.value_high:
            return np.full(n, p.value_mid)
        return rng.triangular(p.value_low, p.value_mid, p.value_high, size=n)

    def source_note(self, pid: str) -> str:
        p = self.params[pid]
        lib = self.resolved_from.get(pid)
        if lib:
            return f"{pid} <- {lib} ({p.source_title or p.source_url}, {p.source_year})"
        return f"{pid}: ASSUMPTION — {p.rationale}"

    def provenance(
        self,
        formula_id: str,
        description: str,
        inputs: dict[str, float | str],
        pids: list[str],
        extra_assumptions: list[str] | None = None,
    ) -> ProvenanceItem:
        ids = [self.resolved_from.get(p, p) for p in pids]
        assumptions = [self.source_note(p) for p in pids if self.params[p].assumption]
        return ProvenanceItem(
            formula_id=formula_id,
            description=description,
            inputs=inputs,
            parameter_ids=ids,
            assumptions=assumptions + list(extra_assumptions or []),
        )


@lru_cache(maxsize=4)
def _cached(path_str: str, use_library: bool) -> tuple[dict[str, Parameter], dict[str, str]]:
    params = _load_yaml_params(Path(path_str))
    resolved: dict[str, str] = {}
    if use_library:
        lib = _load_library()
        for ops_id, lib_id in LIBRARY_ALIASES.items():
            if ops_id in params and lib_id in lib and not lib[lib_id].assumption:
                src = lib[lib_id]
                if src.unit.replace(" ", "") != params[ops_id].unit.replace(" ", ""):
                    continue  # unit mismatch: keep the ops assumption rather than mix units

                params[ops_id] = src.model_copy(update={"id": ops_id})
                resolved[ops_id] = lib_id
    return params, resolved


def load_ops_params(seed: int = 0, use_library: bool = True) -> OpsParams:
    params, resolved = _cached(str(ops_data_dir() / "ops_params.yaml"), use_library)
    return OpsParams(params=dict(params), resolved_from=dict(resolved), seed=seed)

"""The compute cache keys A3's forecast/supply on every lever except NOT_READ_BY_A3. If A3 ever
read one of those levers, a cached forecast or supply result would be reused for a different
input without any error. This pins the assumption against the real engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trialpilot_contracts.models import Levers, TrialDesign
from trialpilot_engine.forecast import forecast
from trialpilot_engine.supply import simulate_supply

from trialpilot_api.engine_adapter import NOT_READ_BY_A3
from trialpilot_api.params_store import load_library

REPO = Path(__file__).resolve().parents[2]


def _strip(x: Any) -> dict[str, Any]:
    return {k: v for k, v in x.to_dict().items() if k != "computed_at"}


def test_a3_ignores_the_levers_left_out_of_its_cache_key() -> None:
    params = load_library(REPO / "data" / "params")
    raw = json.loads((REPO / "data/fixtures/trials/NCT03930732.json").read_text(encoding="utf-8"))
    design = TrialDesign.model_validate(raw.get("design", raw))
    codes = sorted({p.code for v in design.visits for p in v.procedures})
    changed = {"remote_monitoring_share": 1.0, "local_lab_share": 1.0, "removed_procedures": codes}
    assert set(changed) == NOT_READ_BY_A3  # a newly excluded lever must be added here too

    base, other = Levers(), Levers(**changed)
    fa = forecast(design, base, params, seed=7, draws=200)
    fb = forecast(design, other, params, seed=7, draws=200)
    assert _strip(fa) == _strip(fb)
    sa = simulate_supply(design, base, params, fa, seed=7)
    sb = simulate_supply(design, other, params, fb, seed=7)
    assert _strip(sa) == _strip(sb)

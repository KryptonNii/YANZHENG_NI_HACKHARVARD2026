"""A2 only: `compute_scenario` with no forecast and no supply.

2,000 draws, 120 sites, 900 patients, 12 visits, under 300 ms. This does not time A3's enrollment
forecast or drug-supply simulation, and it does not time the API. Those run before `compute_scenario`
on a request, so a pass here is not a pass for the whole route.
Skipped when TP_SKIP_PERF=1 (slow CI machines)."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import pytest
from trialpilot_contracts import Levers, Parameter, TrialDesign

from trialpilot_engine import compute_scenario

pytestmark = pytest.mark.skipif(os.environ.get("TP_SKIP_PERF") == "1", reason="TP_SKIP_PERF=1")


def test_compute_scenario_under_300_ms(large: Callable[..., TrialDesign], ranged_params: dict[str, Parameter]) -> None:
    design = large(n_sites=120, patients=900, n_visits=12)
    levers = Levers(remote_monitoring_share=0.5, home_visit_numbers=[3, 6, 9], local_lab_share=0.3,
                    drug_supply_strategy="on_demand", removed_procedures=["ecg"])
    compute_scenario(design, levers, ranged_params, draws=2000)  # warm-up (imports, caches)
    timings = []
    for _ in range(5):
        start = time.perf_counter()
        compute_scenario(design, levers, ranged_params, draws=2000)
        timings.append(time.perf_counter() - start)
    median_ms = sorted(timings)[len(timings) // 2] * 1000
    assert median_ms < 300, f"median {median_ms:.0f} ms"

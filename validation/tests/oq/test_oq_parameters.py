"""OQ: the parameter library loads, every value is sourced or a labelled assumption, and emission
factors are physically plausible for their stated unit (catches g-vs-kg style unit errors).

The plausibility ceilings are deliberately loose sanity bounds (an ASSUMPTION, not a source): they
only need to separate a kg factor from the same number in grams (x1000).
"""

from __future__ import annotations

from pathlib import Path

import pytest

PARAMS_DIR = Path(__file__).resolve().parents[3] / "data" / "params"

# unit -> (exclusive lower bound, inclusive upper bound) for value_low/mid/high, in that unit.
PLAUSIBLE: dict[str, tuple[float, float]] = {
    "kg_co2e/km": (0.0, 2.0),  # per vehicle-km; heaviest cars are < 0.5
    "kg_co2e/passenger_km": (0.0, 2.0),  # long-haul flights with RF are < 0.5
    "kg_co2e/tonne_km": (0.0, 10.0),  # air freight is the highest at a few kg
    "kg_co2e/kwh": (0.0, 1.5),  # coal-heavy grids are ~1
    "kg_co2e/kg": (0.0, 50.0),  # common packaging materials are < 10
    "kg_co2e/room_night": (0.0, 200.0),  # hotel nights are tens of kg
}


@pytest.fixture(scope="module")
def params() -> dict:  # type: ignore[type-arg]
    from trialpilot_contracts.params import load_params

    if not PARAMS_DIR.exists():
        pytest.skip("data/params not present")
    return load_params(PARAMS_DIR)


@pytest.mark.req("URS-003")
def test_parameter_library_loads_and_is_sourced(params: dict) -> None:  # type: ignore[type-arg]
    assert params, "parameter library is empty"
    for pid, p in params.items():
        assert p.value_low <= p.value_mid <= p.value_high, pid
        if p.assumption:
            assert p.rationale and p.rationale.strip(), f"{pid}: assumption without rationale"
        else:
            assert p.source_title or p.source_url, f"{pid}: no source and not an assumption"


@pytest.mark.req("URS-003", "URS-008")
def test_emission_factors_are_plausible_for_their_unit(params: dict) -> None:  # type: ignore[type-arg]
    checked = 0
    implausible = []
    for pid, p in params.items():
        bounds = PLAUSIBLE.get(p.unit)
        if bounds is None or not pid.startswith("ef."):
            continue
        lo, hi = bounds
        checked += 1
        for name in ("value_low", "value_mid", "value_high"):
            v = getattr(p, name)
            if not (lo < v <= hi):
                implausible.append(f"{pid}.{name}={v} {p.unit} (expected {lo} < v <= {hi})")
    assert checked >= 5, f"only {checked} emission factors had a checkable unit"
    assert implausible == []

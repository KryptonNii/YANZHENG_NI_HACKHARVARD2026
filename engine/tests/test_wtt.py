"""Well-to-tank (WTT) twins of the travel and freight terms (tiny design, TEST parameters from conftest).

The published method adds DESNZ WTT to every travel and freight factor; the engine keeps WTT as a separate
term `carbon.<name>_wtt.v1` per direct term, so a missing `ef.wtt.*` makes only the twin unknown.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from trialpilot_contracts import Levers, Parameter, ScenarioResult, TrialDesign

from trialpilot_engine import PARAMETER_CATALOG, compute_scenario, missing_parameters
from trialpilot_engine.carbon import WTT_FACTOR

TWINNED = ("patient_travel", "monitoring_trips", "investigator_meeting", "site_initiation_trips",
           "closeout_trips", "sample_freight", "drug_shipping")


def items(r: ScenarioResult) -> dict[str, tuple[str, float | None]]:
    """formula_id → (module, P50 of the term or None when unknown)."""
    out: dict[str, tuple[str, float | None]] = {}
    for m in r.modules:
        for p in m.provenance:
            p50 = p.inputs.get("result_p50")
            out[p.formula_id] = (m.module, p50 if isinstance(p50, float) else None)
    return out


def test_every_travel_and_freight_term_has_a_wtt_twin_in_its_module(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    by_id = items(compute_scenario(tiny(), Levers(), unit_params, draws=5))
    for name in TWINNED:
        module, _ = by_id[f"carbon.{name}.v1"]
        assert by_id[f"carbon.{name}_wtt.v1"][0] == module
    # hand-computed twins: patient km 600 × 0.0325; 6 car trips × 200 km × 0.05; kickoff 2 × 1000 × 0.03;
    # frozen 25 tonne-km × 0.5 + ambient 10 tonne-km × 0.15; kit shipping 40 tonne-km × 0.15
    expected = {"patient_travel": 19.5, "monitoring_trips": 60.0, "investigator_meeting": 60.0,
                "site_initiation_trips": 10.0, "closeout_trips": 10.0, "sample_freight": 14.0,
                "drug_shipping": 6.0}
    for name, kg in expected.items():
        assert by_id[f"carbon.{name}_wtt.v1"][1] == pytest.approx(kg), name


def test_wtt_adds_to_the_total_and_names_its_parameters(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    with_wtt = compute_scenario(tiny(), Levers(), unit_params, draws=5)
    # direct carbon of the worked example (docs/model.md §8) + Σ twins above = 3570.2 + 179.5
    assert with_wtt.co2e_kg.p50 == pytest.approx(3570.2 + 179.5, abs=0.05)
    prov = next(m for m in with_wtt.modules if m.module == "samples").provenance
    twin = next(p for p in prov if p.formula_id == "carbon.sample_freight_wtt.v1")
    assert {"ef.wtt.freight.air.long_haul.tonne_km", "ef.wtt.freight.van.tonne_km"} <= set(twin.parameter_ids)
    assert "ef.freight.van.tonne_km" not in twin.parameter_ids  # the twin uses WTT factors only
    assert any("well-to-tank" in a.lower() for a in twin.assumptions)


def test_missing_wtt_factor_is_unknown_not_zero_and_spares_the_direct_term(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    full = compute_scenario(tiny(), Levers(), unit_params, draws=5)
    params = {k: v for k, v in unit_params.items() if k != "ef.wtt.freight.van.tonne_km"}
    r = compute_scenario(tiny(), Levers(), params, draws=5)
    by_id = items(r)
    # sample-freight twin (14 kg) and kit-shipping twin (6 kg) become unknown and are excluded
    assert by_id["carbon.sample_freight_wtt.v1"][1] is None
    assert by_id["carbon.drug_shipping_wtt.v1"][1] is None
    assert by_id["carbon.sample_freight.v1"][1] == pytest.approx(56.0)  # direct term still counted
    assert r.co2e_kg.p50 == pytest.approx(full.co2e_kg.p50 - 14.0 - 6.0)
    for formula in ("carbon.sample_freight_wtt.v1", "carbon.drug_shipping_wtt.v1"):
        assert any("`ef.wtt.freight.van.tonne_km`" in w and formula in w for w in r.warnings)
    assert missing_parameters(tiny(), Levers(), params) == ["ef.wtt.freight.van.tonne_km"]


def test_wtt_mapping_covers_every_direct_travel_and_freight_factor() -> None:
    direct = {k for k in PARAMETER_CATALOG if k.startswith(("ef.travel.", "ef.freight."))}
    assert set(WTT_FACTOR) == direct
    assert all(v in PARAMETER_CATALOG and v.startswith("ef.wtt.") for v in WTT_FACTOR.values())
    assert {k for k in PARAMETER_CATALOG if k.startswith("ef.wtt.")} == set(WTT_FACTOR.values())


TRAVEL_FREIGHT = (
    "patient_travel", "home_nurse_travel", "monitoring_trips", "investigator_meeting",
    "site_initiation_trips", "closeout_trips", "sample_freight", "drug_shipping",
)


def test_wtt_replaces_the_direct_factor_and_is_not_a_second_copy(
    tiny: Callable[..., TrialDesign], unit_params: dict[str, Parameter]
) -> None:
    """A twin uses only `ef.wtt.*`. It does not also multiply by the direct factor, and the direct term
    does not also multiply by `ef.wtt.*`. Home nurse is absent from the default design, so it is checked
    on the home-visit lever."""
    runs = (
        compute_scenario(tiny(), Levers(), unit_params, draws=5),
        compute_scenario(tiny(), Levers(home_visit_numbers=[2]), unit_params, draws=5),
    )
    direct_ef, wtt_ef = set(WTT_FACTOR), set(WTT_FACTOR.values())
    seen: set[str] = set()
    for r in runs:
        for m in r.modules:
            for p in m.provenance:
                ids = set(p.parameter_ids)
                if p.formula_id.endswith("_wtt.v1"):
                    seen.add(p.formula_id)
                    assert not (ids & direct_ef), p.formula_id
                    assert ids & wtt_ef, p.formula_id
                else:
                    name = p.formula_id.removeprefix("carbon.").removesuffix(".v1")
                    if name in TRAVEL_FREIGHT:
                        assert not (ids & wtt_ef), p.formula_id
    assert seen == {f"carbon.{name}_wtt.v1" for name in TRAVEL_FREIGHT}
    base, home = items(runs[0]), items(runs[1])
    # single-factor terms: twin / direct = WTT factor / direct factor (substitution, not direct + direct)
    assert base["carbon.monitoring_trips_wtt.v1"][1] == pytest.approx(60.0)
    assert base["carbon.monitoring_trips.v1"][1] == pytest.approx(240.0)
    ship_wtt = base["carbon.drug_shipping_wtt.v1"][1]
    ship_direct = base["carbon.drug_shipping.v1"][1]
    assert ship_wtt is not None and ship_direct is not None
    assert ship_wtt / ship_direct == pytest.approx(0.15 / 0.6)
    assert home["carbon.home_nurse_travel.v1"][1] == pytest.approx(80.0)
    assert home["carbon.home_nurse_travel_wtt.v1"][1] == pytest.approx(20.0)

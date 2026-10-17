"""The parameter library (data/params, owner A10): valid, sourced, and complete for the engine."""

from __future__ import annotations

import re

import pytest
import yaml
from trialpilot_contracts import load_params

from trialpilot_science import paths
from trialpilot_science.library import load_factor_map

PARAMS = load_params(paths.PARAMS_DIR)


def test_library_loads_and_is_not_trivial() -> None:
    assert len(PARAMS) >= 150


def test_every_sourced_parameter_has_url_and_year() -> None:
    bad = [p.id for p in PARAMS.values() if not p.assumption and not (p.source_url and p.source_year)]
    assert bad == []


def test_every_assumption_has_a_rationale_and_a_range_or_reason() -> None:
    for p in PARAMS.values():
        if p.assumption:
            assert p.rationale and len(p.rationale) > 20, p.id


def test_no_example_parameters_leak_into_the_library() -> None:
    assert not [pid for pid in PARAMS if pid.startswith("example.")]


def test_shares_are_fractions() -> None:
    for p in PARAMS.values():
        if p.unit == "share":
            assert 0.0 <= p.value_low <= p.value_high <= 1.0, p.id


def test_flight_factors_include_radiative_forcing_consistently() -> None:
    # With-RF factors are larger than the DESNZ 2026 without-RF values (domestic 0.13552, short 0.07559,
    # long 0.09043, international 0.0842) - guards against mixing columns.
    without_rf = {"domestic": 0.13552, "short_haul": 0.07559, "long_haul": 0.09043, "international": 0.0842}
    for band, no_rf in without_rf.items():
        assert PARAMS[f"ef.travel.flight.{band}.passenger_km"].value_mid > no_rf * 1.5


def test_factor_map_and_overrides_point_at_existing_parameters() -> None:
    fmap = load_factor_map(paths.FACTOR_MAP)
    missing = sorted({pid for spec in fmap.values() for pid in spec.parameter_ids if pid not in PARAMS})
    assert missing == []
    overrides = yaml.safe_load(paths.PAPER_FACTOR_OVERRIDES.read_text(encoding="utf-8"))
    assert sorted(pid for pid in overrides if pid not in PARAMS) == []
    for design in paths.DESIGNS.values():
        doc = yaml.safe_load(design.read_text(encoding="utf-8"))
        assert sorted(pid for pid in doc.get("activity_overrides", {}) if pid not in PARAMS) == []


def _expand(key: str) -> list[str]:
    """Concrete ids the engine resolves for a catalog key (fallback variants that must always exist)."""
    variants = {
        "<cc>": ["global"],
        "<code>": ["default"],
        "<temp>": ["ambient", "refrigerated", "frozen"],
        "<drug_type>": ["biologic", "small_molecule", "default"],
        "<strategy>": ["upfront", "on_demand"],
    }
    keys = [key]
    for ph, vals in variants.items():
        keys = [k.replace(ph, v) for k in keys for v in vals] if any(ph in k for k in keys) else keys
    return keys


def test_library_covers_the_engine_parameter_catalog() -> None:
    engine = pytest.importorskip("trialpilot_engine")
    catalog = getattr(engine, "PARAMETER_CATALOG", None)
    if catalog is None:
        pytest.skip("engine has no PARAMETER_CATALOG")
    # `ef.procedure.<code>` is optional per code and has no `.default` by design (engine carbon.py).
    keys = [k for k in catalog if not k.startswith("ef.procedure.")]
    missing = sorted(x for k in keys for x in _expand(k) if x not in PARAMS)
    assert missing == []


def test_ids_follow_the_schema_pattern() -> None:
    pattern = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_]+)+$")
    assert [pid for pid in PARAMS if not pattern.match(pid)] == []

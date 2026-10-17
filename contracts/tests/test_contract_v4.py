"""v4 additions preserve older inputs and unknown values in nested display details."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import ValidationError

from trialpilot_contracts import ForecastView, MetricRange, OpsEvent, ScenarioResult, SupplyView

HERE = Path(__file__).resolve().parent


def fixture(name: str) -> dict[str, Any]:
    return json.loads((HERE / "fixtures" / "valid" / f"{name}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def validate_schema(name: str, data: dict[str, Any]) -> None:
    schema = json.loads((HERE.parent / "schema" / f"{name}.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema, cls=jsonschema.Draft202012Validator)


@pytest.mark.parametrize("explicit_null", [False, True])
def test_old_scenario_details_default_to_none(explicit_null: bool) -> None:
    data = fixture("ScenarioResult")
    if explicit_null:
        data.update(forecast=None, supply=None)
    validate_schema("ScenarioResult", data)
    result = ScenarioResult.model_validate(data)
    assert result.forecast is None and result.supply is None
    emitted = result.model_dump(mode="json")
    assert emitted["forecast"] is None and emitted["supply"] is None
    validate_schema("ScenarioResult", emitted)


def test_scenario_accepts_a3_display_subsets_and_ignores_extra_fields() -> None:
    data = fixture("ScenarioResult")
    data["forecast"] = {**fixture("ForecastView"), "warnings": ["producer warning"],
                        "patients_to_randomise": 100, "provenance": []}
    data["supply"] = {**fixture("SupplyView"), "strategy": "on_demand", "provenance": [],
                      "kits_expired": {"p10": 1, "p50": 2, "p90": 3, "unit": "kits"}}
    validate_schema("ScenarioResult", data)
    result = ScenarioResult.model_validate(data)
    assert result.forecast is not None and result.supply is not None
    assert result.forecast.enrollment_curve[1] == (1, 2, 4, 6)
    assert not result.forecast.milestone_dates["DB_LOCK"].known
    assert result.supply.shipments.unit == "count"
    emitted = result.model_dump(mode="json")
    assert emitted["forecast"] == fixture("ForecastView")
    assert emitted["supply"] == fixture("SupplyView")
    validate_schema("ScenarioResult", emitted)
    assert ScenarioResult.model_validate_json(result.model_dump_json()) == result


def test_forecast_can_omit_curve_and_milestones() -> None:
    data = {"months_to_full_enrollment": fixture("ForecastView")["months_to_full_enrollment"]}
    validate_schema("ForecastView", data)
    view = ForecastView.model_validate(data)
    assert view.enrollment_curve == [] and view.milestone_dates == {}


@pytest.mark.parametrize("unknown", [False, True])
def test_count_range_preserves_known_or_unknown(unknown: bool) -> None:
    values = (None, None, None) if unknown else (1.0, 2.0, 3.0)
    metric = MetricRange(p10=values[0], p50=values[1], p90=values[2], unit="count")
    assert metric.known is not unknown
    data = metric.model_dump(mode="json")
    assert (data["p10"], data["p50"], data["p90"]) == values
    validate_schema("MetricRange", data)
    assert MetricRange.model_validate_json(metric.model_dump_json()) == metric


@pytest.mark.parametrize("section,key", [
    ("forecast", "months_to_full_enrollment"),
    ("supply", "kits_needed"), ("supply", "kits_produced"), ("supply", "kits_wasted"),
    ("supply", "waste_share"), ("supply", "shipments"),
])
def test_nested_metrics_stay_unknown_and_reject_partial_unknown(section: str, key: str) -> None:
    data = fixture("ScenarioResult")
    data[section] = fixture("ForecastView" if section == "forecast" else "SupplyView")
    metric = data[section][key]
    metric.update(p10=None, p50=None, p90=None)
    validate_schema("ScenarioResult", data)
    emitted = ScenarioResult.model_validate(data).model_dump(mode="json")
    assert emitted[section][key] == metric
    metric["p50"] = 0
    with pytest.raises(ValidationError):
        ScenarioResult.model_validate(data)
    with pytest.raises(jsonschema.ValidationError):
        validate_schema("ScenarioResult", data)


@pytest.mark.parametrize("length", [3, 5])
def test_curve_rows_require_exactly_four_numbers(length: int) -> None:
    data = fixture("ForecastView")
    data["enrollment_curve"] = [[0] * length]
    with pytest.raises(ValidationError):
        ForecastView.model_validate(data)
    with pytest.raises(jsonschema.ValidationError):
        validate_schema("ForecastView", data)


@pytest.mark.parametrize("probability", [-0.01, 1.01, None])
def test_stockout_probability_must_be_known_and_in_range(probability: float | None) -> None:
    data = fixture("SupplyView")
    data["stockout_probability"] = probability
    with pytest.raises(ValidationError):
        SupplyView.model_validate(data)
    with pytest.raises(jsonschema.ValidationError):
        validate_schema("SupplyView", data)


def test_missing_stockout_probability_is_not_defaulted_to_zero() -> None:
    data = fixture("SupplyView")
    del data["stockout_probability"]
    with pytest.raises(ValidationError):
        SupplyView.model_validate(data)
    with pytest.raises(jsonschema.ValidationError):
        validate_schema("SupplyView", data)


def test_ctms_site_activation_event_round_trips() -> None:
    data = fixture("OpsEvent")
    data.update(type="site_activated", site_id="backup-site-1", source_system="CTMS", payload={
        "activation_date": "2026-10-16", "country": "CA", "region": "Ontario",
        "status": "open_to_enrollment",
    })
    validate_schema("OpsEvent", data)
    event = OpsEvent.model_validate(data)
    assert event.type == "site_activated" and event.simulated
    assert OpsEvent.model_validate_json(event.model_dump_json()) == event

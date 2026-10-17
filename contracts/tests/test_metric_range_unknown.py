"""Contract v2: MetricRange can be unknown (all three percentiles null), never partly known (CHANGELOG v2)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from trialpilot_contracts import MetricRange, ScenarioResult

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schema"


def schema(name: str) -> dict[str, object]:
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_unknown_round_trips_and_matches_schema() -> None:
    r = MetricRange(p10=None, p50=None, p90=None, unit="usd")
    assert not r.known
    dumped = r.model_dump_json()
    assert json.loads(dumped) == {"p10": None, "p50": None, "p90": None, "unit": "usd"}
    assert MetricRange.model_validate_json(dumped) == r
    jsonschema.validate(json.loads(dumped), schema("MetricRange"), cls=jsonschema.Draft202012Validator)


def test_nan_becomes_unknown_so_api_output_can_be_read_back() -> None:
    r = MetricRange(p10=math.nan, p50=math.nan, p90=math.nan, unit="kg_co2e")
    assert (r.p10, r.p50, r.p90) == (None, None, None)
    assert MetricRange.model_validate_json(r.model_dump_json()) == r


def test_known_range_unchanged() -> None:
    r = MetricRange(p10=1.0, p50=2.0, p90=3.0, unit="hours")
    assert r.known and r.p50 == 2.0


@pytest.mark.parametrize("values", [(1.0, None, 3.0), (None, 2.0, None), (1.0, 2.0, math.nan)])
def test_partly_unknown_rejected(values: tuple[float | None, float | None, float | None]) -> None:
    p10, p50, p90 = values
    with pytest.raises(ValidationError, match="all be numbers, or all be null"):
        MetricRange(p10=p10, p50=p50, p90=p90, unit="usd")


def test_partly_unknown_rejected_by_schema_too() -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"p10": 1, "p50": None, "p90": 3, "unit": "usd"}, schema("MetricRange"),
                            cls=jsonschema.Draft202012Validator)


@pytest.mark.parametrize("bad", [math.inf, -math.inf])
def test_infinite_rejected(bad: float) -> None:
    with pytest.raises(ValidationError, match="finite"):
        MetricRange(p10=bad, p50=bad, p90=bad, unit="usd")


def test_nested_unknown_metric_valid_in_scenario_result_schema() -> None:
    data = json.loads((Path(__file__).parent / "fixtures/valid/ScenarioResult.json").read_text())
    data["co2e_kg"] = {"p10": None, "p50": None, "p90": None, "unit": "kg_co2e"}
    jsonschema.validate(data, schema("ScenarioResult"), cls=jsonschema.Draft202012Validator)
    ScenarioResult.model_validate(data)
    data["co2e_kg"]["p50"] = 5
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema("ScenarioResult"), cls=jsonschema.Draft202012Validator)

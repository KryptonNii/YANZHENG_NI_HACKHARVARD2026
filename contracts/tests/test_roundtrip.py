"""Every model round-trips through JSON, and the generated JSON Schema agrees with pydantic on fixtures.

fixtures/valid/<Model>.json      must validate against schema/<Model>.json AND the pydantic model.
fixtures/invalid/<Model>.<why>.json must be rejected by both.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import BaseModel, ValidationError

from trialpilot_contracts import models

HERE = Path(__file__).resolve().parent
SCHEMA_DIR = HERE.parent / "schema"
VALID = sorted((HERE / "fixtures" / "valid").glob("*.json"))
INVALID = sorted((HERE / "fixtures" / "invalid").glob("*.json"))

MODELS: dict[str, type[BaseModel]] = {
    n: o
    for n, o in vars(models).items()
    if isinstance(o, type) and issubclass(o, BaseModel) and o.__module__ == models.__name__
}


def model_for(path: Path) -> type[BaseModel]:
    return MODELS[path.name.split(".")[0]]


def schema_for(model: type[BaseModel]) -> dict[str, object]:
    schema = json.loads((SCHEMA_DIR / f"{model.__name__}.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema  # type: ignore[no-any-return]


def test_every_model_has_a_valid_fixture() -> None:
    assert sorted(p.stem for p in VALID) == sorted(MODELS)


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_fixture_passes_schema_and_pydantic(path: Path) -> None:
    model = model_for(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema_for(model), cls=jsonschema.Draft202012Validator)
    model.model_validate(data)


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_json_round_trip(path: Path) -> None:
    model = model_for(path)
    obj = model.model_validate_json(path.read_text(encoding="utf-8"))
    dumped = obj.model_dump_json()
    again = model.model_validate_json(dumped)
    assert again == obj
    assert again.model_dump_json() == dumped
    # What the API emits (every field, defaults included) must also satisfy the published schema.
    jsonschema.validate(json.loads(dumped), schema_for(model), cls=jsonschema.Draft202012Validator)


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_fixture_rejected_by_schema_and_pydantic(path: Path) -> None:
    model = model_for(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema_for(model), cls=jsonschema.Draft202012Validator)
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_datetimes_serialise_as_iso_8601_utc() -> None:
    sig = models.Signature.model_validate_json((HERE / "fixtures/valid/Signature.json").read_text())
    assert json.loads(sig.model_dump_json())["signed_at"] == "2026-10-16T21:00:00Z"

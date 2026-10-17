from pathlib import Path

import pytest

from trialpilot_contracts import (
    Parameter,
    ParamValidationError,
    load_params,
    param_set_version,
)

REPO = Path(__file__).resolve().parents[2]
PARAMS_DIR = REPO / "data" / "params"
EXAMPLE = PARAMS_DIR / "_example.yaml"

GOOD = """\
parameters:
  - id: a.b
    label: A
    value_low: 1
    value_mid: 2
    value_high: 3
    unit: usd/visit
    assumption: true
    rationale: test
"""


def write(tmp_path: Path, text: str, name: str = "p.yaml") -> Path:
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


def problems_for(tmp_path: Path, text: str) -> list[str]:
    write(tmp_path, text)
    with pytest.raises(ParamValidationError) as exc:
        load_params(tmp_path)
    return exc.value.problems


def test_example_file_loads_three_placeholder_assumptions() -> None:
    params = load_params(EXAMPLE)
    assert len(params) == 3
    assert all(p.assumption and p.rationale == "schema example" for p in params.values())


def test_examples_skipped_by_default_in_directory() -> None:
    assert not any(pid.startswith("example.") for pid in load_params(PARAMS_DIR))
    assert len(load_params(PARAMS_DIR, include_examples=True)) >= 3


def test_real_library_is_valid() -> None:
    load_params(PARAMS_DIR)  # raises on any problem


def test_good_file_loads_sorted(tmp_path: Path) -> None:
    write(tmp_path, GOOD.replace("id: a.b", "id: z.z") + GOOD.replace("parameters:\n", ""))
    assert list(load_params(tmp_path)) == ["a.b", "z.z"]


def test_defaults_are_merged_and_entry_wins(tmp_path: Path) -> None:
    text = (
        "defaults:\n  region: GB\n  source_title: S\n  source_year: 2024\n"
        + GOOD.replace("    rationale: test\n", "    rationale: test\n    region: FR\n")
    )
    p = load_params(write(tmp_path, text))["a.b"]
    assert p.region == "FR" and p.source_title == "S"


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        (("value_low: 1", "value_low: 5"), "value_low <= value_mid <= value_high"),
        (("value_high: 3", "value_high: 1.5"), "value_low <= value_mid <= value_high"),
        (("    rationale: test\n", ""), "requires a rationale"),
        (("assumption: true", "assumption: false"), "needs source_title or source_url"),
        (("id: a.b", "id: NoDots"), "dotted slug"),
        (("unit: usd/visit", "unit: usd/visit\n    soruce_url: x"), "unknown keys"),
        (("value_mid: 2", "value_mid: not-a-number"), "value_mid"),
    ],
)
def test_rule_violations_are_reported(tmp_path: Path, change: tuple[str, str], needle: str) -> None:
    probs = problems_for(tmp_path, GOOD.replace(*change))
    assert any(needle in p for p in probs), probs


def test_source_url_requires_year(tmp_path: Path) -> None:
    text = GOOD.replace("    rationale: test\n", "    rationale: test\n    source_url: https://x\n")
    assert any("source_url requires source_year" in p for p in problems_for(tmp_path, text))


def test_sourced_parameter_is_valid_without_rationale(tmp_path: Path) -> None:
    text = GOOD.replace(
        "    assumption: true\n    rationale: test\n",
        "    source_title: T\n    source_url: https://x\n    source_year: 2024\n",
    )
    assert load_params(write(tmp_path, text))["a.b"].assumption is False


def test_duplicate_ids_across_files(tmp_path: Path) -> None:
    write(tmp_path, GOOD, "one.yaml")
    write(tmp_path, GOOD, "two.yml")
    with pytest.raises(ParamValidationError) as exc:
        load_params(tmp_path)
    assert any("duplicate id" in p for p in exc.value.problems)


def test_all_problems_reported_at_once(tmp_path: Path) -> None:
    bad = GOOD.replace("value_low: 1", "value_low: 9").replace("    rationale: test\n", "")
    assert len(problems_for(tmp_path, bad)) == 2


def test_structural_errors(tmp_path: Path) -> None:
    assert any("'parameters:' list" in p for p in problems_for(tmp_path, "foo: 1\n"))


def test_missing_directory() -> None:
    with pytest.raises(FileNotFoundError):
        load_params(REPO / "does-not-exist")


def _param(pid: str, mid: float = 2.0) -> Parameter:
    return Parameter(
        id=pid, label="x", value_low=1, value_mid=mid, value_high=3, unit="u",
        assumption=True, rationale="r",
    )


def test_param_set_version_is_12_hex_and_order_independent() -> None:
    a, b = _param("a.a"), _param("b.b")
    v = param_set_version({"a.a": a, "b.b": b})
    assert len(v) == 12 and int(v, 16) >= 0
    assert v == param_set_version([b, a])


def test_param_set_version_changes_with_any_field() -> None:
    assert param_set_version([_param("a.a")]) != param_set_version([_param("a.a", mid=2.5)])

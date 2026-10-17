"""`python -m science.reproduce`: deterministic, schema-valid, honest (every gap explained), and checked in."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from trialpilot_contracts import load_params

from trialpilot_science import paths
from trialpilot_science.designs import load_design
from trialpilot_science.library import evaluate, triangular_draws
from trialpilot_science.reproduce import run, write
from trialpilot_science.results import ScienceResults

jsonschema = pytest.importorskip("jsonschema")


@pytest.fixture(scope="module")
def results_json(tmp_path_factory: pytest.TempPathFactory) -> dict:
    out = tmp_path_factory.mktemp("science") / "results.json"
    write(run(), out, out.with_name("results.schema.json"))
    return json.loads(out.read_text(encoding="utf-8"))


def test_deterministic(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    write(run(draws=300), a, tmp_path / "a.schema.json")
    write(run(draws=300), b, tmp_path / "b.schema.json")
    assert a.read_bytes() == b.read_bytes()


def test_matches_schema(results_json: dict) -> None:
    jsonschema.validate(results_json, ScienceResults.model_json_schema())


def test_checked_in_results_are_current(results_json: dict) -> None:
    """science/out/results.json is served as a static file (A5) — it must match the code and data."""
    committed = json.loads(paths.RESULTS_JSON.read_text(encoding="utf-8"))
    assert committed == results_json, "rerun: uv run --project science python -m science.reproduce"


def _rows(results: dict):
    for t in results["trials"]:
        for c in t["checks"]:
            for row in c["modules"] + ([c["total"]] if c["total"] else []):
                yield t["id"], c["id"], row


def test_ranges_are_ordered(results_json: dict) -> None:
    for _, _, row in _rows(results_json):
        if row["ours"]:
            assert row["ours"]["p10"] <= row["ours"]["p50"] <= row["ours"]["p90"]


def test_every_gap_is_explained(results_json: dict) -> None:
    unexplained = [(t, c, r["module"]) for t, c, r in _rows(results_json) if r["status"] == "gap" and not r["explanation"]]
    assert unexplained == []


def test_published_values_are_the_papers(results_json: dict) -> None:
    by_id = {t["id"]: t for t in results_json["trials"]}
    assert by_id["casps"]["published"]["total_kg"] == 71938.8
    assert by_id["primetime"]["published"]["total_kg"] == 89360.2
    assert results_json["industry_band"]["low_t"] == 1437 and results_json["industry_band"]["high_t"] == 2498
    assert results_json["simulated"] is False


def test_method_check_reproduces_the_paper(results_json: dict) -> None:
    for t in results_json["trials"]:
        method = next(c for c in t["checks"] if c["id"] == "method")
        assert abs(method["total"]["diff_pct"]) < 0.5, t["id"]


def _expected_diff_pct(published_kg: float, p50: float) -> float:
    """Same rounding as trialpilot_science.checks._status."""
    if published_kg == 0:
        diff = 0.0 if abs(p50) < 0.5 else float("inf")
    else:
        diff = (p50 - published_kg) / published_kg * 100.0
    return round(diff, 2)


@pytest.mark.req("URS-014")
@pytest.mark.parametrize("tid", ["casps", "primetime"])
def test_each_module_percent_difference_against_published(results_json: dict, tid: str) -> None:
    """URS-014: CASPS and PRIMETIME report each module's % difference against the published value."""
    trial = next(t for t in results_json["trials"] if t["id"] == tid)
    published = trial["published"]["modules"]
    assert published
    available = [c for c in trial["checks"] if c["available"]]
    assert available
    for check in available:
        rows = {row["module"]: row for row in check["modules"]}
        missing = sorted(set(published) - set(rows))
        assert missing == [], (tid, check["id"], missing)
        for module, published_kg in published.items():
            row = rows[module]
            assert row["published_kg"] == pytest.approx(published_kg), (tid, check["id"], module)
            assert row["ours"] is not None, (tid, check["id"], module)
            expected = _expected_diff_pct(float(published_kg), float(row["ours"]["p50"]))
            assert row["diff_pct"] == pytest.approx(expected, abs=0.011), (tid, check["id"], module)


def test_band_trial_unit_matches_tonnes(results_json: dict) -> None:
    """BandTrial.total_t numbers are tonnes and the unit says t_co2e."""
    band = results_json["industry_band"]
    assert band["low_t"] == 1437 and band["high_t"] == 2498
    reported = [t for t in band["demo_trials"] if t["total_t"] is not None]
    assert reported
    for trial in reported:
        total = trial["total_t"]
        assert total["unit"] == "t_co2e"
        assert 1 < total["p50"] < 20_000


def test_two_summary_sentences_per_trial(results_json: dict) -> None:
    for t in results_json["trials"]:
        assert len(t["summary"]) == 2 and all(s.endswith(".") for s in t["summary"])


def test_designs_preserve_reported_activity() -> None:
    lib = load_params(paths.PARAMS_DIR)
    casps = load_design(paths.DESIGNS["casps"], "casps", lib).design
    assert casps.enrollment_target == 47 and len(casps.sites) == 12
    assert sum(p.code == "ct_scan" for v in casps.visits for p in v.procedures) == 9  # 47 x 9 CT scans
    prime = load_design(paths.DESIGNS["primetime"], "primetime", lib).design
    assert prime.enrollment_target == 1962 and len(prime.sites) == 64
    assert sum(p.code == "mammogram" for v in prime.visits for p in v.procedures) == 5


def test_triangular_draws_stay_in_range_and_are_seeded() -> None:
    lib = load_params(paths.PARAMS_DIR)
    p = lib["ef.electricity.grid.gb"]
    d1, d2 = triangular_draws(p, 7, 5000), triangular_draws(p, 7, 5000)
    assert np.array_equal(d1, d2)
    assert d1.min() >= p.value_low and d1.max() <= p.value_high


def test_factor_expressions_are_sandboxed() -> None:
    assert float(evaluate("a * (1 - b) + 2", {"a": 3.0, "b": 0.5})) == pytest.approx(3.5)
    for bad in ("__import__('os')", "a.b", "a ** 2", "[a]"):
        with pytest.raises((ValueError, KeyError, SyntaxError)):
            evaluate(bad, {"a": 1.0})

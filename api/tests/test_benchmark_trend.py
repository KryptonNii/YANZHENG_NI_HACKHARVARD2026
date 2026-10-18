"""Sponsor complexity trend: per-trial counts, sponsor-free expectations and reproducible output."""

import json
import math

import pytest

from trialpilot_api.benchmark import trend


def study(nct, *, lead="Acme Pharma", collaborators=(), phases=("PHASE3",), start="2016-03",
          outcomes=(1, 2, 0), criteria="Inclusion Criteria:\n- a\n- b\nExclusion Criteria:\n- c",
          countries=("United States", "United States", "Canada"),
          meshes=("Pulmonary Disease, Chronic Obstructive",),
          ancestors=("Lung Diseases", "Respiratory Tract Diseases")):
    primary, secondary, other = outcomes
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct},
            "statusModule": {"overallStatus": "COMPLETED", "startDateStruct": {"date": start}},
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": lead, "class": "INDUSTRY"},
                "collaborators": [{"name": c} for c in collaborators]},
            "designModule": {"phases": list(phases)},
            "outcomesModule": {
                "primaryOutcomes": [{"measure": f"p{i}"} for i in range(primary)],
                "secondaryOutcomes": [{"measure": f"s{i}"} for i in range(secondary)],
                "otherOutcomes": [{"measure": f"o{i}"} for i in range(other)]},
            "eligibilityModule": {"eligibilityCriteria": criteria},
            "contactsLocationsModule": {"locations": [{"country": c} for c in countries]},
        },
        "derivedSection": {"conditionBrowseModule": {
            "meshes": [{"term": m} for m in meshes],
            "ancestors": [{"term": a} for a in ancestors]}},
    }


def row(nct, *, lead="Acme Pharma", year=2016, phase="PHASE3", areas=("Respiratory Tract Diseases",),
        outcomes=10, countries=4, sites=20, eligibility=15, abridged=False, collaborators=()):
    return {"nct": nct, "phase": phase, "start_year": year, "status": "COMPLETED", "lead": lead,
            "collaborators": list(collaborators), "areas": list(areas), "outcomes": outcomes,
            "countries": countries, "sites": sites, "eligibility": eligibility,
            "eligibility_abridged": abridged}


def test_extract_counts_registry_fields_and_keeps_unreported_as_none():
    r = trend.extract(study("NCT00000001"))
    assert r == {
        "nct": "NCT00000001", "phase": "PHASE3", "start_year": 2016, "status": "COMPLETED",
        "lead": "Acme Pharma", "collaborators": [], "areas": ["Respiratory Tract Diseases"],
        "outcomes": 3, "eligibility": 3, "eligibility_abridged": False, "sites": 3,
        "countries": 2,
    }
    empty = trend.extract(study("NCT00000002", outcomes=(0, 0, 0), criteria="", countries=()))
    assert (empty["outcomes"], empty["eligibility"], empty["sites"], empty["countries"]) == \
        (None, None, None, None)


def test_key_criteria_postings_are_marked_abridged():
    text = "Key Inclusion Criteria:\n- a\nKey Exclusion Criteria:\n- b\nNote: Other protocol-" \
           "defined Inclusion/Exclusion Criteria apply"
    assert trend.extract(study("NCT00000003", criteria=text))["eligibility_abridged"] is True


def test_disease_areas_use_mesh_categories_with_generic_and_unclassified_fallbacks():
    assert trend.disease_areas(["Dermatitis, Atopic"], [
        "Skin Diseases", "Skin and Connective Tissue Diseases", "Immune System Diseases",
        trend.GENERIC_AREA]) == ["Immune System Diseases", "Skin and Connective Tissue Diseases"]
    assert trend.disease_areas([], ["Disease Attributes", trend.GENERIC_AREA]) == \
        [trend.GENERIC_AREA]
    assert trend.disease_areas([], []) == [trend.UNCLASSIFIED]


@pytest.mark.parametrize(("lead", "collaborators", "group"), [
    ("Regeneron Pharmaceuticals", (), "sponsor_led"),
    ("Regeneron Pharmaceuticals, Inc.", (), "sponsor_led"),
    ("Sanofi", ("Regeneron Pharmaceuticals",), "sponsor_collaborator"),
    ("RegeneRx Biopharmaceuticals, Inc.", (), "industry"),
    ("Sanofi", (), "industry"),
])
def test_sponsor_groups_match_the_whole_word(lead, collaborators, group):
    assert trend.group_of(row("NCT1", lead=lead, collaborators=collaborators)) == group


@pytest.mark.parametrize(("year", "block"), [
    (2009, None), (2010, "2010-2012"), (2012, "2010-2012"), (2024, "2022-2024"), (2025, None),
    (None, None)])
def test_three_year_blocks(year, block):
    assert trend.block_of(year) == block


def reference(n=25, **kw):
    return [row(f"NCT9{i:07d}", **kw) for i in range(n)]


def test_expectation_comes_from_sponsor_free_industry_only():
    rows = reference(outcomes=10) + [
        row("NCT80000001", lead="Regeneron Pharmaceuticals", outcomes=20),
        *[row(f"NCT7{i:07d}", lead="Regeneron Pharmaceuticals", outcomes=1000) for i in range(30)],
    ]
    items = {it["nct"]: it for it in trend.ratios(rows)}
    assert items["NCT80000001"]["outcomes"] == pytest.approx(2.0)
    assert items["NCT90000000"]["outcomes"] == pytest.approx(1.0)
    assert items["NCT80000001"]["fallback"] == []


def test_small_cells_fall_back_to_the_phase_median_and_are_flagged():
    rows = reference(outcomes=10) + [
        *[row(f"NCT6{i:07d}", areas=("Eye Diseases",), outcomes=40) for i in range(3)],
        row("NCT50000001", areas=("Eye Diseases",), outcomes=20),
    ]
    item = next(it for it in trend.ratios(rows) if it["nct"] == "NCT50000001")
    assert item["outcomes"] == pytest.approx(20 / 10)
    assert "outcomes" in item["fallback"]


def test_multi_area_expectation_is_the_mean_of_area_medians():
    rows = (reference(outcomes=10) + reference(n=25, areas=("Eye Diseases",), outcomes=30)
            + [row("NCT40000001", areas=("Eye Diseases", "Respiratory Tract Diseases"),
                   outcomes=40)])
    # reference() reuses NCT ids per call; distinct ids are not needed for the medians.
    item = next(it for it in trend.ratios(rows) if it["nct"] == "NCT40000001")
    assert item["outcomes"] == pytest.approx(40 / 20)


def test_composite_is_the_geometric_mean_and_needs_all_three_dimensions():
    rows = reference() + [row("NCT30000001", outcomes=20, countries=2, sites=20),
                          row("NCT30000002", sites=None)]
    items = {it["nct"]: it for it in trend.ratios(rows)}
    assert items["NCT30000001"]["composite"] == pytest.approx(math.exp(
        (math.log(2) + math.log(0.5) + math.log(1)) / 3))
    assert items["NCT30000002"]["composite"] is None


def test_large_sponsor_peers_are_context_and_never_change_the_reference(monkeypatch):
    monkeypatch.setattr(trend, "LARGE_SPONSOR_MIN", 3)
    rows = reference(outcomes=10) + [
        row(f"NCT2{i:07d}", lead="Big Pharma", outcomes=30) for i in range(3)] + [
        row("NCT20000099", lead="Small Bio", outcomes=10)]
    without = trend.analyze(reference(outcomes=10), boot=0)
    report = trend.analyze(rows, boot=0)
    peers = {(s["period"], s["metric"]): s for s in report["series"]
             if s["group"] == "large_sponsor_peers"}
    assert report["large_sponsor_peers"] == ["Acme Pharma", "Big Pharma"]
    assert peers["all", "outcomes"]["n"] == 28  # 25 Acme + 3 Big Pharma; Small Bio is not a peer
    # Peers are a subset of industry, so the industry reference keeps its median of 10.
    ind = {(s["period"], s["metric"]): s for s in without["series"] if s["group"] == "industry"}
    assert ind["all", "outcomes"]["median_ratio"] == pytest.approx(1.0)


def test_bootstrap_interval_is_seeded_and_contains_the_median():
    values = [0.5, 0.8, 1.0, 1.1, 1.3, 2.0, 2.5, 0.9, 1.2, 1.05]
    first = trend.median_ci(values, 500, "a", "b")
    assert first == trend.median_ci(values, 500, "a", "b")
    point, (lo, hi) = first
    assert lo <= point <= hi
    assert trend.median_ci(values, 0, "a") == (pytest.approx(1.075), None)


def test_committed_report_matches_the_committed_table():
    if not trend.TABLE.exists() or not trend.OUT_JSON.exists():
        pytest.skip("complexity snapshot not present")
    committed = json.loads(trend.OUT_JSON.read_text(encoding="utf-8"))["results"]
    fresh = trend.analyze(trend.read_table(), boot=0)
    key = lambda s: (s["group"], s["period"], s["metric"])  # noqa: E731
    assert {key(s): (s["n"], s["median_ratio"]) for s in fresh["series"]} == \
        {key(s): (s["n"], s["median_ratio"]) for s in committed["series"]}
    assert fresh["trials_by_group"] == committed["trials_by_group"]

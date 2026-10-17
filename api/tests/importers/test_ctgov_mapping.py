"""Mapping tests on the saved REAL ClinicalTrials.gov responses (golden TrialDesign JSON)."""

from __future__ import annotations

import json

import pytest

from trialpilot_api.importers._contracts import TrialDesign
from trialpilot_api.importers.ctgov import (
    classify_drug_type,
    fetch_study_result,
    map_phase,
    map_study,
    map_study_report,
    parse_partial_date,
)

from .conftest import ALL_NCT, DEMO_NCT, REAL_FIXTURES


def _report(nct: str):  # type: ignore[no-untyped-def]
    r = fetch_study_result(nct, offline=True)
    return map_study_report(r.raw, meta=r.meta)


@pytest.mark.parametrize("nct", ALL_NCT)
def test_mapping_matches_golden_fixture(nct: str) -> None:
    golden = TrialDesign.model_validate_json((REAL_FIXTURES / "trials" / f"{nct}.json").read_text(encoding="utf-8"))
    assert map_study(fetch_study_result(nct, offline=True).raw) == golden


def test_demo_trial_boreas_facts_from_registry() -> None:
    rep = _report(DEMO_NCT)
    d = rep.design
    assert d.registry_id == DEMO_NCT and d.source == "ctgov"
    assert d.title.startswith("BOREAS: ")
    assert d.phase == "Phase 3"
    assert d.conditions == ["Chronic Obstructive Pulmonary Disease"]
    assert d.enrollment_target == 939 and rep.enrollment_type == "ACTUAL"
    assert d.duration_months == pytest.approx(48.6, abs=0.05)  # 2019-04-15 -> 2023-05-02
    assert d.drug_type == "biologic" and "dupilumab" in rep.drug_type_basis
    assert len(d.sites) == 275
    assert len(rep.geocoded_site_ids) == 30 and rep.unresolved_site_ids == []
    assert all(s.lat is not None and s.lon is not None for s in d.sites)
    assert rep.sponsor == "Sanofi" and "Regeneron Pharmaceuticals" in rep.collaborators
    assert any(doc["has_protocol"] and doc["url"].endswith("/NCT03930732/Prot_000.pdf") for doc in rep.documents)


def test_visits_are_flagged_as_assumed_template() -> None:
    rep = _report(DEMO_NCT)
    d = rep.design
    assert "visits" in d.missing_fields
    assert rep.visit_template_id == "phase3_default"
    assert rep.field_sources["visits"].startswith("assumption:")
    weeks = [v.week for v in d.visits]
    assert weeks == sorted(weeks) and len(set(weeks)) == len(weeks)
    assert [v.number for v in d.visits] == list(range(1, len(d.visits) + 1))
    assert any("NOT in the registry" in n for n in rep.notes)
    assert all(not v.can_be_remote for v in d.visits)  # decided by humans, default False


def test_unknown_is_never_zero() -> None:
    d = _report(DEMO_NCT).design
    assert all(s.expected_enrollment is None for s in d.sites)
    assert "sites.expected_enrollment" in d.missing_fields


def test_unresolved_sites_are_reported_not_guessed() -> None:
    raw = json.loads((REAL_FIXTURES / "ctgov" / f"{DEMO_NCT}.json").read_text(encoding="utf-8"))
    raw["protocolSection"]["contactsLocationsModule"]["locations"].append(
        {"facility": "Site with an unknown town", "city": "Qwertyzxcv", "country": "France"})
    rep = map_study_report(raw)
    unresolved = [s for s in rep.design.sites if s.id in rep.unresolved_site_ids]
    assert len(unresolved) == 1 and unresolved[0].lat is None and unresolved[0].lon is None
    assert "sites.lat_lon" in rep.design.missing_fields
    assert any("could not be placed" in n for n in rep.notes)


def test_geocoded_sites_are_named_in_notes() -> None:
    rep = _report(DEMO_NCT)
    note = next(n for n in rep.notes if "had no registry geoPoint" in n)
    assert "GeoNames" in note and "state level" in note


def test_small_molecule_and_phase_2_3() -> None:
    assert _report("NCT04535986").design.drug_type == "small_molecule"  # ensifentrine
    photon = _report("NCT04429503").design
    assert photon.phase == "Phase 2/3" and photon.drug_type == "biologic"  # aflibercept (-cept)


def test_site_ids_are_stable_and_unique() -> None:
    a = _report(DEMO_NCT).design
    b = _report(DEMO_NCT).design
    assert [s.id for s in a.sites] == [s.id for s in b.sites]
    assert len({s.id for s in a.sites}) == len(a.sites)
    assert a.id == b.id


def test_attribution_follows_ctgov_terms() -> None:
    rep = _report(DEMO_NCT)
    assert "ClinicalTrials.gov" in rep.attribution and "Data processed by ClinicalTrials.gov" in rep.attribution
    assert "Modified by TrialPilot" in rep.attribution


def test_phase_and_dates_helpers() -> None:
    assert map_phase(["PHASE3"]) == "Phase 3"
    assert map_phase(["PHASE1", "PHASE2"]) == "Phase 1/2"
    assert map_phase(["NA"]) == "Not Applicable"
    assert map_phase([]) is None
    assert parse_partial_date("2019-04")[1] is True
    assert parse_partial_date("2019-04-15")[0].isoformat() == "2019-04-15"  # type: ignore[union-attr]
    assert parse_partial_date(None) == (None, False)


def test_drug_type_rules() -> None:
    bio = {"interventions": [{"type": "BIOLOGICAL", "name": "Vaccine X"}]}
    assert classify_drug_type(bio)[0] == "biologic"
    mab = {"interventions": [{"type": "DRUG", "name": "Placebo"}, {"type": "DRUG", "name": "fooximab"}]}
    assert classify_drug_type(mab)[0] == "biologic"
    sm = {"interventions": [{"type": "DRUG", "name": "metformin"}]}
    assert classify_drug_type(sm)[0] == "small_molecule"
    dev = {"interventions": [{"type": "DEVICE", "name": "Wearable patch"}]}
    assert classify_drug_type(dev)[0] == "device"
    assert classify_drug_type({"interventions": []})[0] == "unknown"
    # "-ment" stem must not fire on ordinary words
    beh = {"interventions": [{"type": "DRUG", "name": "Standard treatment"}]}
    assert classify_drug_type(beh)[0] == "small_molecule"


def test_missing_enrollment_is_an_error_not_a_zero() -> None:
    raw = json.loads((REAL_FIXTURES / "ctgov" / f"{DEMO_NCT}.json").read_text(encoding="utf-8"))
    del raw["protocolSection"]["designModule"]["enrollmentInfo"]
    from trialpilot_api.importers.ctgov import InsufficientRegistryData

    with pytest.raises(InsufficientRegistryData):
        map_study(raw)


def test_missing_dates_flag_duration() -> None:
    raw = json.loads((REAL_FIXTURES / "ctgov" / f"{DEMO_NCT}.json").read_text(encoding="utf-8"))
    sm = raw["protocolSection"]["statusModule"]
    for k in ("startDateStruct", "primaryCompletionDateStruct", "completionDateStruct"):
        sm.pop(k, None)
    d = map_study(raw)
    assert "duration_months" in d.missing_fields and d.duration_months > 0

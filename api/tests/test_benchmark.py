"""Deterministic local registry cohorts, sparse percentiles, and engine comparisons."""

import hashlib
import json
import socket

import pytest
from a5_support import AUTHOR, make_design
from trialpilot_contracts import Levers, TrialDesign
from trialpilot_engine import compare_levers, compute_scenario

from trialpilot_api.benchmark import cohort, routes
from trialpilot_api.benchmark.cohort import (
    CACHE_DIR,
    comparison_rows,
    condition_group,
    eligibility_counts,
    load_cohort,
    matching_peers,
    normalize_phase,
    snapshot,
    source_paths,
)
from trialpilot_api.engine_adapter import EngineFns
from trialpilot_api.settings import REPO_ROOT

CTGOV_ORIGINALS = ["NCT03930732", "NCT04429503", "NCT04456673", "NCT04535986"]


def write_study(directory, nct, *, primary=3, conditions=None, phases=None):
    """Minimal CT.gov v2 records; never require a populated repository registry."""
    study = {"protocolSection": {
        "identificationModule": {"nctId": nct},
        "conditionsModule": {"conditions": conditions if conditions is not None else ["COPD"]},
        "designModule": {
            "phases": phases if phases is not None else ["PHASE3"],
            "enrollmentInfo": {"count": 120, "type": "ESTIMATED"},
        },
        "outcomesModule": {
            "primaryOutcomes": [{"measure": f"Primary {i}"} for i in range(primary)],
            "secondaryOutcomes": [{"measure": "Secondary A"}, {"measure": "Secondary B"}],
            "otherOutcomes": [{"measure": "Other"}],
        },
        "eligibilityModule": {
            "eligibilityCriteria": "Inclusion Criteria:\n* A\n* B\nExclusion Criteria:\n* C",
        },
        "contactsLocationsModule": {"locations": [
            {"country": "Canada"}, {"country": " canada "}, {"country": "United States"},
        ]},
    }}
    path = directory / f"{nct}.json"
    path.write_text(json.dumps(study), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def cached_registry(tmp_path, monkeypatch):
    """All default cohort reads use temporary data, including API calls and snapshots."""
    fixtures = tmp_path / "fixtures"
    cache = fixtures / "ctgov"
    registry = fixtures / "peers" / "registry"
    cache.mkdir(parents=True)
    registry.mkdir(parents=True)
    monkeypatch.setattr(cohort, "FIXTURES_DIR", fixtures)
    monkeypatch.setattr(cohort, "CACHE_DIR", cache)
    monkeypatch.setattr(cohort, "REGISTRY_DIR", registry)
    write_study(cache, "NCT03930732", primary=3)
    write_study(registry, "NCT03930732", primary=99)
    for number, primary in enumerate((1, 2, 3, 3, 5), start=1):
        write_study(registry, f"NCT1000000{number}", primary=primary,
                    conditions=["pulmonary disease chronic obstructive"] if number == 5 else None)
    write_study(cache, "NCT10000006", primary=4)
    write_study(registry, "NCT10000006", primary=40)
    write_study(registry, "NCT10000007", phases=["PHASE2", "PHASE3"])
    for number, condition in enumerate(("Emphysema", "Pulmonary Arterial Hypertension",
                                         "Heart Failure"), start=8):
        write_study(registry, f"NCT100000{number:02}", conditions=[condition, "COPD"])
    write_study(registry, "NCT10000011", conditions=["DME"], phases=["PHASE2", "PHASE3"])
    # Sidecars and lookalike filenames must not be parsed, even if their JSON is invalid.
    for filename in ("NCT10000001.meta.json", "NCT10000012.extra.json", "NCT123.json"):
        (registry / filename).write_text("not study JSON", encoding="utf-8")
    return cache, registry


@pytest.fixture
def ctgov_only(monkeypatch):
    """The original four-file cache, to keep exercising a sparse cohort through the API."""
    monkeypatch.setattr(routes, "load_cohort", lambda: load_cohort((CACHE_DIR,)))


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    # Windows asyncio implements its internal socketpair over loopback TCP.
    def guarded(original):
        def connect(sock, address):
            if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
                return original(sock, address)
            raise AssertionError("Peer Mirror must use local data only")
        return connect

    monkeypatch.setattr(socket.socket, "connect", guarded(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guarded(socket.socket.connect_ex))


def save_registry_design(client, **overrides):
    design = make_design("peer-design")
    design.update(registry_id="NCT03930732", source="ctgov", phase="Phase 3",
                  conditions=["COPD"], visits=[], missing_fields=[])
    design.update(overrides)
    response = client.post("/api/designs", json=design, headers=AUTHOR)
    assert response.status_code == 201, response.text
    return design


def get_peers(client, version=1, **params):
    response = client.get("/api/designs/peer-design/peers", params={"version": version, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_missing_version_is_explicit_even_for_unknown_design(client):
    response = client.get("/api/designs/not-stored/peers")
    assert response.status_code == 422
    assert set(response.json()) == {"error", "message", "details"}
    assert response.json()["error"] == "design_version_required"


@pytest.mark.parametrize("version", [0, "bad"])
def test_invalid_version_uses_error_envelope(client, version):
    response = client.get("/api/designs/peer-design/peers", params={"version": version})
    assert response.status_code == 422
    assert set(response.json()) == {"error", "message", "details"}


def test_missing_design_version_is_not_silently_replaced(client):
    save_registry_design(client)
    response = client.get("/api/designs/peer-design/peers?version=2")
    assert response.status_code == 404
    assert response.json()["error"] == "design_not_found"


def test_insufficient_peers_retains_own_counts_and_descriptive_median(
        client, fake_engine, ctgov_only):
    save_registry_design(client)
    payload = get_peers(client)
    assert payload["cohort_n"] == 2
    assert payload["peer_source_files"] == ["NCT04456673.json", "NCT04535986.json"]
    assert payload["own_counts"]["primary_outcomes"] == 1
    assert payload["own_counts"]["total_outcomes"] == 17
    assert payload["own_counts"]["sites"] == 275
    for row in payload["rows"]:
        assert row["status"] == "insufficient_peers"
        assert row["percentile"] is None
        assert row["cohort_n"] == 2
        assert row["phase"] == "PHASE3"
        assert row["condition_group"] == "copd"
        assert row["source_file"] == "NCT03930732.json"
        assert row["question"].endswith("?")
    outcomes = next(row for row in payload["rows"] if row["metric"] == "total_outcomes")
    assert outcomes["peer_median"] == 12.5
    assert outcomes["comparison"] == "more"
    assert payload["cost_comparison"] is None
    assert "No saved visit schedule" in payload["cost_reason"]
    assert fake_engine.calls == 0


def test_default_sources_include_both_caches_and_prefer_ctgov(cached_registry):
    cache, registry = cached_registry
    records = {record.registry_id: record for record in load_cohort()}
    assert set(records) == {"NCT03930732", *(f"NCT100000{i:02}" for i in range(1, 12))}
    for nct, primary in (("NCT03930732", 3), ("NCT10000006", 4)):
        source = cache / f"{nct}.json"
        assert records[nct].source_file == source.name
        assert records[nct].source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
        assert records[nct].counts.primary_outcomes == primary
    assert {p.stem for p in source_paths()} == set(records)
    assert source_paths((cache, registry)) == source_paths()
    for nct, record in records.items():
        path = cache / record.source_file if nct in {"NCT03930732", "NCT10000006"} else (
            registry.parent.parent / record.source_file)
        assert path.is_file()
        assert record.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert records["NCT10000005"].source_file == "peers/registry/NCT10000005.json"


@pytest.mark.parametrize("registry_exists", [False, True])
def test_empty_or_absent_registry_still_reads_ctgov(tmp_path, monkeypatch, client,
                                                  registry_exists):
    fixtures = tmp_path / "sparse-fixtures"
    cache, registry = fixtures / "ctgov", fixtures / "peers" / "registry"
    cache.mkdir(parents=True)
    if registry_exists:
        registry.mkdir(parents=True)
    monkeypatch.setattr(cohort, "FIXTURES_DIR", fixtures)
    monkeypatch.setattr(cohort, "CACHE_DIR", cache)
    monkeypatch.setattr(cohort, "REGISTRY_DIR", registry)
    source = write_study(cache, "NCT03930732")
    assert source_paths() == [source]
    assert [record.registry_id for record in load_cohort()] == ["NCT03930732"]
    save_registry_design(client)
    payload = get_peers(client)
    assert payload["cohort_n"] == 0
    assert payload["own_counts"]["primary_outcomes"] == 3
    assert all(row["percentile"] is None and row["peer_median"] is None
               and row["comparison"] is None for row in payload["rows"])


def test_api_uses_both_sources_for_descriptive_percentiles(client, fake_engine):
    save_registry_design(client)
    payload = get_peers(client)
    assert payload["cohort_n"] == 6
    assert payload["source_file"] == "NCT03930732.json"
    peers = payload["peer_source_files"]
    assert len(set(peers)) == len(peers)
    assert "NCT03930732.json" not in peers and "peers/registry/NCT03930732.json" not in peers
    assert set(peers) == {"NCT10000006.json", *(
        f"peers/registry/NCT1000000{i}.json" for i in range(1, 6))}
    by_file = {record.source_file: record for record in load_cohort()}
    assert all(by_file[f].phase == "PHASE3" and by_file[f].condition_group == "copd"
               for f in peers)
    for row in payload["rows"]:
        assert row["cohort_n"] == row["available_n"] == 6
        assert row["status"] == "ok" and row["percentile"] == 50
        assert row["question"].endswith("?")
    primary = next(row for row in payload["rows"] if row["metric"] == "primary_outcomes")
    assert primary["own_count"] == primary["peer_median"] == 3
    assert primary["comparison"] == "same"
    assert fake_engine.calls == 0


def test_original_ctgov_counts_are_extracted_without_registry_or_snapshot(client, ctgov_only):
    # Independent expected line counts for the four unchanged source records.
    criteria = {"NCT03930732": (8, 11, 19), "NCT04429503": (5, 6, 11),
                "NCT04456673": (8, 11, 19), "NCT04535986": (24, 43, 67)}
    records = load_cohort((CACHE_DIR,))
    assert {record.registry_id for record in records} == set(CTGOV_ORIGINALS)
    for record in records:
        ps = json.loads((CACHE_DIR / record.source_file).read_text(encoding="utf-8"))["protocolSection"]
        outcomes = ps["outcomesModule"]
        locations = ps["contactsLocationsModule"]["locations"]
        expected = {
            "primary_outcomes": len(outcomes["primaryOutcomes"]),
            "total_outcomes": sum(len(outcomes.get(key, [])) for key in (
                "primaryOutcomes", "secondaryOutcomes", "otherOutcomes")),
            "inclusion_criteria": criteria[record.registry_id][0],
            "exclusion_criteria": criteria[record.registry_id][1],
            "eligibility_criteria": criteria[record.registry_id][2],
            "sites": len(locations),
            "countries": len({loc["country"].strip().casefold() for loc in locations}),
            "enrollment_target": None,  # These four records report ACTUAL, not ESTIMATED.
        }
        assert record.counts.model_dump() == expected
        design = save_registry_design(
            client, id=record.registry_id, registry_id=record.registry_id,
            phase=record.phase, conditions=ps["conditionsModule"]["conditions"],
        )
        response = client.get(f"/api/designs/{design['id']}/peers?version=1")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["own_counts"] == expected
        assert payload["enrollment_reported"] == ps["designModule"]["enrollmentInfo"]["count"]
        assert payload["enrollment_type"] == "ACTUAL"
        assert "splitlines()" in payload["methods"]["eligibility"]
        assert "ACTUAL" in payload["methods"]["enrollment"]


def test_snapshot_reextracts_current_sources_instead_of_reading_a_saved_snapshot(cached_registry):
    cache, _ = cached_registry
    before = snapshot()
    write_study(cache, "NCT03930732", primary=7)
    after = snapshot()
    assert after["source_kind"] == "cached_registry"
    old = next(record for record in before["records"] if record["registry_id"] == "NCT03930732")
    new = next(record for record in after["records"] if record["registry_id"] == "NCT03930732")
    assert old["counts"]["primary_outcomes"] == 3
    assert new["counts"]["primary_outcomes"] == 7
    assert old["source_sha256"] != new["source_sha256"]


def test_line_method_handles_nested_bullets_continuations_and_repeated_headings():
    assert eligibility_counts(
        "Key Inclusion Criteria:\n\n* A\n  continuation\n  * nested\n"
        "Inclusion Criteria at Randomization:\n1. B\n"
        "Exclusion Criteria:\n* C\nExclusion Criteria at Randomization\n* D\n"
    ) == (4, 2, 6)
    assert eligibility_counts("Unsectioned text\n\nnext line") == (None, None, 2)
    assert eligibility_counts(None) == (None, None, None)


@pytest.mark.parametrize(("raw", "expected"), [
    ("Phase III", "PHASE3"), ("Phase 2/3", "PHASE2/PHASE3"),
    (["PHASE2", "PHASE3"], "PHASE2/PHASE3"), ("Early Phase 1", "EARLY_PHASE1"),
    (None, None), ("not known", None),
])
def test_phase_normalization_preserves_combined_phases(raw, expected):
    assert normalize_phase(raw) == expected


@pytest.mark.parametrize("spelling", [
    "COPD", "  Chronic Obstructive Pulmonary Disease (COPD)  ",
    "Pulmonary Disease, Chronic Obstructive", "pulmonary disease chronic obstructive",
    "COPD (Chronic Obstructive Pulmonary Disease)",
    "Pulmonary Disease, Chronic Obstructive (COPD)",
])
def test_exact_copd_aliases_are_normalized(spelling):
    assert condition_group([spelling]) == "copd"


@pytest.mark.parametrize(("first", "expected"), [
    ("Emphysema", "emphysema"), ("Pulmonary Emphysema", "pulmonary_emphysema"),
    ("Pulmonary Hypertension", "pulmonary_hypertension"),
    ("Pulmonary Arterial Hypertension", "pulmonary_arterial_hypertension"),
    ("Heart Failure", "heart_failure"), ("Asthma", "asthma"),
    ("COPD Exacerbation", "copd_exacerbation"),
])
def test_other_first_conditions_are_not_merged_into_copd(first, expected):
    assert condition_group([first]) == expected
    assert condition_group([" ", first, "COPD"]) == expected


def test_condition_uses_first_nonempty_entry_and_handles_missing():
    assert condition_group(["DME", "COPD"]) == "diabetic_macular_edema"
    assert condition_group(["", "  ", "COPD", "Emphysema"]) == "copd"
    assert condition_group([]) is None
    assert condition_group(["", "  "]) is None


def test_cohort_uses_exact_phase_and_first_condition_and_excludes_self():
    records = load_cohort()
    phase3 = matching_peers(records, "PHASE3", "copd", "NCT03930732")
    assert {r.registry_id for r in phase3} == {f"NCT1000000{i}" for i in range(1, 7)}
    assert all(r.phase == "PHASE3" and r.condition_group == "copd" for r in phase3)
    assert matching_peers(records, "PHASE3", "diabetic_macular_edema", None) == []
    combined = matching_peers(records, "PHASE2/PHASE3", "copd", None)
    assert [r.registry_id for r in combined] == ["NCT10000007"]
    assert not {r.registry_id for r in combined} & {r.registry_id for r in phase3}
    assert matching_peers(records, None, "copd", None) == []
    assert matching_peers(records, "PHASE3", None, None) == []
    for record in records:
        assert record.cohort_n == len(matching_peers(
            records, record.phase, record.condition_group, record.registry_id))


def test_unknown_phase_or_condition_has_no_cohort(cached_registry):
    _, registry = cached_registry
    write_study(registry, "NCT10000012", phases=[])
    write_study(registry, "NCT10000013", conditions=[])
    records = {record.registry_id: record for record in load_cohort()}
    assert records["NCT10000012"].phase is None
    assert records["NCT10000013"].condition_group is None
    assert records["NCT10000012"].cohort_n == records["NCT10000013"].cohort_n == 0


def test_missing_registry_modules_remain_unknown_instead_of_zero(cached_registry):
    _, registry = cached_registry
    path = write_study(registry, "NCT10000012")
    study = json.loads(path.read_text(encoding="utf-8"))
    ps = study["protocolSection"]
    for key in ("outcomesModule", "eligibilityModule", "contactsLocationsModule"):
        del ps[key]
    del ps["designModule"]["enrollmentInfo"]
    path.write_text(json.dumps(study), encoding="utf-8")
    record = next(record for record in load_cohort() if record.registry_id == path.stem)
    assert all(value is None for value in record.counts.model_dump().values())
    assert record.enrollment_reported is record.enrollment_type is None


@pytest.mark.parametrize("invalid", ["invalid JSON", '{"protocolSection": {}}'])
def test_invalid_study_returns_explicit_cache_error(client, cached_registry, invalid):
    _, registry = cached_registry
    (registry / "NCT10000012.json").write_text(invalid, encoding="utf-8")
    save_registry_design(client)
    response = client.get("/api/designs/peer-design/peers?version=1")
    assert response.status_code == 503
    assert response.json()["error"] == "peer_cache_invalid"
    assert response.json()["details"]["source_file"] == "peers/registry/NCT10000012.json"


def test_sparse_and_missing_values_never_receive_a_percentile():
    subject = load_cohort()[0]
    # In-memory test observations exercise the threshold; production uses only cached files.
    peers = [subject.model_copy(deep=True) for _ in range(5)]
    full = comparison_rows(subject, peers, subject.phase, subject.condition_group)[0]
    assert full.status == "ok"
    assert full.percentile == 50
    assert full.comparison == "same"
    peers[0].counts.primary_outcomes = None
    missing = comparison_rows(subject, peers, subject.phase, subject.condition_group)[0]
    assert missing.cohort_n == 5 and missing.available_n == 4
    assert missing.status == "insufficient_peers" and missing.percentile is None
    small = comparison_rows(subject, peers[1:], subject.phase, subject.condition_group)[0]
    assert small.cohort_n == small.available_n == 4 and small.percentile is None
    assert small.peer_median == subject.counts.primary_outcomes


@pytest.mark.parametrize(("own", "percentile", "comparison"), [
    (0, 0, "fewer"), (3, 60, "same"), (6, 100, "more"),
])
def test_five_available_peers_use_midrank_ties(own, percentile, comparison):
    subject = load_cohort()[0]
    subject.counts.primary_outcomes = own
    peers = [subject.model_copy(deep=True) for _ in range(5)]
    for peer, count in zip(peers, (1, 2, 3, 3, 5), strict=True):
        peer.counts.primary_outcomes = count
    row = comparison_rows(subject, peers, subject.phase, subject.condition_group)[0]
    assert row.cohort_n == row.available_n == 5
    assert row.status == "ok" and row.percentile == percentile
    assert row.peer_median == 3 and row.comparison == comparison


def test_no_reported_peer_values_or_own_value_stays_unknown():
    subject = load_cohort()[0]
    peers = [subject.model_copy(deep=True) for _ in range(5)]
    subject.counts.primary_outcomes = None
    missing_own = comparison_rows(subject, peers, subject.phase, subject.condition_group)[0]
    assert missing_own.status == "not_reported"
    assert missing_own.percentile is missing_own.comparison is None
    assert missing_own.peer_median == 3
    for peer in peers:
        peer.counts.primary_outcomes = None
    missing_peers = comparison_rows(subject, peers, subject.phase, subject.condition_group)[0]
    assert missing_peers.cohort_n == 5 and missing_peers.available_n == 0
    assert missing_peers.status == "insufficient_peers"
    assert missing_peers.peer_median is missing_peers.percentile is missing_peers.comparison is None


def test_uncached_subject_has_unknown_counts_without_invented_provenance(client):
    save_registry_design(client, registry_id="NCT99999999")
    payload = get_peers(client)
    assert payload["cohort_n"] == 7
    assert payload["source_file"] is None
    assert all(value is None for value in payload["own_counts"].values())
    assert all(row["percentile"] is None and row["source_file"] is None
               and row["status"] == "record_not_cached"
               for row in payload["rows"])


def test_reading_older_version_stays_pinned(client):
    design = save_registry_design(client)
    previous = client.get("/api/designs/peer-design")
    updated = {**design, "phase": "Phase 2/3", "conditions": ["DME"]}
    response = client.post("/api/designs", json=updated,
                           headers={**AUTHOR, "If-Match": previous.headers["etag"]})
    assert response.status_code == 201, response.text
    old = get_peers(client, version=1)
    new = get_peers(client, version=2)
    assert old["design_version"] == 1 and old["cohort_n"] == 6
    assert new["design_version"] == 2 and new["cohort_n"] == 1
    assert new["phase"] == "PHASE2/PHASE3"
    assert new["condition_group"] == "diabetic_macular_edema"
    # Counts explicitly remain those of the source registry, even after saved-design edits.
    assert old["own_counts"] == new["own_counts"]


@pytest.mark.parametrize("schedule", [[], [{"number": 1, "label": "Visit", "week": 0, "procedures": []}]])
def test_absent_procedures_skip_engine(client, fake_engine, schedule):
    save_registry_design(client, visits=schedule)
    payload = get_peers(client)
    assert payload["cost_comparison"] is None and payload["cost_reason"]
    assert fake_engine.calls == 0


def test_assumed_schedule_does_not_trigger_cost_model(client, fake_engine):
    save_registry_design(client, visits=make_design()["visits"], missing_fields=["visits"])
    payload = get_peers(client)
    assert payload["cost_comparison"] is None
    assert "missing/assumed" in payload["cost_reason"]
    assert fake_engine.calls == 0


def test_unknown_procedure_is_rejected_with_existing_error_shape(client):
    save_registry_design(client)
    response = client.get("/api/designs/peer-design/peers?version=1&removed_procedures=invented")
    assert response.status_code == 422
    assert response.json()["error"] == "invalid_levers"
    assert set(response.json()) == {"error", "message", "details"}


def test_costs_and_delta_equal_real_engine_recalculation_without_saving(make_client):
    # Actual repository engine and parameter library; no fake cost formula.
    client = make_client(
        engine_fns=EngineFns(compute=compute_scenario, compare_levers=compare_levers),
        params_dir=REPO_ROOT / "data" / "params", default_draws=100,
        mount_optional_routers=False,
    )
    design_data = save_registry_design(client, visits=make_design()["visits"])
    saved_before = client.get("/api/designs/peer-design").json()
    payload = get_peers(client, removed_procedures=["ecg", "blood_draw", "ecg"])
    cost = payload["cost_comparison"]
    assert payload["cost_reason"] is None
    assert cost["removed_procedures"] == ["blood_draw", "ecg"]
    assert cost["design_id"] == "peer-design" and cost["design_version"] == 1
    design = TrialDesign.model_validate(design_data)
    svc = client.app.state.services
    params = svc.params.current()
    baseline, counterfactual, deltas = compare_levers(
        design, Levers(), Levers(removed_procedures=["blood_draw", "ecg"]),
        params.params, seed=cost["seed"], draws=cost["draws"],
    )
    for metric in ("cost_usd", "site_staff_hours"):
        assert cost["baseline"][metric] == getattr(baseline, metric).model_dump()
        assert cost["counterfactual"][metric] == getattr(counterfactual, metric).model_dump()
        assert cost["delta"][metric] == deltas[metric].model_dump()
        assert cost["delta"][metric]["p10"] <= cost["delta"][metric]["p50"] <= cost["delta"][metric]["p90"]
        assert cost["delta"][metric]["p50"] < 0
    assert cost["parameter_set_version"] == params.version
    empty = get_peers(client)["cost_comparison"]
    assert empty["baseline"] == empty["counterfactual"]
    assert all(empty["delta"][metric][p] == 0
               for metric in ("cost_usd", "site_staff_hours") for p in ("p10", "p50", "p90"))
    assert client.get("/api/designs/peer-design").json() == saved_before
    assert len(client.get("/api/designs/peer-design/versions").json()) == 1
    assert client.get("/api/scenarios").json() == []


def test_copy_is_descriptive_without_sponsor_ranking(client):
    save_registry_design(client)
    text = json.dumps(get_peers(client)).lower()
    for forbidden in ("sponsor ranking", "leaderboard", "best sponsor", "worst sponsor",
                      "better percentile", "worse percentile", "quality score:"):
        assert forbidden not in text
    assert "complexity can have scientific reasons" in text

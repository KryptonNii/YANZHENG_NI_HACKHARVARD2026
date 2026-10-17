"""Fetch/cache behaviour: offline serves cache only; network failures give clean errors; one retry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from trialpilot_api.importers.ctgov import (
    InvalidRegistryId,
    OfflineCacheMiss,
    RegistryUnavailable,
    StudyNotFound,
    cached_study_ids,
    fetch_study,
    fetch_study_result,
    normalize_nct,
)

from .conftest import ALL_NCT, DEMO_NCT, REAL_FIXTURES

pytestmark = pytest.mark.req("URS-001")
NEW_NCT = "NCT09999999"


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _study_json(nct: str) -> dict[str, Any]:
    raw = json.loads((REAL_FIXTURES / "ctgov" / f"{DEMO_NCT}.json").read_text(encoding="utf-8"))
    raw["protocolSection"]["identificationModule"]["nctId"] = nct
    return raw


def test_normalize_nct() -> None:
    assert normalize_nct(" nct03930732 ") == "NCT03930732"
    for bad in ["", "NCT123", "ISRCTN12345678", "NCT0393073X", "NCT039307321"]:
        with pytest.raises(InvalidRegistryId):
            normalize_nct(bad)


@pytest.mark.req("URS-029")
def test_offline_serves_cache_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")

    def boom(_: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be touched offline")

    r = fetch_study_result(DEMO_NCT, client=_client(boom), refresh=True)
    assert r.cached and r.raw["protocolSection"]["identificationModule"]["nctId"] == DEMO_NCT
    assert fetch_study(DEMO_NCT)["protocolSection"]["identificationModule"]["nctId"] == DEMO_NCT


@pytest.mark.req("URS-029")
def test_offline_cache_miss_is_clean_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    with pytest.raises(OfflineCacheMiss) as e:
        fetch_study_result(NEW_NCT)
    assert e.value.status == 503 and DEMO_NCT in e.value.details["cached"]


def test_cache_first_online() -> None:
    def boom(_: httpx.Request) -> httpx.Response:
        raise AssertionError("cached study must not be re-downloaded without refresh")

    assert fetch_study_result(DEMO_NCT, client=_client(boom)).cached


def test_network_failure_twice_raises_registry_unavailable() -> None:
    calls = {"n": 0}

    def down(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("no route to host")

    with pytest.raises(RegistryUnavailable) as e:
        fetch_study_result(NEW_NCT, client=_client(down))
    assert calls["n"] == 2  # timeout/connection error -> exactly one retry
    assert e.value.status == 503 and "DEMO_OFFLINE" in e.value.message


def test_retry_once_then_success_writes_cache(isolated_dirs: dict[str, Path]) -> None:
    calls = {"study": 0}

    def flaky(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/version"):
            return httpx.Response(200, json={"apiVersion": "2.0.5", "dataTimestamp": "2026-10-16T09:00:05"})
        calls["study"] += 1
        if calls["study"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json=_study_json(NEW_NCT))

    r = fetch_study_result(NEW_NCT, client=_client(flaky))
    assert not r.cached and calls["study"] == 2
    assert r.meta["data_timestamp"] == "2026-10-16T09:00:05"
    assert (isolated_dirs["runtime"] / "ctgov" / f"{NEW_NCT}.json").exists()  # writable dir, not fixtures
    assert not (isolated_dirs["cache"] / f"{NEW_NCT}.json").exists()
    assert NEW_NCT in cached_study_ids()
    # second call is served from disk
    assert fetch_study_result(NEW_NCT, client=_client(lambda _: httpx.Response(500))).cached


def test_not_found() -> None:
    with pytest.raises(StudyNotFound) as e:
        fetch_study_result(NEW_NCT, client=_client(lambda _: httpx.Response(404)))
    assert e.value.status == 404


def test_refresh_with_network_down_falls_back_to_stale_cache() -> None:
    def down(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    r = fetch_study_result(DEMO_NCT, client=_client(down), refresh=True)
    assert r.cached and r.stale_fallback


@pytest.mark.req("URS-029")
def test_docker_data_dir_keeps_reading_committed_fixtures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A5 sets TP_DATA_DIR to a writable volume: fixtures still come from data/fixtures, writes go to the volume."""
    monkeypatch.delenv("TP_RUNTIME_CACHE_DIR")
    monkeypatch.setenv("TP_DATA_DIR", str(tmp_path / "volume"))
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    assert fetch_study_result(DEMO_NCT).cached
    monkeypatch.setenv("DEMO_OFFLINE", "0")

    def ok(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={} if req.url.path.endswith("/version") else _study_json(NEW_NCT))

    fetch_study_result(NEW_NCT, client=_client(ok))
    assert (tmp_path / "volume" / "importers" / "ctgov" / f"{NEW_NCT}.json").exists()
    assert {DEMO_NCT, NEW_NCT} <= set(cached_study_ids())


@pytest.mark.req("URS-029")
def test_all_demo_fixtures_present_with_metadata() -> None:
    for nct in ALL_NCT:
        meta = json.loads((REAL_FIXTURES / "ctgov" / f"{nct}.meta.json").read_text(encoding="utf-8"))
        assert meta["nct_id"] == nct and meta["fetched_at"] and meta["data_timestamp"]
        assert meta["source_url"].startswith("https://clinicaltrials.gov/api/v2/studies/")

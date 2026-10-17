"""OQ against the integrated API (A5 app + A7 compliance router), real parameter library."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
AUTHOR = {"X-User": "alex.author", "X-Role": "author"}


def _design(design_id: str, title: str = "OQ trial") -> dict[str, Any]:
    return {
        "id": design_id, "source": "manual", "title": title, "phase": "PHASE3",
        "enrollment_target": 60, "duration_months": 18.0, "drug_type": "biologic",
        "sites": [{"id": "s1", "name": "Site 1", "country": "US"},
                  {"id": "s2", "name": "Site 2", "country": "GB"}],
        "visits": [{"number": 1, "label": "Screening", "week": 0},
                   {"number": 2, "label": "Week 4", "week": 4}],
    }


@pytest.fixture()
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    main = pytest.importorskip("trialpilot_api.main")
    settings_mod = pytest.importorskip("trialpilot_api.settings")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("TP_SECRET_PEPPER", "oq-pepper")
    monkeypatch.setenv("TP_DEMO_PINS", "")
    monkeypatch.setenv("TP_VALIDATION_OUT", str(tmp_path / "vout"))
    settings = settings_mod.Settings(
        db_path=tmp_path / "oq.sqlite", params_dir=REPO / "data" / "params",
        fixtures_dir=tmp_path / "fixtures", science_results_path=tmp_path / "results.json",
        web_dist_dir=tmp_path / "dist", log_json=False, log_level="WARNING",
        seed_fixture_designs=False, demo_offline=True,
    )
    app = main.create_app(settings)
    with TestClient(app) as client:
        yield client
    app.state.db_engine.dispose()


def _audit(client: Any, **params: Any) -> list[dict[str, Any]]:
    r = client.get("/api/audit", params={"limit": 1000, "order": "asc", **params})
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]
    return items


@pytest.mark.req("URS-015")
def test_design_create_and_update_are_audited(api: Any) -> None:
    r = api.post("/api/designs", json=_design("oq-d1"), headers=AUTHOR)
    assert r.status_code == 201, r.text
    entries = _audit(api, object_type="design", object_id="oq-d1")
    assert [e["action"] for e in entries] == ["design.create"]
    created = entries[0]
    assert created["actor"] == "alex.author" and created["role"] == "author"
    assert created["before_hash"] is None and len(created["after_hash"]) == 64

    r = api.post("/api/designs", json=_design("oq-d1", title="OQ trial v2"), headers=AUTHOR)
    assert r.status_code in (200, 201), r.text
    entries = _audit(api, object_type="design", object_id="oq-d1")
    assert [e["action"] for e in entries] == ["design.create", "design.update"]
    assert entries[1]["before_hash"] == created["after_hash"]
    assert entries[1]["after_hash"] != created["after_hash"]


@pytest.mark.req("URS-015", "URS-017")
def test_every_api_mutation_lands_in_a_verifiable_chain(api: Any) -> None:
    before = api.get("/api/audit/verify").json()["checked"]
    for i in range(3):
        assert api.post("/api/designs", json=_design(f"oq-c{i}"), headers=AUTHOR).status_code == 201
    v = api.get("/api/audit/verify").json()
    assert v["ok"] is True and v["checked"] == before + 3


@pytest.mark.req("URS-028")
def test_audit_export_has_every_row(api: Any) -> None:
    for i in range(4):
        api.post("/api/designs", json=_design(f"oq-e{i}"), headers=AUTHOR)
    total = api.get("/api/audit", params={"limit": 1}).json()["total"]
    r = api.get("/api/audit/export.csv")
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text)))
    assert len(rows) - 1 == total >= 4


@pytest.mark.req("URS-029")
def test_health_reports_offline(api: Any) -> None:
    body = api.get("/api/health").json()
    assert body["offline"] is True

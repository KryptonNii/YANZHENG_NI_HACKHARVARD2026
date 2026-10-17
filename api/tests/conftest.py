"""Shared fixtures for A5's API tests (temp SQLite + temp parameter library per test).

The calculation engine is replaced by a FAKE in these tests only (clearly labelled numbers that
exist to exercise the HTTP layer). Production code has no placeholder engine.
Fixtures here are not autouse, so A4/A6/A7 test folders below are unaffected.
"""

from __future__ import annotations

import json
import textwrap
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from trialpilot_contracts.models import (
    Levers,
    MetricRange,
    ModuleBreakdown,
    Parameter,
    ProvenanceItem,
    ScenarioResult,
    TrialDesign,
)
from trialpilot_contracts.params import param_set_version

from trialpilot_api.engine_adapter import METRICS, EngineFns
from trialpilot_api.main import create_app
from trialpilot_api.settings import Settings

AUTHOR = {"X-User": "alex.author", "X-Role": "author"}
REVIEWER = {"X-User": "riley.reviewer", "X-Role": "reviewer"}
QA = {"X-User": "sam.qa", "X-Role": "qa"}
ADMIN = {"X-User": "admin", "X-Role": "admin"}
VIEWER = {"X-User": "val.viewer", "X-Role": "viewer"}
PINS = {"alex.author": "1111", "riley.reviewer": "2222", "sam.qa": "3333", "admin": "9999"}


# ---------------------------------------------------------------------------------------------
# Fake engine (tests only)
# ---------------------------------------------------------------------------------------------
class FakeEngine:
    """Deterministic stand-in for A2's engine. Numbers are meaningless test values."""

    def __init__(self) -> None:
        self.calls = 0
        self.raise_exc: Exception | None = None

    def compute_scenario(
        self, design: TrialDesign, levers: Levers, params: dict[str, Parameter],
        seed: int = 7, draws: int = 2000,
    ) -> ScenarioResult:
        self.calls += 1
        if self.raise_exc is not None:
            raise self.raise_exc
        sites = [s for s in design.sites if s.id not in levers.excluded_site_ids]
        moved = len(set(levers.home_visit_numbers) | set(levers.remote_visit_numbers))
        visits = max(len(design.visits), 1)
        travel = design.enrollment_target * (visits - moved) * 2.0
        cost = 1000.0 * len(sites) + 50.0 * design.enrollment_target * visits
        cost *= 1 - 0.1 * levers.remote_monitoring_share
        values = {
            "cost_usd": (cost, "usd"), "site_staff_hours": (cost / 100, "hours"),
            "patient_travel_hours": (travel, "hours"), "co2e_kg": (travel * 3, "kg_co2e"),
            "duration_months": (design.duration_months, "months"),
            "drug_waste_share": (40.0 if levers.drug_supply_strategy == "upfront" else 20.0,
                                 "percent"),
        }
        ranges = {k: MetricRange(p10=v * 0.8, p50=v, p90=v * 1.25 + seed * 0, unit=u)
                  for k, (v, u) in values.items()}
        pids = list(params)[:2]
        return ScenarioResult(
            design_id=design.id, levers=levers, **ranges,
            modules=[ModuleBreakdown(
                module="patient_assessments", cost_usd=ranges["cost_usd"],
                co2e_kg=ranges["co2e_kg"],
                provenance=[ProvenanceItem(
                    formula_id="test.fake.v1", description="TEST FAKE ENGINE",
                    inputs={"draws": draws}, parameter_ids=pids,
                    assumptions=["fake engine used by API tests"])],
            )],
            warnings=["TEST FAKE ENGINE"],
            parameter_set_version=param_set_version(params),
            computed_at=datetime.now(UTC),
        )

    def compare(self, a: ScenarioResult, b: ScenarioResult) -> dict[str, MetricRange]:
        return {m: MetricRange(p10=getattr(b, m).p10 - getattr(a, m).p10,
                               p50=getattr(b, m).p50 - getattr(a, m).p50,
                               p90=getattr(b, m).p90 - getattr(a, m).p90,
                               unit=getattr(a, m).unit) for m in METRICS}

    def drivers(self, design: TrialDesign, levers: Levers, params: dict[str, Parameter],
                metric: str, top: int = 5) -> list[tuple[str, float]]:
        return [(pid, 1.0 / (i + 1)) for i, pid in enumerate(list(params)[:top])]

    def fns(self) -> EngineFns:
        return EngineFns(compute=self.compute_scenario, compare=self.compare,
                         drivers=self.drivers, status={"engine": "test-fake"})


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------
PARAMS_YAML = textwrap.dedent("""\
    parameters:
      - id: test.ef.car_km
        label: Test car factor
        value_low: 0.1
        value_mid: 0.2
        value_high: 0.3
        unit: kg_co2e/km
        assumption: true
        rationale: test fixture only
        region: global
      - id: test.cost.visit
        label: Test visit cost
        value_low: 10
        value_mid: 20
        value_high: 30
        unit: usd/visit
        source_title: Test source
        source_url: https://example.org/test
        source_year: 2024
""")


def make_design(design_id: str | None = "design-test-1") -> dict[str, Any]:
    d: dict[str, Any] = {
        "source": "manual", "title": "Test trial", "phase": "PHASE3",
        "enrollment_target": 100, "duration_months": 24.0, "drug_type": "biologic",
        "sites": [
            {"id": "s1", "name": "Site 1", "country": "US"},
            {"id": "s2", "name": "Site 2", "country": "GB"},
            {"id": "s3", "name": "Site 3", "country": "DE"},
        ],
        "visits": [
            {"number": 1, "label": "Screening", "week": 0, "procedures": [
                {"code": "blood_draw", "label": "Blood draw", "ships_sample": True,
                 "sample_temp": "frozen_-80"}]},
            {"number": 2, "label": "Week 4", "week": 4, "procedures": [
                {"code": "ecg", "label": "ECG"}]},
            {"number": 3, "label": "Week 12", "week": 12, "can_be_remote": True},
            {"number": 4, "label": "End of study", "week": 52},
        ],
        "missing_fields": ["visits"],
    }
    if design_id is not None:
        d["id"] = design_id
    return d


# ---------------------------------------------------------------------------------------------
# App fixtures
# ---------------------------------------------------------------------------------------------
@pytest.fixture()
def fake_engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture()
def make_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_engine: FakeEngine
) -> Iterator[Callable[..., TestClient]]:
    monkeypatch.setenv("TP_SECRET_PEPPER", "test-pepper")
    monkeypatch.delenv("TP_DEMO_PINS", raising=False)
    monkeypatch.delenv("DEMO_OFFLINE", raising=False)
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    (params_dir / "test.yaml").write_text(PARAMS_YAML, encoding="utf-8")
    apps: list[Any] = []

    def _make(engine_fns: EngineFns | None = None, **overrides: Any) -> TestClient:
        kwargs: dict[str, Any] = dict(
            db_path=tmp_path / f"api{len(apps)}.sqlite", params_dir=params_dir,
            fixtures_dir=tmp_path / "fixtures", science_results_path=tmp_path / "results.json",
            web_dist_dir=tmp_path / "dist", log_json=False, log_level="WARNING",
            seed_fixture_designs=False, demo_offline=False,
        )
        kwargs.update(overrides)
        app = create_app(Settings(**kwargs), engine_fns=engine_fns or fake_engine.fns())
        apps.append(app)
        return TestClient(app)

    yield _make
    for app in apps:
        app.state.db_engine.dispose()
    try:  # leave A7's process-wide state clean for their tests
        from trialpilot_api.compliance import records, store

        records.unregister_resolver("scenario")
        store.get_store().close()
    except Exception:
        pass


@pytest.fixture()
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


@pytest.fixture()
def design_id(client: TestClient) -> str:
    r = client.post("/api/designs", json=make_design(), headers=AUTHOR)
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def audit_actions(client: TestClient, object_id: str) -> list[str]:
    """Audit actions recorded for one object, oldest first (A7's log, or the stub's)."""
    svc = client.app.state.services  # type: ignore[attr-defined]
    if svc.compliance.status.get("audit") == "a7":
        r = client.get("/api/audit", params={"object_id": object_id, "order": "asc",
                                             "limit": 1000})
        assert r.status_code == 200, r.text
        return [e["action"] for e in r.json()["items"]]
    return [e.action for e in svc.compliance.stub_entries(object_id)]


def save_scenario(client: TestClient, design_id: str, headers: dict[str, str] = AUTHOR,
                  **levers: Any) -> dict[str, Any]:
    r = client.post("/api/scenarios", headers=headers, json={
        "name": "Scenario B", "design_id": design_id, "levers": levers})
    assert r.status_code == 201, r.text
    return dict(r.json())


def dumps(obj: Any) -> str:
    return json.dumps(obj, indent=1)

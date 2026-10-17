"""Fixtures for A5's API tests (temp SQLite + temp parameter library per test).

Helpers and test data live in `a5_support.py`. Fixtures here are not autouse, so the A4/A6/A7
test folders below are unaffected.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from a5_support import AUTHOR, PARAMS_YAML, FakeEngine, make_design
from fastapi.testclient import TestClient

from trialpilot_api.engine_adapter import EngineFns
from trialpilot_api.main import create_app
from trialpilot_api.settings import Settings


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

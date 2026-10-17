"""OQ fixtures: the real integrated API (A5 app + real engine + real parameter library + A7
compliance), each app on its own temporary SQLite file, offline."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[3]
AUTHOR = {"X-User": "alex.author", "X-Role": "author"}
PINS = {"alex.author": "1111", "riley.reviewer": "2222", "sam.qa": "3333"}


@pytest.fixture()
def make_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], Any]]:
    main = pytest.importorskip("trialpilot_api.main")
    settings_mod = pytest.importorskip("trialpilot_api.settings")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("TP_SECRET_PEPPER", "oq-pepper")
    monkeypatch.setenv("TP_DEMO_PINS", "")
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    monkeypatch.setenv("TP_VALIDATION_OUT", str(tmp_path / "vout"))
    apps: list[Any] = []

    def _make() -> Any:
        n = len(apps)
        settings = settings_mod.Settings(
            db_path=tmp_path / f"oq{n}.sqlite", params_dir=REPO / "data" / "params",
            fixtures_dir=REPO / "data" / "fixtures", science_results_path=tmp_path / "r.json",
            web_dist_dir=tmp_path / "dist", log_json=False, log_level="WARNING",
            seed_fixture_designs=False, demo_offline=True,
        )
        app = main.create_app(settings)
        apps.append(app)
        return TestClient(app)

    yield _make
    for app in apps:
        app.state.db_engine.dispose()
    try:
        from trialpilot_api.compliance import records

        records.unregister_resolver("scenario")
    except Exception:
        pass


@pytest.fixture()
def api(make_api: Callable[[], Any]) -> Any:
    return make_api()

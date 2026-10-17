"""Fixtures for A4 importer tests. Everything that writes goes to tmp dirs; real fixtures are read-only."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from trialpilot_api.importers import ctgov
from trialpilot_api.importers.paths import fixtures_dir
from trialpilot_api.importers.router import get_auditor, router

REAL_FIXTURES = fixtures_dir()
DEMO_NCT = "NCT03930732"
ALL_NCT = ["NCT03930732", "NCT04429503", "NCT04456673", "NCT04535986"]


@pytest.fixture(autouse=True)
def isolated_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Copies of the ctgov cache + protocol fixtures in tmp; runtime cache in tmp; no politeness delay."""
    cache = tmp_path / "ctgov"
    cache.mkdir()
    for p in (REAL_FIXTURES / "ctgov").glob("NCT*.json"):
        shutil.copy(p, cache / p.name)
    protos = tmp_path / "protocols"
    shutil.copytree(REAL_FIXTURES / "protocols", protos, ignore=shutil.ignore_patterns(".cache", "*.pdf"))
    runtime = tmp_path / "runtime"
    monkeypatch.setenv("TP_CTGOV_CACHE_DIR", str(cache))
    monkeypatch.setenv("TP_PROTOCOLS_DIR", str(protos))
    monkeypatch.setenv("TP_RUNTIME_CACHE_DIR", str(runtime))
    monkeypatch.setenv("TP_GEONAMES_DIR", str(REAL_FIXTURES / "ctgov" / "geonames"))
    monkeypatch.delenv("DEMO_OFFLINE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(ctgov, "MIN_INTERVAL_S", 0.0)
    return {"cache": cache, "protocols": protos, "runtime": runtime}


@pytest.fixture
def audit_log() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def client(audit_log: list[dict[str, Any]]) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router, prefix="/api/import")

    def fake_audit(actor: str, role: str, action: str, object_type: str, object_id: str,
                   before_hash: str | None, after_hash: str | None, reason: str | None = None) -> None:
        audit_log.append({"actor": actor, "role": role, "action": action, "object_type": object_type,
                          "object_id": object_id, "before_hash": before_hash, "after_hash": after_hash,
                          "reason": reason})

    app.dependency_overrides[get_auditor] = lambda: fake_audit
    with TestClient(app) as c:
        yield c

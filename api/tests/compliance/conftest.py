"""Fixtures for compliance tests: every test gets its own temporary SQLite file."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trialpilot_api.compliance import hashing, records, store


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "req(id, ...): URS requirement id(s) this test verifies")


@pytest.fixture()
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[store.Store]:
    monkeypatch.setenv("TP_SECRET_PEPPER", "test-pepper")
    monkeypatch.delenv("TP_DEMO_PINS", raising=False)
    monkeypatch.setenv("TP_VALIDATION_OUT", str(tmp_path / "vout"))
    st = store.configure(tmp_path / "compliance.sqlite")
    yield st
    hashing.set_clock(None)
    for rt in ("scenario",):
        records.unregister_resolver(rt)
    st.close()


class FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self.t = start or datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t = self.t + timedelta(seconds=seconds)


@pytest.fixture()
def clock(db: store.Store) -> FakeClock:
    c = FakeClock()
    hashing.set_clock(c)
    return c


PINS = {
    "alex.author": "1111",
    "riley.reviewer": "2222",
    "sam.qa": "3333",
    "admin": "9999",
    "val.viewer": "0000",
}

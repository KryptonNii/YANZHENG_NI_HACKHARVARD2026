"""pytest plugin used by `tpv` (stdlib + pytest only: it is loaded into every package's own venv).

- registers the `req` marker: `@pytest.mark.req("URS-012")` or `@pytest.mark.req("URS-012", "URS-013")`
- `--tpv-collect=FILE`: with `--collect-only`, writes every collected test and its requirement ids
- `--tpv-results=FILE`: writes per-test outcomes (passed/failed/error/skipped/xfailed/xpassed)
- `--tpv-prefix=api/`: prepended to node ids so they are repo-relative

Outcomes are recorded exactly as pytest reports them; nothing is inferred or invented.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("tpv", "TrialPilot validation toolkit")
    group.addoption("--tpv-results", default=None, help="write per-test results JSON here")
    group.addoption("--tpv-collect", default=None, help="write collected tests JSON here")
    group.addoption("--tpv-prefix", default="", help="prefix for node ids (e.g. 'api/')")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "req(*ids): URS requirement id(s) this test verifies")
    if config.getoption("--tpv-results") or config.getoption("--tpv-collect"):
        config.pluginmanager.register(_Recorder(config), "tpv-recorder")


def _utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class _Recorder:
    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.prefix: str = config.getoption("--tpv-prefix") or ""
        self.started_at = _utc()
        self.t0 = time.perf_counter()
        self.tests: dict[str, dict[str, Any]] = {}
        self.collection_errors: list[dict[str, Any]] = []

    def _nid(self, nodeid: str) -> str:
        return self.prefix + nodeid

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        for item in items:
            reqs: list[str] = []
            for mark in item.iter_markers("req"):
                for arg in mark.args:
                    for rid in str(arg).replace(",", " ").split():
                        if rid not in reqs:
                            reqs.append(rid)
            path, _, name = item.nodeid.partition("::")
            self.tests[item.nodeid] = {
                "id": self._nid(item.nodeid),
                "file": self.prefix + path,
                "name": name,
                "reqs": reqs,
                "outcome": None,
                "duration_s": 0.0,
                "message": None,
            }

    def pytest_collectreport(self, report: pytest.CollectReport) -> None:
        if report.failed:
            self.collection_errors.append(
                {"id": self._nid(report.nodeid), "message": str(report.longrepr)[-4000:]}
            )

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        t = self.tests.setdefault(
            report.nodeid,
            {"id": self._nid(report.nodeid), "file": "", "name": report.nodeid, "reqs": [],
             "outcome": None, "duration_s": 0.0, "message": None},
        )
        t["duration_s"] = round(t["duration_s"] + float(report.duration or 0.0), 4)
        outcome: str | None = None
        if hasattr(report, "wasxfail"):
            outcome = "xfailed" if report.skipped else ("xpassed" if report.passed else None)
        elif report.when == "setup":
            if report.failed:
                outcome = "error"
            elif report.skipped:
                outcome = "skipped"
        elif report.when == "call":
            outcome = "passed" if report.passed else ("failed" if report.failed else "skipped")
        elif report.when == "teardown" and report.failed and t["outcome"] == "passed":
            outcome = "error"
        if outcome is not None:
            t["outcome"] = outcome
        if report.failed or (report.skipped and report.when == "setup"):
            text = str(report.longrepr)
            t["message"] = text[-4000:] if report.failed else text[-500:]

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        collect_path = self.config.getoption("--tpv-collect")
        results_path = self.config.getoption("--tpv-results")
        payload = {
            "prefix": self.prefix,
            "started_at": self.started_at,
            "finished_at": _utc(),
            "duration_s": round(time.perf_counter() - self.t0, 3),
            "exitstatus": int(exitstatus),
            "tests": list(self.tests.values()),
            "collection_errors": self.collection_errors,
        }
        for path in (collect_path, results_path):
            if path:
                Path(path).parent.mkdir(parents=True, exist_ok=True)
                Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

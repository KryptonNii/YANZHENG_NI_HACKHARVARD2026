"""Ops tests use only temporary databases and an explicit no-op audit sink for pure simulations."""

from __future__ import annotations

import pytest

from trialpilot_api.ops.fixtures import load_demo_design
from trialpilot_api.ops.params import load_ops_params
from trialpilot_api.ops.plan import build_plan
from trialpilot_api.ops.simulator import simulate
from trialpilot_api.ops.store import TrialState


def pytest_configure(config):
    config.addinivalue_line("markers", "req(id): validation requirement covered by this test")


@pytest.fixture(scope="session")
def ops_plan():
    return build_plan(load_demo_design(), load_ops_params(42))


@pytest.fixture(scope="session")
def simulated(ops_plan):
    return simulate(ops_plan, load_ops_params(42), 42, "demo")


@pytest.fixture(scope="module")
def demo_state():
    return TrialState("demo-40", load_demo_design(), None, 42, 0, "demo", 599, 600,
                      audit_sink=lambda **kwargs: None)

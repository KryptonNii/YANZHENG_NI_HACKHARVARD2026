"""MCP server tools, driven through the official SDK client in-process (fake engine)."""

from __future__ import annotations

from typing import Any

import anyio
import pytest
from a5_support import AUTHOR, FakeEngine, audit_actions, make_design, save_scenario
from fastapi.testclient import TestClient
from mcp.client import Client
from trialpilot_contracts.models import ProvenanceItem, ScenarioResult

from trialpilot_api.mcp_server import Backend, build_server

TOOLS = {"list_designs", "list_scenarios", "compute_scenario", "compare_scenarios",
         "explain_metric", "get_parameter"}


def call(client: TestClient, name: str, args: dict[str, Any] | None = None) -> tuple[bool, Any]:
    """(is_error, structured result or error text) for one tool call."""
    async def run() -> tuple[bool, Any]:
        backend = Backend(app=client.app)
        try:
            async with Client(build_server(backend)) as c:
                res = await c.call_tool(name, args or {})
        finally:
            await backend.aclose()
        if res.is_error:
            return True, " ".join(getattr(b, "text", "") for b in res.content)
        return False, res.structured_content

    return anyio.run(run)


def test_tools_are_listed_and_read_only(client: TestClient) -> None:
    async def run() -> list[Any]:
        async with Client(build_server(Backend(app=client.app))) as c:
            return list((await c.list_tools()).tools)

    tools = anyio.run(run)
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True and t.annotations.destructive_hint is False


def test_list_and_compute(client: TestClient, design_id: str) -> None:
    err, out = call(client, "list_designs")
    assert not err and [d["id"] for d in out["designs"]] == [design_id]
    err, out = call(client, "compute_scenario",
                    {"design_id": design_id, "levers": {"remote_monitoring_share": 0.5}})
    assert not err, out
    assert set(out["metrics"]) == {"cost_usd", "site_staff_hours", "patient_travel_hours",
                                   "co2e_kg", "duration_months", "drug_waste_share"}
    cost = out["metrics"]["cost_usd"]
    assert cost["p10"] <= cost["p50"] <= cost["p90"] and cost["unit"] == "usd"
    assert out["cache"] == "miss" and out["levers"]["remote_monitoring_share"] == 0.5
    assert "TEST FAKE ENGINE" in out["warnings"]
    _, again = call(client, "compute_scenario",
                    {"design_id": design_id, "levers": {"remote_monitoring_share": 0.5}})
    assert again["cache"] == "hit" and again["metrics"] == out["metrics"]


def test_api_errors_reach_the_model(client: TestClient, design_id: str) -> None:
    err, text = call(client, "compute_scenario",
                     {"design_id": design_id, "levers": {"remote_monitoring": 0.5}})
    assert err and "validation_error" in text and "remote_monitoring" in text
    err, text = call(client, "compute_scenario", {"design_id": "nope"})
    assert err and "design_not_found" in text
    err, text = call(client, "explain_metric", {"metric": "happiness", "design_id": design_id})
    assert err and "invalid_metric" in text
    err, text = call(client, "explain_metric", {"metric": "co2e_kg"})
    assert err and "scenario_id" in text


def test_explain_metric_filters_formulas_and_adds_driver_sources(
    make_client: Any, fake_engine: FakeEngine
) -> None:
    plain = fake_engine.compute_scenario

    def with_provenance(*args: Any, **kwargs: Any) -> ScenarioResult:
        res = plain(*args, **kwargs)
        mod = res.modules[0]
        items = [
            ProvenanceItem(formula_id="carbon.patient_travel.v1", description="km x factor",
                           inputs={"patients": 10, "result_p10": 1, "result_p50": 2,
                                   "result_p90": 3, "result_unit": "kg_co2e"},
                           parameter_ids=["test.ef.car_km"], assumptions=["round trip"]),
            ProvenanceItem(formula_id="cost.site_staff_visits.v1", description="cost",
                           inputs={"result_p50": 5}, parameter_ids=["test.cost.visit"]),
        ]
        return res.model_copy(update={"modules": [mod.model_copy(update={"provenance": items})]})

    fake_engine.compute_scenario = with_provenance  # type: ignore[method-assign]
    client = make_client()
    design = client.post("/api/designs", json=make_design(),
                         headers=AUTHOR).json()
    err, out = call(client, "explain_metric", {"metric": "co2e_kg", "design_id": design["id"]})
    assert not err, out
    assert [f["formula_id"] for f in out["formulas"]] == ["carbon.patient_travel.v1"]
    f = out["formulas"][0]
    assert f["contribution"] == {"p10": 1, "p50": 2, "p90": 3, "unit": "kg_co2e"}
    assert f["inputs"] == {"patients": 10} and f["assumptions"] == ["round trip"]
    assert out["range"]["unit"] == "kg_co2e"
    sourced = {d["parameter_id"]: d for d in out["drivers"]}
    assert sourced["test.cost.visit"]["source_url"] == "https://example.org/test"
    err, out = call(client, "explain_metric",
                    {"metric": "duration_months", "design_id": design["id"]})
    assert not err and out["formulas"] == []
    assert any("forecast" in w for w in out["warnings"])


def test_compare_saved_scenarios_and_nothing_is_written(client: TestClient, design_id: str) -> None:
    a = save_scenario(client, design_id)
    b = save_scenario(client, design_id, remote_monitoring_share=1.0)
    before = audit_actions(client, a["id"]) + audit_actions(client, b["id"])
    err, out = call(client, "compare_scenarios", {"a_id": a["id"], "b_id": b["id"]})
    assert not err, out
    cost = out["deltas"]["cost_usd"]
    assert cost["p50"] < 0 and cost["direction"].startswith("decrease")
    assert out["deltas"]["drug_waste_share"]["direction"].startswith("no change")
    err, listed = call(client, "list_scenarios", {"design_id": design_id})
    assert not err and {s["id"] for s in listed["scenarios"]} == {a["id"], b["id"]}
    err, sc = call(client, "explain_metric", {"metric": "cost_usd", "scenario_id": a["id"]})
    assert not err and sc["range"] == a["result"]["cost_usd"]
    err, p = call(client, "get_parameter", {"parameter_id": "test.cost.visit"})
    assert not err and p["source_year"] == 2024
    after = audit_actions(client, a["id"]) + audit_actions(client, b["id"])
    assert after == before  # read-only: no tool writes an audit entry


@pytest.mark.parametrize("url", ["http://127.0.0.1:9"])
def test_unreachable_api_url_is_a_tool_error(client: TestClient, url: str) -> None:
    async def run() -> Any:
        async with Client(build_server(Backend(base_url=url))) as c:
            return await c.call_tool("list_designs", {})

    res = anyio.run(run)
    assert res.is_error and "not reachable" in res.content[0].text

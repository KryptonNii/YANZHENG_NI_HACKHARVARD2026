"""MCP server: lets Claude Code and other agents query TrialPilot's engine (owner: A5, optional).

    uv run --project api python -m trialpilot_api.mcp_server              # stdio transport
    claude mcp add trialpilot -- uv run --project api python -m trialpilot_api.mcp_server

Built on the official MCP Python SDK (`mcp` 2.x, `MCPServer`). Every tool goes through the
TrialPilot HTTP API, so validation, caching, error codes and parameter versions are exactly what
the web app gets. By default the API runs in-process (same settings, SQLite file and parameter
library as `uvicorn trialpilot_api.main:create_app --factory`); set `TP_MCP_API_URL`
(e.g. `http://localhost:8000`) to query a running API instead.

Read-only by design (MASTER §2.5: AI may draft text but never writes results, evidence or
signatures): no tool saves, submits, approves or signs anything. Numbers are returned as the
engine's P10/P50/P90 ranges with units; `null` means unknown (the warnings say why).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from . import __version__
from .engine_adapter import METRICS

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

# Provenance formula ids start with the metric family they feed (A2 engine, docs/model.md).
FORMULA_PREFIX: dict[str, tuple[str, ...]] = {
    "cost_usd": ("cost.",),
    "co2e_kg": ("carbon.",),
    "site_staff_hours": ("workload.",),
    "patient_travel_hours": ("burden.patient_travel",),
    "duration_months": ("forecast.",),
    "drug_waste_share": ("supply.",),
}
A3_METRICS = {"duration_months", "drug_waste_share"}

RANGE_NOTE = ("Ranges are P10/P50/P90 over the Monte Carlo draws (triangular low/mid/high per "
              "parameter); null means unknown, see warnings. Parameter sources: get_parameter.")

INSTRUCTIONS = """TrialPilot scenario simulator for clinical trials (read-only).
Start with list_designs to find a trial design id, then compute_scenario with design levers.
Report every number as its P10/P50/P90 range with the unit; never collapse it to one value.
Use explain_metric to show where a number comes from (formulas, parameters, sources) and
compare_scenarios for saved scenarios (per-draw deltas B - A). Nothing here saves or signs."""


class Backend:
    """HTTP access to the TrialPilot API: a URL, or an in-process ASGI app (default)."""

    def __init__(self, base_url: str | None = None, app: Any = None) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._app = app
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            if self._base_url:
                self._http = httpx.AsyncClient(base_url=self._base_url, timeout=120)
            else:
                if self._app is None:
                    from .main import create_app

                    self._app = create_app()
                self._http = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self._app),
                    base_url="http://trialpilot.local", timeout=120,
                )
        return self._http

    async def call(self, method: str, path: str, **kwargs: Any) -> tuple[Any, httpx.Response]:
        try:
            r = await self._client().request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ToolError(f"TrialPilot API not reachable ({type(exc).__name__}: {exc}). "
                            "Start it or unset TP_MCP_API_URL to run it in-process.") from exc
        try:
            body = r.json()
        except ValueError:
            body = None
        if r.status_code >= 400:
            if isinstance(body, dict) and "error" in body:
                details = body.get("details") or {}
                extra = f" Details: {details}" if details else ""
                raise ToolError(f"{body['error']} (HTTP {r.status_code}): {body.get('message')}"
                                f"{extra}")
            raise ToolError(f"HTTP {r.status_code} from {path}: {r.text[:300]}")
        return body, r

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None


def _check_metric(metric: str) -> None:
    if metric not in METRICS:
        raise ToolError(f"invalid_metric: metric must be one of {', '.join(METRICS)}.")


def _range(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    return {k: r.get(k) for k in ("p10", "p50", "p90", "unit")}


def _direction(delta: dict[str, Any]) -> str:
    lo, hi = delta.get("p10"), delta.get("p90")
    if lo is None or hi is None:
        return "unknown"
    if lo == 0 and hi == 0:
        return "no change (B - A is 0 from P10 to P90)"
    if lo > 0:
        return "increase (P10 of B - A above 0)"
    if hi < 0:
        return "decrease (P90 of B - A below 0)"
    return "uncertain (the P10-P90 range of B - A includes 0)"


def _matching_provenance(result: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    prefixes = FORMULA_PREFIX[metric]
    items: list[dict[str, Any]] = []
    for module in result.get("modules", []):
        for p in module.get("provenance", []):
            if not str(p.get("formula_id", "")).startswith(prefixes):
                continue
            inputs = dict(p.get("inputs") or {})
            contribution = {k[len("result_"):]: inputs.pop(k) for k in list(inputs)
                            if k.startswith("result_")}
            items.append({
                "module": module.get("module"),
                "formula_id": p.get("formula_id"),
                "description": p.get("description"),
                "contribution": contribution or None,
                "inputs": inputs,
                "parameter_ids": p.get("parameter_ids", []),
                "assumptions": p.get("assumptions", []),
            })
    items.sort(key=lambda i: -float((i["contribution"] or {}).get("p50") or 0.0))
    return items


def build_server(backend: Backend | None = None) -> MCPServer:
    api = backend or Backend(base_url=os.environ.get("TP_MCP_API_URL") or None)
    server = MCPServer(name="trialpilot", title="TrialPilot", version=__version__,
                       instructions=INSTRUCTIONS)

    @server.tool(annotations=READ_ONLY)
    async def list_designs() -> dict[str, Any]:
        """List stored trial designs (latest version of each): id, title, registry id, size."""
        rows, _ = await api.call("GET", "/api/designs")
        return {"designs": [{
            "id": d["id"], "version": d["version"], "title": d["title"],
            "registry_id": d.get("registry_id"), "phase": d.get("phase"),
            "source": d.get("source"), "enrollment_target": d["enrollment_target"],
            "duration_months": d["duration_months"], "site_count": d["site_count"],
            "visit_count": d["visit_count"], "countries": d.get("countries", []),
            "missing_fields": d.get("missing_fields", []),
        } for d in rows]}

    @server.tool(annotations=READ_ONLY)
    async def list_scenarios(design_id: str | None = None) -> dict[str, Any]:
        """List saved scenarios (newest first), optionally for one design: id, name, version,
        status (draft/submitted/approved/rejected) and headline metric ranges."""
        params = {"design_id": design_id} if design_id else {}
        rows, _ = await api.call("GET", "/api/scenarios", params=params)
        return {"scenarios": [{
            "id": s["id"], "name": s["name"], "version": s["version"], "status": s["status"],
            "design_id": s["design_id"], "design_version": s["design_version"],
            "author": s["author"], "created_at": s["created_at"],
            "parameter_set_version": s["parameter_set_version"],
            "metrics": {k: _range(v) for k, v in s.get("metrics", {}).items()},
        } for s in rows]}

    @server.tool(annotations=READ_ONLY)
    async def compute_scenario(
        design_id: str,
        design_version: int,
        levers: dict[str, Any] | None = None,
        seed: int = 7,
        draws: int = 2000,
    ) -> dict[str, Any]:
        """Compute cost, site staff hours, patient travel hours, CO2e, duration and drug waste
        (P10/P50/P90) for a stored design under design levers. Nothing is saved.

        levers (all optional; unknown keys are rejected):
          remote_monitoring_share 0..1, home_visit_numbers [int], remote_visit_numbers [int],
          local_lab_share 0..1, drug_supply_strategy "upfront"|"on_demand",
          removed_procedures [procedure code], excluded_site_ids [site id].
        """
        body = {"design_id": design_id, "design_version": design_version,
                "levers": levers or {}, "seed": seed, "draws": draws}
        result, resp = await api.call("POST", "/api/scenarios/compute", json=body)
        return {
            "design_id": result["design_id"],
            "design_version": int(resp.headers["X-Design-Version"]),
            "levers": result["levers"],
            "metrics": {m: _range(result.get(m)) for m in METRICS},
            "modules": [{"module": m["module"], "cost_usd": _range(m.get("cost_usd")),
                         "co2e_kg": _range(m.get("co2e_kg"))} for m in result.get("modules", [])],
            "warnings": result.get("warnings", []),
            "parameter_set_version": result["parameter_set_version"],
            "seed": seed, "draws": draws,
            "compute_ms": resp.headers.get("X-Compute-Ms"),
            "cache": resp.headers.get("X-Cache"),
            "note": RANGE_NOTE,
        }

    @server.tool(annotations=READ_ONLY)
    async def compare_scenarios(a_id: str, b_id: str) -> dict[str, Any]:
        """Compare two saved scenarios on the same design version: per-draw deltas B - A
        (common random numbers) for every headline metric, with the direction it supports."""
        out, _ = await api.call("POST", "/api/scenarios/compare",
                                json={"a_id": a_id, "b_id": b_id})
        deltas = out.get("deltas", {})
        return {
            "a_id": out["a_id"], "b_id": out["b_id"],
            "deltas": {m: {**(_range(deltas[m]) or {}), "direction": _direction(deltas[m])}
                       for m in METRICS if m in deltas},
            "module_deltas": {k: _range(v) for k, v in deltas.items() if k not in METRICS},
            "a_metrics": {k: _range(v) for k, v in out.get("a_metrics", {}).items()},
            "b_metrics": {k: _range(v) for k, v in out.get("b_metrics", {}).items()},
            "same_parameter_set": out.get("same_parameter_set"),
            "seed": out.get("seed"), "draws": out.get("draws"),
            "parameter_set_version": out.get("parameter_set_version"),
            "warnings": out.get("warnings", []),
            "note": "Deltas are B - A computed per Monte Carlo draw, then P10/P50/P90.",
        }

    @server.tool(annotations=READ_ONLY)
    async def explain_metric(
        metric: str,
        design_id: str | None = None,
        design_version: int | None = None,
        scenario_id: str | None = None,
        levers: dict[str, Any] | None = None,
        top: int = 5,
        seed: int = 7,
        draws: int = 2000,
    ) -> dict[str, Any]:
        """Explain one metric: its range, the formulas that produce it (with inputs, parameter
        ids and assumptions, largest first) and the top parameters driving its uncertainty
        (with sources). Pass a saved scenario_id, or a design_id (+ optional levers).

        metric: cost_usd | site_staff_hours | patient_travel_hours | co2e_kg |
                duration_months | drug_waste_share
        """
        _check_metric(metric)
        warnings: list[str] = []
        if scenario_id:
            row, _ = await api.call("GET", f"/api/scenarios/{scenario_id}")
            result = row["result"]
            drivers_call: tuple[str, str, dict[str, Any]] = (
                "GET", f"/api/scenarios/{scenario_id}/drivers",
                {"params": {"metric": metric, "top": top}})
        elif design_id:
            if design_version is None:
                raise ToolError("Pass design_version from list_designs with design_id.")
            body = {"design_id": design_id, "design_version": design_version,
                    "levers": levers or {}, "seed": seed, "draws": draws}
            result, _ = await api.call("POST", "/api/scenarios/compute", json=body)
            drivers_call = ("POST", "/api/scenarios/drivers",
                            {"json": {**body, "metric": metric, "top": top}})
        else:
            raise ToolError("Pass scenario_id (a saved scenario) or design_id (+ levers).")
        warnings.extend(result.get("warnings", []))
        formulas = _matching_provenance(result, metric)
        if not formulas:
            warnings.append(
                f"No per-module formula items for {metric}: it comes from the enrollment forecast "
                "/ drug supply simulation (A3, docs/model_forecast.md)." if metric in A3_METRICS
                else f"The engine returned no provenance items for {metric}.")
        drivers: list[dict[str, Any]] = []
        drivers_error = None
        method, path, kwargs = drivers_call
        try:
            out, _ = await api.call(method, path, **kwargs)
            drivers = out.get("drivers", [])
            warnings.extend(w for w in out.get("warnings", []) if w not in warnings)
        except ToolError as exc:
            drivers_error = str(exc)
        return {
            "metric": metric,
            "range": _range(result.get(metric)),
            "formulas": formulas,
            "drivers": drivers,
            "drivers_error": drivers_error,
            "parameter_set_version": result.get("parameter_set_version"),
            "warnings": warnings,
            "note": "drivers.share = the parameter's share of this metric's variance (engine "
                    "definition). " + RANGE_NOTE,
        }

    @server.tool(annotations=READ_ONLY)
    async def get_parameter(parameter_id: str) -> dict[str, Any]:
        """One parameter from the library: low/mid/high values, unit, source (title, URL,
        year) or the rationale when it is a flagged assumption, and its version."""
        p, _ = await api.call("GET", f"/api/params/{parameter_id}")
        return dict(p)

    return server


def main() -> None:
    from .logs import configure_logging
    from .settings import get_settings

    settings = get_settings()
    # stdout is the MCP protocol channel: logs go to stderr (first handler wins).
    configure_logging(settings.log_level, settings.log_json, stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per tool call otherwise
    build_server().run("stdio")


if __name__ == "__main__":
    main()

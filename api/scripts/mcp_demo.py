"""Record a real MCP session against TrialPilot (stdio transport, real engine, temp database).

    uv run --project api python api/scripts/mcp_demo.py --out api/MCP_DEMO.md

1. Creates a temporary data dir (DEMO_OFFLINE=1) so the human's database is never touched.
2. Saves two scenarios on the first fixture design as the demo author (through the API, like
   the web app would), because the MCP server itself is read-only.
3. Starts `python -m trialpilot_api.mcp_server` as a subprocess and calls its tools over stdio
   with the official SDK client, writing every call and (abbreviated) result as Markdown.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import httpx
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters

AUTHOR = {"X-User": "alex.author", "X-Role": "author"}
ROOT = Path(__file__).resolve().parents[2]


def _num(x: Any) -> str:
    if x is None:
        return "unknown"
    a = abs(x)
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= div:
            return f"{x / div:.2f}{suffix}"
    return f"{x:.3g}" if a < 10 else f"{x:.1f}"


def _short(obj: Any, max_items: int = 4) -> Any:
    """Keep transcripts readable: a P10/P50/P90 range becomes one line "P10 / P50 / P90 unit",
    long lists are cut (and say so), numbers rounded. Presentation only."""
    if isinstance(obj, dict) and {"p10", "p50", "p90", "unit"} <= set(obj) and len(obj) <= 5:
        line = f"{_num(obj['p10'])} / {_num(obj['p50'])} / {_num(obj['p90'])} {obj['unit']}"
        return f"{line} | {obj['direction']}" if "direction" in obj else line
    if isinstance(obj, dict):
        return {k: _short(v, max_items) for k, v in obj.items()}
    if isinstance(obj, list):
        head = [_short(v, max_items) for v in obj[:max_items]]
        return head + ([f"... {len(obj) - max_items} more"] if len(obj) > max_items else [])
    if isinstance(obj, float):
        return round(obj, 3 if abs(obj) < 10 else 1)
    return obj


async def prepare(env: dict[str, str]) -> tuple[str, list[str]]:
    os.environ.update(env)
    from trialpilot_api.main import create_app
    from trialpilot_api.settings import Settings

    app = create_app(Settings())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://demo") as http:
        designs = (await http.get("/api/designs")).json()
        boreas = next((d for d in designs if d.get("registry_id") == "NCT03930732"), designs[0])
        ids = []
        for name, levers in (("A: baseline", {}),
                             ("B: 50% remote monitoring + on-demand supply",
                              {"remote_monitoring_share": 0.5,
                               "drug_supply_strategy": "on_demand"})):
            r = await http.post("/api/scenarios", headers=AUTHOR, json={
                "name": name, "design_id": boreas["id"], "levers": levers})
            r.raise_for_status()
            ids.append(r.json()["id"])
    app.state.db_engine.dispose()
    return boreas["id"], ids


async def session(env: dict[str, str], design_id: str, a_id: str, b_id: str) -> list[str]:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "trialpilot_api.mcp_server"], env=env, cwd=str(ROOT))
    lines: list[str] = []
    async with Client(params) as c:
        tools = (await c.list_tools()).tools
        lines.append("### tools/list\n")
        for t in tools:
            ro = t.annotations.read_only_hint if t.annotations else None
            lines.append(f"- `{t.name}` (read-only: {ro}) - {(t.description or '').splitlines()[0]}")
        steps: list[tuple[str, dict[str, Any]]] = [
            ("list_designs", {}),
            ("compute_scenario", {"design_id": design_id}),
            ("compute_scenario", {"design_id": design_id, "levers": {
                "remote_monitoring_share": 0.5, "drug_supply_strategy": "on_demand"}}),
            ("compute_scenario", {"design_id": design_id, "levers": {"remote_monitoring": 0.5}}),
            ("explain_metric", {"metric": "co2e_kg", "design_id": design_id, "top": 3}),
            ("compare_scenarios", {"a_id": a_id, "b_id": b_id}),
        ]
        top_param = None
        for name, args in steps:
            t0 = time.perf_counter()
            res = await c.call_tool(name, args)
            ms = (time.perf_counter() - t0) * 1000
            lines.append(f"\n### tools/call `{name}`\n\n```json\n{json.dumps(args, indent=1, ensure_ascii=False)}\n```\n")
            if res.is_error:
                text = " ".join(getattr(b, "text", "") for b in res.content)
                lines.append(f"**is_error: true** ({ms:.0f} ms)\n\n```text\n{text[:600]}\n```")
                continue
            out = res.structured_content
            if name == "explain_metric" and out.get("drivers"):
                top_param = out["drivers"][0]["parameter_id"]
            lines.append(f"Result ({ms:.0f} ms round trip):\n\n```json\n"
                         f"{json.dumps(_short(out), indent=1, ensure_ascii=False)}\n```")
        if top_param:
            res = await c.call_tool("get_parameter", {"parameter_id": top_param})
            lines.append(f"\n### tools/call `get_parameter`\n\n```json\n"
                         f"{json.dumps({'parameter_id': top_param})}\n```\n\nResult:\n\n```json\n"
                         f"{json.dumps(_short(res.structured_content), indent=1, ensure_ascii=False)}\n```")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="tp-mcp-demo-"))
    env = {**os.environ, "TP_DATA_DIR": str(tmp), "DEMO_OFFLINE": "1", "TP_LOG_LEVEL": "WARNING"}
    env.pop("TP_MCP_API_URL", None)
    design_id, (a_id, b_id) = anyio.run(prepare, env)
    lines = anyio.run(session, env, design_id, a_id, b_id)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    header = [
        "# TrialPilot MCP server - recorded session",
        "",
        f"Recorded {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by "
        "`api/scripts/mcp_demo.py` (git `" + commit + "`): real stdio transport, real A2 engine "
        "+ A3 forecast/supply, A10 parameter library, DEMO_OFFLINE=1, temporary database. "
        "The two saved scenarios were created by the script as the demo author (the MCP server "
        "cannot save). Ranges are shown as `P10 / P50 / P90 unit` (k = thousand, M = million); "
        "long lists are cut; nothing else is edited.",
        "",
    ]
    text = "\n".join(header + lines) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()

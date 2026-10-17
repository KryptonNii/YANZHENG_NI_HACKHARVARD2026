# TrialPilot API (`trialpilot_api`)

FastAPI + SQLite (WAL). Owner: A5. Routers from A4 (`/api/import`), A6 (`/api/ops`) and A7
(`/api/audit`, `/api/approvals`, `/api/validation`, `/api/signatures`, `/api/compliance`) are mounted
when they import cleanly; until then those paths answer `501 not_ready`.

```bash
uv sync --project api
uv run --project api python -m trialpilot_api.seed                 # DB + parameter library + fixture designs
uv run --project api uvicorn trialpilot_api.main:app --port 8000 --reload
uv run --project api pytest api/tests -q --ignore=api/tests/compliance --ignore=api/tests/importers
```

Interactive docs: `http://localhost:8000/docs`.

## Conventions

- **Errors** (every endpoint): `{"error": "<code>", "message": "<plain English>", "details": {...}}`;
  `details.request_id` matches the `X-Request-ID` response header and the JSON log line.
- **Demo identity only**: changes need `X-User` (e.g. `alex.author`). The role comes from A7's user
  registry (URS-023), never from the request: `X-Role` is optional, and if sent it must match the
  registered role (`403 role_mismatch`); unregistered users get `403 unknown_user`; `viewer` cannot
  change data. There is no login. Signing (A7) re-authenticates with a demo PIN. Only if A7's package
  cannot be imported (stub mode, `/api/health` → `compliance.roles: "header"`) is `X-Role` trusted.
- **Every change is audited** before it is applied (A7 `audit.append`; a hash-chained stub if A7 is
  absent). If the change then fails, a compensating `<action>.failed` entry is appended.
- **Ranges and unknowns**: every metric is `{p10, p50, p90, unit}`. A metric the engine cannot compute
  (missing parameter) is `null` = unknown, never 0, and `warnings` says which input is missing.
- **Immutability**: designs and parameter rows are never updated (new versions instead); a scenario is
  frozen once submitted. SQLite triggers enforce this even against raw SQL.

## Endpoints

| Method | Path | What |
|---|---|---|
| GET | `/api/health` | status, `offline`, DB, parameter library, engine + module readiness |
| GET | `/api/designs` | latest version of every stored design (summaries) |
| POST | `/api/designs` | store a `TrialDesign`. A new id is version 1. Identical content is 200. Different content for an existing id needs `If-Match` (409 `design_changed` otherwise) and cannot change `registry_id` / `source` (422 `design_identity_immutable`) |
| GET | `/api/designs/{id}` | the `TrialDesign` (`?version=`); headers `X-Design-Version`, `ETag` |
| GET | `/api/designs/{id}/versions` | all versions |
| POST | `/api/scenarios/compute` | `{design_id \| design, design_version?, levers, seed?, draws?}` → `ScenarioResult` (includes `forecast` / `supply` or null) |
| POST | `/api/scenarios/drivers` | top drivers for an unsaved scenario (`metric`, `top`) |
| POST | `/api/scenarios/compare` | `{a_id, b_id}` → per-draw deltas b − a |
| POST | `/api/scenarios` | compute + save a draft. `design_version` is required (422 `design_version_required` if omitted) |
| GET | `/api/scenarios` | list (`?design_id=&lineage_id=&status=&latest_only=true`) |
| GET | `/api/scenarios/{id}` | full record incl. result, approval request and signatures |
| PATCH | `/api/scenarios/{id}` | edit a draft (author/admin); submitted → `409 scenario_immutable` |
| POST | `/api/scenarios/{id}/versions` | new draft version (the base row never changes) |
| GET | `/api/scenarios/{id}/versions` | all versions of the lineage |
| POST | `/api/scenarios/{id}/submit` | freeze + create an `ApprovalRequest` (A7) |
| GET | `/api/scenarios/{id}/drivers` | `?metric=co2e_kg&top=5`, with the parameters the scenario used |
| GET | `/api/params` | parameter library with sources (`?prefix=&ids=a,b&assumption=`) |
| GET | `/api/params/{id}` | one `Parameter` (current) |
| GET | `/api/params/{id}/history` | every stored value of a parameter |
| GET | `/api/science/results` | A10's reproduction results (`science/out/results.json`) |
| GET | `/api/export/scenario/{id}.csv` | design report as CSV (one table, `section` column) |
| GET | `/api/export/scenario/{id}.pdf` | design report as PDF (results, assumptions, sources, signatures) |

Compute headers: `X-Compute-Ms`, `X-Cache: hit|miss` (key = design hash, levers hash, parameter set
version, seed, draws), `X-Parameter-Set-Version`. A stored design also returns `X-Design-Version`
and `ETag` (the design hash). Send that version as `design_version` on compute and on save.

`ScenarioResult.forecast` and `.supply` are the contract v4 display subset of A3's `to_dict()`
(`ForecastView`, `SupplyView`). Extra producer keys are not copied. A missing detail is `null`.
Nested percentiles that A3 could not compute stay `null` (never 0). Shipment counts keep unit
`count`. When supply ran on fewer draws than the scenario requested, `warnings` includes A3's
own sentence (for example `Supply simulated on 100 forecast draws in weekly steps.`).

### Design version, ETag, and conflicts (A8)

```bash
# The version on screen is the response header, not a field of TrialDesign.
curl -sD - -o design.json "$API/api/designs/$DESIGN_ID"
# X-Design-Version: 2
# ETag: "0123abcd...64 hex chars..."

# Compute that exact version. The same two headers come back.
curl -sD - -H 'Content-Type: application/json' -X POST "$API/api/scenarios/compute" -d '{
  "design_id": "'"$DESIGN_ID"'",
  "design_version": 2,
  "levers": {"remote_monitoring_share": 0.5}}'

# Save must send that design_version. Omitting it is 422 design_version_required
# and does not store a row. details.latest_version is the current tip, not permission
# to save the screen's numbers against it.
curl -s -H 'X-User: alex.author' -H 'Content-Type: application/json' \
  -X POST "$API/api/scenarios" -d '{
    "name": "Scenario B",
    "design_id": "'"$DESIGN_ID"'",
    "design_version": 2,
    "levers": {"remote_monitoring_share": 0.5}}'

# Editing an existing design. If-Match is the strong ETag just read.
# A missing tag, *, or a weak tag is 409 design_changed.
curl -s -H 'X-User: alex.author' -H 'Content-Type: application/json' \
  -H 'If-Match: "0123abcd...64 hex chars..."' \
  -X POST "$API/api/designs" -d @edited-design.json
```

`409 design_changed` body (the current version, so the client can reload — not so it can resend the stale body with the new tag):

```json
{
  "error": "design_changed",
  "message": "Design '41774a6b-4338-595f-bee7-493e4a5e62b6' is now version 3. Send If-Match with that version's ETag to store a new version. Do not reuse a stale body with the new tag.",
  "details": {
    "design_id": "41774a6b-4338-595f-bee7-493e4a5e62b6",
    "version": 3,
    "design_hash": "0123abcd...64 hex chars...",
    "etag": "\"0123abcd...64 hex chars...\""
  }
}
```

The 409 response also repeats `ETag` and `X-Design-Version`. Changing `registry_id` or `source` is `422 design_identity_immutable` even when `If-Match` is current. `details.fields` lists which of the two changed.

Compute response excerpt, BOREAS `41774a6b-4338-595f-bee7-493e4a5e62b6` version 1, seed 7, 2000 draws, default levers (2026-10-17, this machine; values rounded to 1 decimal, the API returns full precision):

```json
{
  "forecast": {
    "months_to_full_enrollment": {"p10": 7.6, "p50": 8.8, "p90": 10.8, "unit": "months"},
    "milestone_dates": {
      "database_lock": {"p10": 26.0, "p50": 27.2, "p90": 29.2, "unit": "months"}
    },
    "enrollment_curve": [[0.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]]
  },
  "supply": {
    "kits_needed": {"p10": 7846.7, "p50": 8165.0, "p90": 16152.2, "unit": "kits"},
    "kits_produced": {"p10": 19445.1, "p50": 25085.5, "p90": 50558.0, "unit": "kits"},
    "kits_wasted": {"p10": 11383.0, "p50": 17004.5, "p90": 34377.3, "unit": "kits"},
    "waste_share": {"p10": 57.1, "p50": 65.9, "p90": 73.3, "unit": "percent"},
    "shipments": {"p10": 333.9, "p50": 438.0, "p90": 818.1, "unit": "count"},
    "stockout_probability": 0.0
  },
  "warnings": [
    "Large trial: drug supply simulated on 170 draws (not 500) to stay within the compute budget; supply ranges are noisier than the other metrics.",
    "Supply simulated on 170 forecast draws in weekly steps.",
    "Design field 'visits' is not from the source; a labelled assumption fills it (design v1 missing_fields)",
    "Design field 'sites.expected_enrollment' is not from the source; a labelled assumption fills it (design v1 missing_fields)"
  ]
}
```

The same run also has `first_patient_in`, `last_patient_in`, and `last_patient_last_visit`, each a full `{p10, p50, p90, unit: "months"}` range (P50 about 4.1, 8.8, and 25.9 months). `enrollment_curve` rows are `[month, p10, p50, p90]` cumulative patients (14 rows on this run). `milestone_dates` are months from study start. `stockout_probability` is the share of supply draws with any site stockout (`0.0` here means none of those 170 draws stocked out). A missing `supply` or `forecast` is `null`, not a zero probability and not a zero range. When A3 returns an unknown range, all three percentiles are `null` and the unit is unchanged. Shipment counts stay unit `count`.

## curl walkthrough (demo steps 2–3)

```bash
API=http://localhost:8000
AUTHOR=(-H "X-User: alex.author" -H "X-Role: author")

curl -s $API/api/health | jq '{status, offline, engine: .engine.ready, params: .params}'

# 1. store a design (or import one: POST /api/import/ctgov/{NCT})
curl -s "${AUTHOR[@]}" -H 'Content-Type: application/json' -X POST $API/api/designs -d '{
  "id": "demo-design", "source": "manual", "title": "Demo trial", "enrollment_target": 300,
  "duration_months": 24, "drug_type": "biologic",
  "sites": [{"id": "s1", "name": "Site 1", "country": "US"}, {"id": "s2", "name": "Site 2", "country": "GB"}],
  "visits": [{"number": 1, "label": "Screening", "week": 0,
              "procedures": [{"code": "blood_draw", "label": "Blood draw", "ships_sample": true}]},
             {"number": 2, "label": "Week 12", "week": 12, "can_be_remote": true}]}' | jq .id

# 2. flip levers -> ranges + provenance (headers show compute time, cache, and design version)
curl -si -H 'Content-Type: application/json' -X POST $API/api/scenarios/compute -d '{
  "design_id": "demo-design",
  "design_version": 1,
  "levers": {"remote_monitoring_share": 0.5, "home_visit_numbers": [2], "drug_supply_strategy": "on_demand"}}' \
  | grep -iE '^x-(compute-ms|cache|design-version)|"cost_usd"|"forecast"'

# 3. what drives carbon?
curl -s -H 'Content-Type: application/json' -X POST $API/api/scenarios/drivers \
  -d '{"design_id": "demo-design", "metric": "co2e_kg"}' | jq '.drivers[] | {parameter_id, share, source_url}'

# 4. save scenario B, submit it, try to self-approve (blocked), then reviewer + QA sign
SID=$(curl -s "${AUTHOR[@]}" -H 'Content-Type: application/json' -X POST $API/api/scenarios \
  -d '{"name": "Scenario B", "design_id": "demo-design", "design_version": 1, "levers": {"remote_monitoring_share": 0.5}}' | jq -r .id)
AID=$(curl -s "${AUTHOR[@]}" -X POST $API/api/scenarios/$SID/submit | jq -r .approval_id)
curl -s "${AUTHOR[@]}" -H 'Content-Type: application/json' -X POST $API/api/approvals/$AID/sign \
  -d '{"meaning": "reviewed", "pin": "1111"}' | jq .error                       # "self_approval_forbidden"
curl -s -H "X-User: riley.reviewer" -H 'Content-Type: application/json' -X POST $API/api/approvals/$AID/sign \
  -d '{"meaning": "reviewed", "pin": "2222"}' > /dev/null
curl -s -H "X-User: sam.qa" -H 'Content-Type: application/json' -X POST $API/api/approvals/$AID/sign \
  -d '{"meaning": "approved", "pin": "3333"}' > /dev/null
curl -s $API/api/scenarios/$SID | jq '{status, signatures: [.approval.signatures[] | {signer, meaning, signed_at}]}'
curl -s $API/api/audit/verify | jq .                                              # {"ok": true, ...}

# 5. a submitted scenario cannot change; make a new version instead
curl -s "${AUTHOR[@]}" -H 'Content-Type: application/json' -X PATCH $API/api/scenarios/$SID -d '{"name": "x"}' | jq .error
curl -s "${AUTHOR[@]}" -H 'Content-Type: application/json' -X POST $API/api/scenarios/$SID/versions \
  -d '{"levers": {"local_lab_share": 1.0}}' | jq '{id, version, parent_id, status}'

# 6. exports
curl -s -o scenario.pdf $API/api/export/scenario/$SID.pdf
curl -s $API/api/export/scenario/$SID.csv | head
```

Demo PINs are A7's fictional demo values (alex.author 1111 · riley.reviewer 2222 · sam.qa 3333; override
with `TP_DEMO_PINS`).

## Settings (environment or `.env`)

| Variable | Default | Meaning |
|---|---|---|
| `DEMO_OFFLINE` | `0` | `1` = no network; importers use cached fixtures (reported by `/api/health`) |
| `TP_DATA_DIR` | — | writable data dir (Docker volume); SQLite goes to `$TP_DATA_DIR/trialpilot.sqlite` |
| `TP_DB_PATH` | `<repo>/var/trialpilot.sqlite` | explicit SQLite path (wins over `TP_DATA_DIR`) |
| `TP_PARAMS_DIR` | `<repo>/data/params` | parameter library (reloaded when a YAML file changes) |
| `TP_FIXTURES_DIR` | `<repo>/data/fixtures` | `trials/*.json` designs are stored at startup |
| `TP_SCIENCE_RESULTS` | `<repo>/science/out/results.json` | served by `/api/science/results` |
| `TP_WEB_DIST` | `<repo>/web/dist` | built web app served at `/` when present |
| `TP_CORS_ORIGINS` | Vite dev ports 5173, 5178 | comma-separated |
| `TP_DEFAULT_DRAWS` / `TP_MAX_DRAWS` / `TP_DEFAULT_SEED` | 2000 / 20000 / 7 | Monte Carlo |
| `TP_COMPUTE_CACHE_SIZE` | 256 | in-process LRU entries |
| `TP_COMPUTE_CONCURRENCY` | 2 | engine runs at once; the rest queue (`X-Queue-Ms`) |
| `TP_MCP_API_URL` | — | MCP server only: query this running API instead of running it in-process |
| `TP_LOG_LEVEL` / `TP_LOG_JSON` | INFO / 1 | structured JSON logs with request ids |

## For other modules

- **SSE (A6)**: `from trialpilot_api.sse import sse_response` → `return sse_response(request, f"ops:{trial_id}")`;
  publish with `request.app.state.services.broker.publish(channel, event, data)`. 15 s heartbeat,
  replay after `Last-Event-ID` (header or `?last_event_id=`). See the module docstring.
- **Audit (A4/A6)**: `request.app.state.services.compliance.append(actor, role, action, object_type,
  object_id, before_hash, after_hash, reason)` (A7's function, or the stub), or A7's `audit.append` directly.
- **Scenario record hash (A7)**: registered with `compliance.records.register_resolver("scenario", ...)`.

## MCP server (Claude Code / agents)

`trialpilot_api/mcp_server.py` exposes the engine to MCP clients with the official MCP Python SDK
(`mcp` 2.3.0, MIT, `MCPServer`, stdio transport). Six **read-only** tools: `list_designs`,
`list_scenarios`, `compute_scenario`, `compare_scenarios`, `explain_metric`, `get_parameter`. No tool
saves, submits, approves or signs (AI never writes results or signatures); every call goes through
this API, so validation, error codes, caching and parameter versions are the same as in the web app.

```bash
# add to Claude Code (from the repo root)
claude mcp add trialpilot -- uv run --project api python -m trialpilot_api.mcp_server
# run it directly (stdio); logs go to stderr
uv run --project api python -m trialpilot_api.mcp_server
# query a running API instead of starting one in-process
TP_MCP_API_URL=http://localhost:8000 uv run --project api python -m trialpilot_api.mcp_server
```

- `compute_scenario(design_id, levers?, seed=7, draws=2000)` → six metrics as P10/P50/P90 + unit,
  per-module cost/CO2e, warnings, parameter-set version, `compute_ms`, `cache`. Unknown lever keys
  come back as a tool error (`validation_error`), never silently dropped.
- `compare_scenarios(a_id, b_id)` → per-draw deltas B − A for two saved scenarios, each with a
  direction (`increase` / `decrease` / `no change` / `uncertain` when the P10–P90 range includes 0).
- `explain_metric(metric, design_id | scenario_id, levers?, top=5)` → the metric's range, the formulas
  that feed it (module, formula id, description, contribution range, inputs, parameter ids,
  assumptions; largest first) and the top variance drivers with sources. Duration and drug waste come
  from A3's forecast / supply simulation, which has no per-module formula items; the tool says so.

Recorded session (real stdio transport, real engine, temporary database):
[`MCP_DEMO.md`](MCP_DEMO.md), regenerate with `uv run --project api python api/scripts/mcp_demo.py
--out api/MCP_DEMO.md`. In-process mode builds the API on the first call (a few seconds); times in
the transcript depend on machine load. Tests: `api/tests/test_mcp_server.py` (SDK client in-process).

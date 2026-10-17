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
- **Demo identity only**: changes need `X-User` (e.g. `alex.author`) and `X-Role`
  (`author | reviewer | qa | admin | viewer`). There is no login; `viewer` cannot change data.
  Signing (A7) re-authenticates with a demo PIN.
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
| POST | `/api/designs` | store a `TrialDesign` (new version if the id exists and content changed) |
| GET | `/api/designs/{id}` | the `TrialDesign` (`?version=`); headers `X-Design-Version`, `ETag` |
| GET | `/api/designs/{id}/versions` | all versions |
| POST | `/api/scenarios/compute` | `{design_id \| design, levers, seed?, draws?}` → `ScenarioResult` |
| POST | `/api/scenarios/drivers` | top drivers for an unsaved scenario (`metric`, `top`) |
| POST | `/api/scenarios/compare` | `{a_id, b_id}` → per-draw deltas b − a |
| POST | `/api/scenarios` | compute + save a draft |
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
version, seed, draws), `X-Parameter-Set-Version`.

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

# 2. flip levers -> ranges + provenance (headers show compute time and cache)
curl -si -H 'Content-Type: application/json' -X POST $API/api/scenarios/compute -d '{
  "design_id": "demo-design",
  "levers": {"remote_monitoring_share": 0.5, "home_visit_numbers": [2], "drug_supply_strategy": "on_demand"}}' \
  | grep -iE '^x-(compute-ms|cache)|"cost_usd"'

# 3. what drives carbon?
curl -s -H 'Content-Type: application/json' -X POST $API/api/scenarios/drivers \
  -d '{"design_id": "demo-design", "metric": "co2e_kg"}' | jq '.drivers[] | {parameter_id, share, source_url}'

# 4. save scenario B, submit it, try to self-approve (blocked), then reviewer + QA sign
SID=$(curl -s "${AUTHOR[@]}" -H 'Content-Type: application/json' -X POST $API/api/scenarios \
  -d '{"name": "Scenario B", "design_id": "demo-design", "levers": {"remote_monitoring_share": 0.5}}' | jq -r .id)
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
| `TP_LOG_LEVEL` / `TP_LOG_JSON` | INFO / 1 | structured JSON logs with request ids |

## For other modules

- **SSE (A6)**: `from trialpilot_api.sse import sse_response` → `return sse_response(request, f"ops:{trial_id}")`;
  publish with `request.app.state.services.broker.publish(channel, event, data)`. 15 s heartbeat,
  replay after `Last-Event-ID` (header or `?last_event_id=`). See the module docstring.
- **Audit (A4/A6)**: `request.app.state.services.compliance.append(actor, role, action, object_type,
  object_id, before_hash, after_hash, reason)` (A7's function, or the stub), or A7's `audit.append` directly.
- **Scenario record hash (A7)**: registered with `compliance.records.register_resolver("scenario", ...)`.

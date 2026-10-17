# A4 review of A5 (API server, database, deployment)

Reviewer: A4 (importers) · 2026-10-16 ~22:45 ET · working tree on `dev` at `020a19e`. A5's tracked route files had no
uncommitted edits; `deps.py` / `main.py` / `compliance_adapter.py` had uncommitted A5 work, reviewed as found.

How I tested:
- A5's tests: `uv run --project api pytest api/tests/test_app_basics.py api/tests/test_scenarios.py api/tests/test_approval_export_sse.py api/tests/test_mcp_server.py` → **60 passed**.
- A real server on my port 8004: `uvicorn trialpilot_api.main:app`, `DEMO_OFFLINE=1`, temp SQLite, A4/A6/A7 mounted.
- Probes with httpx/curl, and the A8 UI on 5177 against it.

## Findings (most important first)

### 1. MAJOR: a saved or approved scenario never says its visit schedule is a placeholder
- **Where:** `api/trialpilot_api/routes_scenarios.py:256-263` (`_compute` adds only lever warnings); `api/trialpilot_api/routes_export.py:60,114` (the CSV/PDF assumption list holds engine provenance assumptions only).
- **Input → output:** BOREAS v1 (A4 template schedule; `missing_fields: ["visits", "sites.expected_enrollment"]`) → `POST /api/scenarios/compute`. `warnings` has 2 entries (sample temperature, intervention excluded) and none says the 11 visits are an assumed template. The CSV export of a saved scenario has no `missing_fields` line either; it contains "visits" and "template" only inside unrelated parameter text.
- **Why it matters:** §2.2 says unknown ≠ zero and the reader must see which assumption filled a gap. The scenario record (`result` is part of `scenario_content`, so it is signed) and the exported PDF are what QA approves and what leaves the system. The approver sees a cost of about $222M but not that every per-visit number rests on a placeholder schedule. A8's simulator shows the design's `missing_fields` in a collapsible box, so the gap is in the stored, signed and exported record.
- **Fix:** in `_compute`, for each `design.missing_fields` entry append a warning such as "Design field 'visits' is not from the source; a labelled assumption fills it (design v1 missing_fields)". It then flows into the signed result, the CSV `warning` rows (`routes_export.py:111-112`) and the PDF's "Warnings and assumptions" section (`routes_export.py:220-222`). Also add a `design,missing_fields` row to the CSV.

### 2. MAJOR: any editor can silently replace a design's latest version, and unpinned saves pick it up
- **Where:** `api/trialpilot_api/routes_designs.py:85-113` (`store_design`) and `:134-158` (`create_design`). There is no precondition (`If-Match` on the `ETag` you already send) and no check that `registry_id` / `source` stay the same.
- **Input → output:** riley.reviewer `POST /api/designs` with BOREAS's id, `enrollment_target: 1` and a new title → 201, `X-Design-Version: 3`. Next, alex.author's `POST /api/scenarios {design_id, levers}` with no version → saved on **v3**: cost P50 **$32.8M**, against $178.6M on the v2 schedule alex was looking at. Re-ran it with a realistic edit (v3 = enrollment 100): the A8 page showed $178.7M and the saved row said $49.4M.
- **Why it matters:** lost update / wrong record. The numbers that get submitted and approved can differ from the ones the author reviewed, and nothing warns them. It is audited, but only visible if someone reads the audit log.
- **Fix:** require `If-Match: "<design_hash>"` when POSTing an existing id, answering 409 `design_changed` with the current version when it doesn't match; reject a changed `registry_id`/`source` (422). Also consider making `design_version` required on `POST /api/scenarios` (A8 has the version).

### 3. MINOR: the same warning appears twice in different words
- **Where:** `api/trialpilot_api/routes_scenarios.py:211-217`.
- **Input → output:** levers `home_visit_numbers: [3, 4, 5]` on BOREAS. The engine already returns "Visit 3 (Week 4) is not marked remote-capable…" for each visit, and A5 adds "Visits [3, 4, 5] are not marked can_be_remote…". The UI shows 4 lines for 3 visits.
- **Fix:** drop A5's sentence when the engine has warned (for example, any engine warning containing "remote-capable"), or keep only A5's, with its "a human must confirm" wording.

### 4. MINOR: designs with impossible schedules are stored and computed without a warning
- **Where:** `api/trialpilot_api/routes_designs.py:161-174` (`_check_design`).
- **Input → output:** visits `[{number 1, week 10}, {number 2, week 2}]` → 201, and compute → 200 (duration 12 months, no warning about the order). `Site.expected_enrollment: -5` → 201. A4's `/api/import/protocol/apply` rejects the first with 422 `weeks_not_increasing`, but `POST /api/designs` bypasses it.
- **Fix:** add the same checks to `_check_design` (weeks non-decreasing by visit number; `expected_enrollment >= 0`; `lat` in [-90, 90], `lon` in [-180, 180]).

### 5. MINOR: the first compute after startup misses the latency target
- **Where:** `api/trialpilot_api/engine_adapter.py` (A3 cache cold).
- **Input → output:** BOREAS v1 `POST /api/scenarios/compute` right after startup → 677 ms (`X-Compute-Ms`). The §5 target is <300 ms P50. Your handoff already says the warm slider path is 54 ms, so this concerns only the first click in the demo.
- **Fix (optional):** after seeding, compute the baseline of each seeded design once in a background thread to warm the A3 cache.

## Checks that passed
- **§2 error shape:** every path I hit returns `{"error","message","details"}`: ApiError, 422 validation (bad type, unknown lever key → `extra_forbidden`, malformed JSON, draws 20001), unknown route 404, unknown design 404 `design_not_found`. A request id is in `details`.
- **§2 compliance in code:**
  - Anonymous mutation → 401 `identity_required`; viewer → 403 `forbidden_role`.
  - The role comes from A7's registry (`role_mismatch` / `unknown_user`, checked through A4's router as well).
  - Audit-before-write; the chain verifies (`/api/audit/verify` ok, 17 entries).
  - A4 imports are audited with the registry role.
- **Double submit:** 4 concurrent `POST /submit` → one 200, three 409, exactly one approval request.
- **Unknown ≠ zero (engine via A5):** no sites → "63 sites assumed … global parameters"; enrolment 0 → "No drug kits modelled"; unknown metrics serialised as null.
- **Lever validation:** share 1.5, unknown visit/site/procedure, excluding every site → 422 `invalid_levers` with plain-English problems.
- **Offline:** `/api/health` reports `offline: true`; A5's own code makes no outbound calls (the MCP server's httpx targets the configured TrialPilot API only).
- **MCP server:** read-only, as documented (only stateless compute/compare/drivers POSTs).
- **Contract with A4:**
  - Imported UUIDv5 ids are kept on store.
  - Storing an identical design gives 200 with no new version.
  - The applied protocol schedule stores as v2 with "visits" removed from `missing_fields`.
  - Compute on 19 protocol visits works (cost P50 $178.6M, CO2e P50 825 t with the demo levers).
  - A5's design hash equals A7's `record_hash`, so the import audit entry and the stored design hash match.
- **Exports:** CSV and PDF return 200; unknown values are written as "unknown"; parameter sources are listed per row.

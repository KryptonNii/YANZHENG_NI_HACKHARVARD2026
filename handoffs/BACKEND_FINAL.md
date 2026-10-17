# TrialPilot backend integration

Status: **BACKEND_READY** — interfaces and backend code committed, 2026-10-17 ET.
This is interface readiness, not QA approval or a claim that the full cold latency
target is met. Complete combined-commit validation is starting; see final section.

Backend code: **`f91cdb213a76979d08e9decc98e646f67bc05b30`**.
Includes frontend code **`e425ca25541e69b40328337aba0ef5145fcd8d91`** as parent.
Retains A3 optimization/docs **`56ada2645bed33021e79372cb4fc21a2bec0fc0d`**
and A2 null/WTT implementation **`851a17dbb3bafd01bbe16c40c98289ff9363a8df`**.

## Ownership and baseline

- Started on shared `dev`, HEAD `56ada2645bed33021e79372cb4fc21a2bec0fc0d`.
- A3 forecast/supply optimization, strict type fixes and model documentation already
  committed in that revision. Preserve and verify them rather than reconstruct them.
- Existing unstaged A4/A5/A6/A7/A10 changes under api, data, science, validation and
  their handoffs belong to this backend takeover. No staged changes at initial inspection.
- Frontend task owns web (except generated root contracts), README, A8/A9/A11,
  pitch materials. Those edits remain untouched. Existing `prof.out` is unowned;
  it is neither removed nor committed. Backend test ports: 8007/5180; frontend: 8008/5181.
- Historical evidence under validation/out is retained. The 851a17d report at
  `validation/out/clean-clone/20261017T033016Z` remains 542 passed / 2 failed,
  including cold latency median 642 ms and stale science snapshot.

- Intake backend diff and file hashes are preserved at
  `validation/out/backend/20261017T040152Z-intake/`. The prior science JSON is
  `previous-science-results.json` there. No historical validation evidence removed.
- 75 explicit owned paths were committed with `git commit --only -- <paths>`.
  Frontend files were not staged except generator-produced `web/src/contracts.ts`.
  README files were left unchanged by this task, including inherited dirty
  `api/README.md`; this handoff is the current API guidance.

## Stable API (contract additive v5)

Errors use `{ "error": "code", "message": "explanation", "details": { ... } }`.
Missing numerical percentiles are JSON null, not zero. Forecast/supply details
can themselves be null when unavailable; the warning explains the omission.

1. `GET /api/designs/{id}` returns TrialDesign plus `X-Design-Version` and strong
   `ETag`. `?version=N` reads that immutable historical version.
2. `POST /api/designs` creates an unseen ID. Changed content for an existing ID
   requires `If-Match: "<hash read with that body>"`. Missing, stale, weak or
   racing updates return **409 design_changed**, current version/hash/ETag.
   Identical content is an idempotent 200. Changed content creates a new version.
   `registry_id` or `source` changes return **422 design_identity_immutable**;
   neither field is silently replaced. Concurrent requests using the same ETag
   produce one successful new version and one 409; history stays immutable.
3. `POST /api/scenarios/compute` and `/api/scenarios/drivers` require
   `design_version` with `design_id`. Missing version is **422
   design_version_required**. Inline `design` must omit both `design_id` and
   `design_version`; an inline version is **422 inline_design_version**.
4. `POST /api/scenarios` requires the same explicit `design_version` and
   recomputes that exact version. PATCH/new scenario versions default to the
   existing saved design version, never the newest design. Headers identify the
   computed version/ETag, parameter set, cache status and compute/queue timings.
5. Saves bind the design hash/version, result, warnings, missing-field warnings,
   A3 provenance/assumptions, parameter-set version, seed and draws into the
   scenario record hash. Submission locks the row; signatures bind that hash.
   CSV/PDF exports read the saved version and retain missing fields, warnings,
   assumptions, provenance, sampling counts and forecast/supply details.
   MCP compute also requires explicit `design_version`; list_designs supplies it.

Example request (replace the id/version with the values read):

```json
{"design_id":"<id>","design_version":2,"levers":{"drug_supply_strategy":"on_demand"},"seed":201,"draws":2000}
```

The forecast object contains `months_to_full_enrollment` (MetricRange in months),
`milestone_dates` (months from study start), `enrollment_curve` tuples
`[month,p10,p50,p90]` (cumulative patients), `draws_requested`, `draws_used`,
`curve_draws_used`, and `provenance`.
Supply contains `kits_needed`, `kits_produced`, `kits_wasted` (kits), `waste_share`
(percent), `shipments` (count), `stockout_probability` (0–1 share),
`draws_requested`, `draws_used`, and `provenance`.
Historical missing counts remain null. All producer warnings are retained.
Current real BOREAS cold calls: forecast 2,000 requested/used, curve 500;
supply 500 requested, 170–171 used for seeds 200–206. Existing budgets unchanged.

## Import, review and operations field meanings

- `POST /api/import/ctgov/{NCT}` returns `notes` for older consumers plus
  `field_notes[]` and `notes_by_field`. A field note is
  `{field,kind,assumption,text,clears_when_present}`. `kind` is fact, missing or
  assumption; a fact never becomes an assumption. `_unscoped` groups notes not
  tied to a field. Only notes explicitly marked `clears_when_present` may clear
  after the relevant missing field is resolved. Dates/geocoding assumptions
  remain visible; `missing_fields` matches the design.
- `GET /api/import/procedure-codes` and importer `procedure_group_labels` give
  names for the complete procedure code group. Group labels must not be replaced
  by the first assessment's label. Unknown `other:*` codes remain distinct.
- `POST /api/import/protocol/review`: `bulk_accepted` counts a subset already in
  `accepted`, not extra rows. Greater than accepted gives **422
  bulk_accepted_exceeds_accepted**. Unchanged-accept share excludes bulk rows.
  Legacy rows without bulk counts stay unknown; the aggregate share is null
  if any included review has unknown bulk counts. Status values: `no_reviews`,
  `unknown`, `no_individual_review`, `review_log_only`. This is not measured LLM
  accuracy, and old review logs are not rewritten.
- Operations health site/country rows expose:

```json
{"weekly_enrollment":{"unit":"patients","actual_per_week":[0,2],"actual_cumulative":[0,2],"plan":[{"p10":0,"p50":0,"p90":1},{"p10":0,"p50":2,"p90":4}]}}
```

  Example shape only. Index 0 is days [0,7); arrays include complete weeks only,
  omit the open week, and retain complete zero-event weeks. No completed week
  means empty arrays. Country actuals sum sites; country plan bands sum the
  existing site bands (not a fresh joint-distribution percentile calculation).
  Backup plan remains zero. Actual opening emits `site_activated` from CTMS,
  with activation date/country/region/status; no fabricated vendor milestone.
  `data/fixtures/ops/weekly_enrollment_example.json` is explicitly simulated.

## Science and model boundaries

203 parameters, 58 labelled assumptions; parameter-set hash **1249d0f0eed8**.
Per-trial activity overrides have their own parameter-set hashes in the output.
`data/params/NEEDED.md` matches the live catalog including eight WTT IDs.
`science/out/results.json` and schema are regenerated deterministically with
seed 7 and 2,000 draws. No coefficient was tuned toward the paper.

| Engine + library, excluding drug_supply | P10 kg CO2e | P50 kg CO2e | P90 kg CO2e | vs published |
|---|---:|---:|---:|---:|
| CASPS | 64,601.50 | 88,758.48 | 123,510.08 | +23.38% |
| PRIMETIME | 87,891.34 | 109,685.91 | 142,685.69 | +22.75% |

Both published totals are inside these ranges. Method arithmetic remains +0.01%
and -0.16% vs the published totals. Library-factor ledger checks are different
from the engine structural checks. Industry-band rows use t_co2e; module rows
use kg_co2e. Old +5%/+7% engine claims are retired, retained only as history.

Direct and WTT factors multiply the same activity once each. The paper-factor
experiment splits the documented DESNZ 2022 combined factors into their actual
components; it no longer adds WTT on top of a combined factor. The unidentified
road total 0.19443 is counted once with no additional WTT in that experiment;
its upstream split remains unknown. Library road WTT is unchanged and nonzero.

Drug_supply is an extension with manufacture/packaging, shipping separately;
it is excluded from published-method comparison totals per draw. Limits remain:
PRIMETIME visits apply to all 1,962 instead of the 1,623 subgroup; hospital
utilities and some sample/audit activity are absent; assumed monitoring and
initiation/closeout trips differ from the academic trials. On-demand supply
projection knows scheduled visits but not future dropout, hence is optimistic.
Library recruitment rate overrides the plan-implied rate; stockouts can exceed
5%. See docs/model.md, docs/model_forecast.md and per-module science explanations.

## Checks before the combined run

- `validation/out/backend/20261017T040525Z-checks`: **563 tests, 561 pass / 2
  fail**. Contracts 106/106, engine 105/105, API 232/232, ops 34/34. Science
  35/36 (catalog omitted eight WTT entries), validation 49/50 (OQ design update
  needed If-Match). Failures preserved, fixed subsequently.
- `validation/out/backend/20261017T040933Z-recheck`: Ruff on all Python packages,
  strict mypy engine/contracts, generated contracts, licenses, API
  version/export/MCP checks, science suite and validation suite all pass.
  Further concurrent-update regression: 23/23 app-basics tests pass. The final
  clone must verify all changes together; these were dirty-workspace checks.
- Supply tests retain inventory conservation, expiry, emergency shipments,
  strategy comparisons, draw/chunk independence and seed reproducibility.
  URS-014 substantive per-module percentage tests and WTT boundary checks are
  in the backend code commit, not just this handoff.
- `THIRD_PARTY.md` regenerated byte-identical; license check: 0 items to review.
  Makefile uses frozen installs, retains validation/science evidence on clean,
  and stops only its own dev PIDs. CI adds isolated full validation and uploads
  results even on failure. Docker absent: container build/run **not verified**;
  no deployment or push performed.

## Actual cold-path observations (not replacements for final validation)

`validation/out/backend/20261017T041106Z-cold/benchmark.json`:
NCT03930732, real library, 2,000 forecast draws, seeds 200–206, every response
`X-Cache: miss`, queue 0, no discarded warmup, no profiling:
**165.0, 351.2, 296.7, 308.2, 289.0, 320.7, 308.8 ms; median 308.2 ms**.
This standalone observation **misses** the unchanged <300 ms target.
The script records requested/actual supply counts for each call. Full adapter
profile is preserved at `20261017T041127Z-profile`; it shows forecast/supply
dominate current compute. No reduced sampling or warm cache substitutes.
The earlier engine-only profile is at `20261017T042500Z-baseline` (that directory
label was manually chosen; file metadata shows actual capture around 04:00 UTC).

## Combined isolated validation — pending

FRONTEND_READY confirmed from handoffs/FRONTEND_FINAL.md with code commit e425ca2.
The complete runner will clone the committed combined tree, use isolated DBs and
8007/5180, check types/build/units plus full pytest/real Playwright, generate the
trace/report/package, download every package artifact and verify hashes/audit.
New timestamped output and exact tested commit will be added here on completion.

QA status: **awaiting QA approval**. Automated fixture signatures: **demo**,
not human review or human QA approval. Human effort and live extraction accuracy
remain unmeasured. Docker/deployment unverified. Cold performance remains an open
gap until the full combined run records its result.

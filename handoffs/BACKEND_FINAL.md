# TrialPilot backend integration

Status: **BACKEND_READY** — interfaces and backend code committed, 2026-10-17 ET.
This is interface readiness, not QA approval. Combined-commit isolated validation
has completed: 576/576 pass, cold compute median 147.8 ms; see final section for
scope, retained failures and the separate current-package browser check.

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
Science JSON SHA256 (identical in the shared checkout and tested clean clone):
`51b307a5a85795969551bf4bde514044f95cc988484f83f8c3600082668358a2`.

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

## Combined isolated validation — completed

Tested commit: **`e5c386b1fb0b6edf362bf5d37b97cc17066dfd07`**, clean `dev`
clone (`dirty: false`), containing backend f91cdb2 and frontend e425ca2.
FRONTEND_READY was confirmed before this run. Later handoff/material edits are
not represented as code that this run tested.

- Clone: `C:/Users/ol735/AppData/Local/Temp/tpv-clean-223y360g/repo` (preserved).
- Output: `validation/out/clean-clone/20261017T041438Z/`.
- Result: `summary.json`; launch log:
  `validation/out/backend/combined-e5c386b-launch.log`; runner exit **0**.
- Runtime: Windows AMD64, CPython 3.12.14, frozen Python dependencies and
  pnpm **9.15.9**, no release-age override. Temporary DBs; only 8007/5180.
- 13 preflight checks passed: five Ruff packages, strict engine/contracts mypy,
  generated contracts, parameter catalog, licenses, web types/units/build.
  Vitest: **48/48** (separate from the 576 below); production build passed.

| Full execution suite | Passed | Failed/skipped |
|---|---:|---:|
| contracts | 106 | 0 / 0 |
| engine | 105 | 0 / 0 |
| API | 233 | 0 / 0 |
| API operations | 34 | 0 / 0 |
| validation/OQ | 50 | 0 / 0 |
| science | 36 | 0 / 0 |
| real Edge + API E2E | 12 | 0 / 0 |
| **Total** | **576** | **0 / 0** |

No errors, xfails, xpasses, unrun tests or collection errors. All 12 browser
tests passed on their first attempt (no retries/flakes). Tests exercise real
offline imports, review/apply, version-pinned compute/save/compare, stale-write
409, scenario signatures and author denial, audit, weekly operations and the
alert/intervention/effect flow. Trace matrix: **32 pass**, zero fail/incomplete/
untested. URS-014's CASPS/PRIMETIME module differences and direct/WTT boundary
regressions are included and passed.

Cold URS-009: real imported NCT03930732, 2,000 requested forecast draws,
seeds 200–206, every call `X-Cache: miss`; no discarded call. Recorded
`X-Compute-Ms`: **143.8, 142.7, 148.2, 143.7, 147.8, 150.5, 151.0 ms**;
median **147.8 ms**, **PASS** against the unchanged <300 ms gate. This header
measures backend computation, not browser or network latency. The earlier
standalone median 308.2 ms and historic complete-run failures remain failures;
this run does not establish a latency guarantee under every machine/load.

### Package, downloads and audit

- Local entry: `validation/out/clean-clone/20261017T041438Z/package/index.html`.
  Machine-readable entry: `package/package_index.json`; report: `package/report.md`.
- API entry: `GET /api/validation/package`; files:
  `GET /api/validation/package/files/{relative_path}`.
  `validation/out/served_output.txt` now points at this output. An explicit
  `TP_VALIDATION_OUT` takes precedence; it must name the run directory, not
  the nested `package` directory. No live user's environment was changed.
- All **114** package manifest entries were downloaded through the real
  compliance HTTP router (ASGI TestClient) and matched SHA256, including long
  paths, PNG and ZIP. Evidence manifest: zero integrity problems.
  Detailed downloads are in `package-downloads.json`.
- Package index SHA256:
  `c8eb52ab3a58a63def1239d600c410acffb35b4e956bda73556d29aeaff39228`.
- Audit snapshot at package construction: intact, 12 entries. Final audit after
  packaging and demo labeling: intact, **14** entries, head
  `ae673caf2ea3571aad76f532d10ade3669ac56e085ac817a709a65d72d5cee56`.
  These are different capture times, not a broken chain.
- The complete E2E run occurs before package generation, so its validation-page
  test checked the honest `package_not_built` state. A separate **1/1** browser
  check then ran that unchanged test against an exact copy of this new package:
  `validation/out/backend/20261017T042216Z-package-browser/`. It verified the
  current counts, DRAFT/awaiting-QA state and real browser Markdown, PNG and ZIP
  download hashes, with **0 skips/retries/flakes**. This supplemental check is
  separate from the 576 count and does not rewrite the signed evidence manifest.
  Its temporary wrapper/config, source package and tested commit are recorded
  in `run-context.json`; browser JSON, screenshot and trace are preserved.
  Post-run inspection verified all 114 files in both source and copied package.
  Diagnostic attempts are retained: ordinary Windows paths could not open a
  long attachment, and an overly strict empty-status check noticed the run's
  untracked `var/importers/review_log.jsonl`. Extended-path verification found
  zero hash mismatches; tracked clone files remain unchanged. The generated
  review log and all diagnostic records were preserved.

QA status: **awaiting QA approval**. Automated fixture signatures: **demo**;
`human_qa_approval: false`. The summary report has no approval signatures.
Passing automated tests do not constitute human review or regulatory validation.

## Remaining gaps and operating limits

- Human QA approval, live extraction accuracy and human time savings are not
  measured/approved. Protocol bulk acceptance is a review-log metric only.
- Docker is unavailable: image build, compose runtime and deployment are
  **not verified**. No deployment or push was performed; updated CI has not run
  on a hosted runner in this session.
- The science/model limits above remain (drug_supply comparison exclusion,
  PRIMETIME subgroup coverage, omitted activity, assumptions and optimistic
  resupply projection); do not claim exact engine reproduction of the paper.
- Cold performance passed this isolated run; the recorded 308.2 ms standalone
  miss remains evidence of runtime variability, not an erased failure.
- Final evidence directories are local preserved artifacts, excluded from Git;
  they have not been uploaded or externally archived. The code/handoff commits
  and exact local evidence paths are provided for subsequent archival.
- The inherited `api/README.md` changes remain uncommitted because README files
  are outside this task's edit scope. Other tasks' files, real .env and user DBs
  were not modified. Owned verification servers were stopped by Playwright;
  ports 8007/5180 are free. Frontend 8008/5181 processes were not stopped.

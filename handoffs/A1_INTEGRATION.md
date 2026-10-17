# A1 integration check — 2026-10-16 ET

Branch `dev`. Base before this pass: `493727a` (`A1: adopt contract v4 and refresh third-party notices`).
The commit that contains this file is recorded at the bottom after `git log -1`.
Other agents' uncommitted files were not staged. No reset, clean, stash, branch switch, worktree, push, or deploy.

## Contract

v4 is unchanged in `models.py`. Generated schemas and `web/src/contracts.ts` match it.

Kept:

- `MetricRange` percentiles are `number | null`. All three numbers, or all three null. NaN becomes null. Infinity is rejected.
- `unit` includes `count`.
- `ScenarioResult.forecast` and `supply` are optional and default to null. Nested unknown percentiles stay null. A supplied `SupplyView` still requires `stockout_probability` in 0..1.
- `Signature.signer_name`, `ApprovalRequest.record_hash`, and `ApprovalRequest.created_at` stay required. `title` stays optional.
- `EventType` includes `site_activated`.

`uv run --project contracts python contracts/gen.py --check` → `OK: 20 generated files are up to date`.
`web/src/contracts.ts` is tracked. `git check-ignore -v -- web/src/contracts.ts` exits 1. It is not gitignored.

### A4 UUIDv5 — recorded, no schema change

`id` stays `str`. UUID4, UUIDv5, and the existing plain fixture ids all validate. There is no version-nibble check.

- Importer namespace `6f1c3c3e-8a43-4d0e-9b55-1f2a5e0c7a11` (`api/trialpilot_api/importers/ctgov.py`):
  - `TrialDesign.id = uuid5(namespace, "ctgov:<NCT>")`
  - `Site.id = uuid5(namespace, "ctgov:<NCT>:site:<key>#<n>")`
- Extraction namespace `0b8f5d0e-5a3c-4c55-9f7e-2c1d7a9e4b21` (`protocol_extract.py`). These ids are not design ids.
  - live: `uuid5(namespace, "<pdf_sha256>:<method>:<model>")`
  - BOREAS cache: `uuid5(namespace, "<pdf_sha256>:transcription:<model>")`
- In-app operations ids (`event_uuid`) are deterministic bytes formatted as UUID version 4.

### `Visit.patient_share` — deferred

Not added. PRIMETIME's five mammogram visits are still applied to all 1,962 patients. Accepting the field would require the engine, the science designs, and every visit builder to change together. That is a known limitation, not a silent zero.

## Build entry points

| Target | Command |
|---|---|
| dev API | `uv run --project api uvicorn --factory trialpilot_api.main:create_app --host 127.0.0.1 --port $(API_PORT)` |
| dev web | `corepack pnpm@9.15.9 --dir web dev --port $(WEB_PORT) --strictPort` with `WEB_PORT` and `API_TARGET` |
| seed | `uv run --project contracts python -m trialpilot_contracts data/params`, then `uv run --project api python -m trialpilot_api.seed` |
| science | `uv run --project science python -m science.reproduce` |
| validate | `cd validation && uv run tpv package` |
| gen check | `uv run --project contracts python contracts/gen.py --check` |
| licences | `uv run --project contracts python .github/scripts/third_party.py` |

`web/package.json` `packageManager` is `pnpm@9.15.9`. `web/pnpm-lock.yaml` is lockfileVersion 9.0. `api/Dockerfile` runs `corepack prepare pnpm@9.15.9`. CI `pnpm/action-setup` is pinned to `9.15.9`. Bare `pnpm` is not on PATH. `corepack pnpm` from the repo root reported `12.14.0`; `corepack pnpm@9.15.9` and `corepack pnpm` inside `web/` reported `9.15.9`.

`make -n` was run after prepending `C:\Program Files\Git\bin` to PATH. `bash` is not on the default PATH of this PowerShell. The dry run prints the commands above. Default ports in the Makefile remain 8000 and 5173.

Docker image command, from `api/Dockerfile`, is `python -m trialpilot_api.seed` then `uvicorn trialpilot_api.main:app`. Compose does not override it. `main:app` is the lazy factory alias of `create_app`.

Licence rows that said "to confirm by A10" now use `docs/sources.md` §11: DESNZ and DfT National Travel Survey are Open Government Licence v3.0; BMJ Open 2024, Ember, and Australian NGA Factors 2026 are CC BY 4.0. `third_party.py` wrote `THIRD_PARTY.md` with 0 review findings. `--check` exited 0.

## Commands and results

Working directory: repo root, unless noted. PowerShell.

```text
uv run --project contracts python contracts/gen.py --check
  OK: 20 generated files are up to date

uv run --project contracts python -B -m pytest -p no:cacheprovider contracts/tests
  106 passed

uv run --project contracts ruff check --no-cache contracts
  All checks passed

cd contracts; uv run mypy --strict trialpilot_contracts gen.py
  Success: no issues found in 6 source files

contracts\.venv\Scripts\python.exe -m trialpilot_contracts data/params
  OK: 203 parameters (58 assumptions), parameter_set_version=1249d0f0eed8

science\.venv\Scripts\python.exe -m science.reproduce --help
  exit 0. Did not write science/out/results.json.

corepack pnpm@9.15.9 --dir web typecheck
  exit 2. tsc errors are listed under cross-module defects.

docker --version
  docker is not recognized. Docker was not run.
```

The first `uv run --project contracts` printed: the existing `contracts/.venv` pointed at a missing interpreter, so uv removed it and created a new one with CPython 3.15.0. `contracts/uv.lock` was not modified. `engine/.venv` and `validation/.venv` still point at missing `cpython-3.12.15` and were not recreated. `api/.venv` and `science/.venv` already ran on CPython 3.15.0.

Running `mypy --strict` from the repo root, instead of from `contracts/`, reports `payload: dict` in `models.py`. That invocation does not load `contracts/pyproject.toml`. The Makefile and CI run mypy inside the package directory, which is the run that passed.

### Local processes (temp database, then stopped)

```text
TP_DATA_DIR / TP_DB_PATH = C:\Users\ol735\AppData\Local\Temp\tp-a1-6c70fcdccf3246c2807f34dbb78c8fc8
DEMO_OFFLINE=1
api\.venv\Scripts\python.exe -m uvicorn --factory trialpilot_api.main:create_app --host 127.0.0.1 --port 8001
corepack pnpm@9.15.9 --dir web exec vite --host 127.0.0.1 --port 5174 --strictPort
API_TARGET=http://127.0.0.1:8001
```

- `GET http://127.0.0.1:8001/api/health` → 200, `offline: true`, params 203, engine ready, forecast and simulate_supply available, importers/ops/compliance mounted, `web.status` `not_built`, `science_results: true`.
- `GET http://127.0.0.1:8001/api/import/ctgov` → 200. First cached study is NCT03930732, 275 sites, protocol extraction cached.
- `GET http://127.0.0.1:5174/` → 200 (842 bytes).
- `GET http://127.0.0.1:5174/api/health` → 200, same health body through the Vite proxy.

Stopped API pid 46044 and the Vite processes started for port 5174. Afterwards nothing was listening on 8001 or 5174. An earlier attempt failed before any process started (`RedirectStandardOutput` and `RedirectStandardError` were the same file). No server was left from that attempt.

`make seed`, `make science`, and `make validate` were not executed. Seed would write a database. Science would overwrite `science/out/results.json`. Validate would write `validation/out/`.

## Docker — not verified

`docker` is not installed on this machine. No image was built. There is no deployment URL.

Reproducible command, from the repo root, on a machine with Docker:

```text
docker compose up --build
```

The compose file binds `127.0.0.1:8000` only. That address is the local port, not a host that was deployed.

## Cross-module defects (not edited)

- `corepack pnpm@9.15.9 --dir web typecheck` exits 2. `web/src/app/contracts.ts` now re-exports `../contracts` (the generated v4 file). `tsc` then reports null percentiles used as numbers (`MetricCard`, `ModuleChart`, `ComparePage`, mock engine), mock `ApprovalRequest` missing `record_hash` / `created_at` / `title`, mock `Signature` missing `signer_name`, `normalize.ts` forecast/supply details that are not `ForecastView` / `SupplyView`, and `DesignRecord` passed where `TrialDesign` is required (`ImportPage`, `ScenarioPage`). Files: `web/src/app/api/mock/engine.ts`, `web/src/app/api/mock/index.ts`, `web/src/app/api/normalize.ts`, `web/src/features/scenario/`. A1 did not edit them.
- `web/src/app/_contracts_local.ts` is an older generated copy: `p10: number`, no `count`, no `site_activated`, no `ForecastView`, no `signer_name`. The shim no longer exports it. It is still in the tree.
- A2's handoff (23:10 ET) says engine mypy still has 4 strict errors in `forecast.py`, and that science tests `test_needed_md_matches_the_engine_parameter_catalog` and `test_checked_in_results_are_current` fail after well-to-tank. This pass did not re-run those suites and did not rewrite `science/out/results.json`.
- A5/A7 historical URS-009 evidence stays: clean-clone full run at `38e2073`, median 664.1 ms, failed (`664.1 < 300`); the seven `X-Compute-Ms` values were 532.3, 683.7, 702.4, 581.1, 710.0, 664.1, 643.8. The standalone retry on that commit passed and does not replace the failure. Slider hot path P50 54 ms is a different path. This pass did not re-measure compute latency.
- `engine/.venv` and `validation/.venv` point at missing CPython 3.12.15, so `make test` and `make lint` were not run for those packages.
- API health reports `web.status: not_built`. The dev UI is Vite. The Docker image is what would serve `web/dist`, and that image was not built.
- A1 incident at 21:04 ET (untracked importer files deleted) is unchanged in `handoffs/A1.md`. A4 later re-created the importer package.

## Can this be demonstrated?

A local offline demo can be started. The temp-database process on 8001 answered `/api/health` and listed the cached BOREAS import, and Vite on 5174 proxied that health check. Repeat it with the commands above, or with `make dev API_PORT=8001 WEB_PORT=5174` once `bash` is on PATH.

It is not a finished submission. Web typecheck fails, Docker was not run, there is no deployment URL, the full `make test` was not run, and the recorded URS-009 full-run failure is still a failure. `Visit.patient_share` is still absent, so the PRIMETIME visit-count gap remains.

## Commit

`22f052f7dc4cffbf5f32c8524cd68f3fe0a506ee` on `dev`: `A1: record id rules and point the build at the real entries`.

That commit contains the contract note, the id-convention test, the Makefile, CI, compose comment, licence generator, `THIRD_PARTY.md`, and these handoffs. This paragraph was added in the follow-up commit so the hash above is the integration commit, not this sentence.

## Backend takeover integration — 2026-10-17 04:23 UTC

The earlier observations above are retained as history. Current interface and
backend code is `f91cdb213a76979d08e9decc98e646f67bc05b30`; frontend code is
`e425ca25541e69b40328337aba0ef5145fcd8d91`. BACKEND_READY and FRONTEND_READY
preceded the complete clean-clone run on
`e5c386b1fb0b6edf362bf5d37b97cc17066dfd07`.

`validation/out/clean-clone/20261017T041438Z/summary.json`: **576 passed, 0
failed/skipped**, including 12 real Edge/API flows with no retries. All 32
requirements pass the trace matrix, including substantive URS-014 tests.
Thirteen preflight checks passed, including strict engine/contracts types,
generated v5 contracts, licenses, frontend types/build and 48 frontend unit tests.
Cold URS-009 median **147.8 ms**, seven distinct cache misses, 2,000 forecast
draws; historical 664.1/642 ms failures and the 308.2 ms standalone miss remain.

All 114 package files passed HTTP download/hash verification; final audit chain
is intact (14 entries). Package `package/index.html` and `package_index.json`
remain **awaiting QA approval**, with explicitly **demo** fixture signatures.
The additional `validation/out/backend/20261017T042216Z-package-browser/` run
verified this newly generated package in the real browser (1/1, no retries),
including Markdown/PNG/ZIP hashes. Original signed evidence was not rewritten.

Makefile frozen installs and isolated validation target, preservation of science/
validation evidence on clean, CI integration/artifact retention and license
checks are current. Docker remains unavailable and unverified; no deployment,
push or hosted-CI execution is claimed. Temporary verification servers stopped;
8007/5180 are free. See `handoffs/BACKEND_FINAL.md` for API semantics, science
boundaries, exact hashes, full samples and remaining human QA/model limitations.

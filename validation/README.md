# `tpv` — TrialPilot validation toolkit

Generates TrialPilot's own GxP validation package (dogfooding) with humans in charge: the test
protocol must be approved before it runs, evidence is hashed and signed by the executor, and the
summary report waits for QA's electronic signature. AI may draft prose (stamped
"DRAFT — requires human review") but never results, counts, evidence or signatures.

Inputs (all in this folder): `company_sop.md` (fictional SOP), `requirements.yaml` (URS, 32 items),
`ROLES.md` (permission matrix), `component_map.yaml` (change control), `tpv_config.yaml` (suites),
`PART11.md` (21 CFR Part 11 mapping), `defects/` (planted defects), `effort/` (manual baseline).

## Run (from the repo root)

```bash
uv run --project validation tpv plan
uv run --project validation tpv risk
uv run --project validation tpv protocol --submit --as alex.author      # collects tests per requirement
uv run --project validation tpv sign <approval-id> --as riley.reviewer --meaning reviewed   # PIN prompt
uv run --project validation tpv sign <approval-id> --as sam.qa --meaning approved
uv run --project validation tpv execute --as alex.author                 # refuses if not approved
uv run --project validation tpv trace
uv run --project validation tpv report --submit --as alex.author         # awaiting QA approval
uv run --project validation tpv package                                  # validation/out/package/index.html
```

Signing can also be done in the app (`/approvals`). Scripted runs may pass the PIN via `TPV_PIN`
(the signer's own PIN — tpv never signs for anyone). `make validate` runs `tpv package`.

Other commands: `tpv status` · `tpv impact --base <ref> --head <ref> [--submit --as U]` ·
`tpv controls` (compliance control probes) · `tpv defects-run` (planted defects, throwaway worktree)
· `tpv verify-evidence` · `tpv effort start|stop|show`.

## Tagging tests with requirements

- pytest: `@pytest.mark.req("URS-015")` (several ids allowed). The marker is registered by the tpv
  pytest plugin; outside tpv runs an unregistered-marker warning is harmless.
- Playwright: a comment directly above the test, `// @req URS-019`, or
  `test.info().annotations.push({ type: 'req', description: 'URS-019' })`.

`tpv trace` flags requirements with no test, tests with no requirement and unknown ids.

## Where things go

`validation/out/` (git-ignored): `collect/`, `protocol/OQ-TP-001-<sha8>.md`, `evidence/RUN-…/`
(raw results, JUnit XML, logs, `evidence_manifest.json`, `executed_signature.json`), `trace/`,
`report/`, `change/`, `defects/`, `package/` (served by `GET /api/validation/package`).

The compliance database is the API's SQLite file (`TP_DB_PATH`, default `var/trialpilot.sqlite`), so
approvals given in the app unlock `tpv execute` and vice versa.

## Check a clean local clone

```bash
uv run --project validation python validation/scripts/check_clean_clone.py --e2e
```

This clones committed code into a temporary directory, installs locked dependencies, checks the
approval gate, self-approval and signing order, runs the real suites (plus Playwright with `--e2e`),
and builds the package. It verifies evidence and package hashes. Results are in
`validation/out/clean-clone/<UTC timestamp>/summary.json` and `package/index.html`; the clone is
preserved for inspection. Exit 1 means tests or a suite failed; the package still records the
actual results. Missing requirement coverage is reported in the trace and summary report.

Signatures in this isolated automated check use published **fictional demo identities** as test
fixtures. They are not human approvals or regulatory validation evidence. The generated report
remains **awaiting QA approval**. The shared database and checkout are not used for execution.

`validation/defects/LAST_RUN.json` preserves a historical measured defects experiment. If no local
defects run exists, the package includes that archive, labelled with the commit it actually tested.

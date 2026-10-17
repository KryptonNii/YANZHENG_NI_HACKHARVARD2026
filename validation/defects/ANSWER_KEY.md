# Planted defects — answer key

Six defects, one per type on the Regeneron "Software Speedrun" sheet. Each is a patch file in this
folder, generated from the committed code by `make_patches.py` (one exact text replacement, spec in
`defects.yaml`). **Patches are never applied in the shared folder.** `tpv defects-run` applies them
one at a time in a throwaway `git worktree` outside the repository, runs an unsigned experiment
(all test suites + trace check + compliance control probes), compares it with a clean baseline,
and reports what — if anything — flagged the defect.

| ID | Type | Patch | Target | What the defect does | Requirement | Expected to be caught by |
|---|---|---|---|---|---|---|
| D1 | calculation bug | `D1_car_factor_unit_error.patch` | `data/params/emission_factors.yaml` | Car factor entered in g instead of kg (×1000), unit still `kg_co2e/km` | URS-003 | unit test: `validation/tests/oq/test_oq_parameters.py::test_emission_factors_are_plausible_for_their_unit` (and any engine/science test that uses the real library) |
| D2 | missing audit entry | `D2_design_save_not_audited.patch` | `api/trialpilot_api/routes_designs.py` | Design create/update bypasses the audited write | URS-015 | unit test: `validation/tests/oq/test_oq_api.py::test_design_create_and_update_are_audited`, A5's audit tests |
| D3 | role can self-approve | `D3_qa_can_self_approve.patch` | `api/trialpilot_api/compliance/workflow.py` | Segregation-of-duties check exempts the QA role | URS-021 | unit test: `api/tests/compliance/test_compliance_workflow.py::test_no_role_is_exempt_from_segregation_of_duties[sam.qa]`; workflow check: probe C1b |
| D4 | export drops rows | `D4_audit_export_drops_last_row.patch` | `api/trialpilot_api/compliance/audit.py` | Audit CSV export skips the newest entry | URS-028 | unit tests: `test_export_contains_every_entry`, OQ `test_audit_export_has_every_row`; workflow check: probe C6 |
| D5 | wrong configuration value | `D5_offline_default_on.patch` | `api/trialpilot_api/settings.py` | `DEMO_OFFLINE` defaults to on in code; `.env.example` documents 0 | URS-029 | unit test: `validation/tests/oq/test_oq_config.py::test_documented_and_coded_offline_default_is_off` |
| D6 | requirement with no test | `D6_requirement_without_test.patch` | `validation/requirements.yaml` | Adds URS-033 (audit date-range filter) with no test | URS-033 | trace check: "requirement with no test" |

## Honest caveats

- **Not a blind test.** The same agent (A7) planted the defects and wrote the OQ tests and probes;
  the tests were written from the requirements, but with knowledge of the defect types. The result
  shows the toolkit's mechanics work (patch → run → compare → stage attribution); it is not an
  independent estimate of real-world detection rates.
- Only **committed** code is tested (the worktree is created from `HEAD`).
- A patch that no longer applies (target code changed) is reported as "not applied", never as
  detected. Regenerate with `uv run --project validation python validation/defects/make_patches.py`.
- The detection count in the package and the HANDOFF is the number measured by the latest
  `tpv defects-run`, copied from `validation/out/defects/results.json`.

## Completed experiment (archived)

`LAST_RUN.json` preserves the completed experiment at commit
`d61664572163b674f1a4ede2903b96a204c40b57`, from 2026-10-16 21:38:28 to 21:53:03 EDT.
All six patches applied and **6 of 6 were detected**: D1/D2/D5 by tests, D3/D4 by tests plus
workflow checks, D6 by traceability. The unmodified baseline had 269 tests (266 passed,
3 failed), 10 of 10 control probes holding, and 12 requirements without a tagged test.
The three baseline failures concerned unknown metric handling in engine/API tests; only
new failures or flags relative to that baseline counted as defect detections.

Packages without a local run include this archive with its tested commit and an explicit
historical-results label. It does not claim the current checkout has been tested again.

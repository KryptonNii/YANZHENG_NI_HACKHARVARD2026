# Planted-defect detection run

Commit `d616645721` · 2026-10-17T01:38:28Z → 2026-10-17T01:53:03Z · **detected 6 of 6** planted defects (6 applied).

> Unsigned experiment, not GxP evidence. Only committed code (HEAD) is tested.

Archived experiment from `validation/defects/LAST_RUN.json`. The commit above identifies the code tested; these are not measurements of the current checkout. Run `tpv defects-run` to measure the current commit.

Baseline (no defect): 269 tests — passed 266, failed 3, error 0; control probes holding 10.

| Defect | Type | Requirement | Applied | Detected | Stage(s) | What flagged it |
|---|---|---|---|---|---|---|
| D1 | calculation bug | URS-003 | yes | **yes** | unit test | `validation/tests/oq/test_oq_parameters.py::test_emission_factors_are_plausible_for_their_unit` |
| D2 | missing audit entry | URS-015 | yes | **yes** | unit test | `api/tests/test_app_basics.py::test_design_create_get_list_and_versions`<br>`api/tests/test_app_basics.py::test_fixture_designs_are_seeded`<br>`api/tests/test_approval_export_sse.py::test_stub_compliance_keeps_mutations_audited` |
| D3 | role can self-approve | URS-021 | yes | **yes** | unit test, workflow check | `api/tests/compliance/test_compliance_workflow.py::test_no_role_is_exempt_from_segregation_of_duties[sam.qa]`<br>`validation/tests/test_tpv_units.py::test_all_control_probes_hold_on_this_code`<br>`C1b no role (not even QA) approves its own record: no error raised — control did not hold` |
| D4 | export drops rows | URS-028 | yes | **yes** | unit test, workflow check | `api/tests/compliance/test_compliance_api.py::test_audit_list_and_export`<br>`api/tests/compliance/test_compliance_audit.py::test_export_contains_every_entry`<br>`validation/tests/oq/test_oq_api.py::test_audit_export_has_every_row`<br>`C6 audit export contains every entry: 7 exported rows vs 8 entries` |
| D5 | wrong configuration value | URS-029 | yes | **yes** | unit test | `validation/tests/oq/test_oq_config.py::test_documented_and_coded_offline_default_is_off` |
| D6 | requirement with no test | URS-033 | yes | **yes** | trace check | `no test: URS-033` |

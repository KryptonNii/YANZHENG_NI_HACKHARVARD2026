# Constrained NextLever backend handoff

Completed 2026-10-17 in the shared, uncommitted working tree. No commit, push, registry download,
design write or scenario write was performed by this task.

## Scope

Changed only `api/trialpilot_api/advice/{candidates,ranking,routes,sampling,schemas}.py`,
`api/tests/test_advice.py`, and this handoff. Shared contracts, calculation formulas, engine
defaults, importer, benchmark, router registration and frontend were not edited.

## HTTP contract

`GET /api/scenarios/advice` still requires `design_id` and `design_version`. Optional
`current_levers` is a JSON object encoded as a query parameter. It is validated with the existing
Levers input model (unknown keys rejected) and existing design-specific lever validation.
Malformed input returns HTTP 422 using `{error,message,details}`. Omission means default Levers.

Old response fields are retained. Additions:

- `current_levers`: the complete validated selection used as the comparison baseline.
- `seed: 7`, `draws: 200`: the single ranking stage used for the baseline, every candidate and
  the stress scenario. `scenario_draws`: `settings.default_draws` (2000 unless
  `TP_DEFAULT_DRAWS` overrides it), the formal scenario's own draw count. There is no
  `screening_draws` field. `sampling_note` and `delta_method` explain both.
- `policy`: `max_duration_increase_months: 0.0`, `max_stockout_probability` from
  `supply.stockout_warning_threshold.value_mid` (0.05 fallback), `max_recommendations: 3`, and
  an explicit statement that these are reviewable model assumptions, not a clinical guarantee.
- `rejected`: `{id,label,kind,levers,reason,delta,procedure}` records; `delta` may be null.
- Each recommendation carries `kind` (`lever` or `procedure_removal`), `procedure`
  (`{code,label,endpoint_roles:["not_linked"]}` for removals, otherwise null) and
  `stockout_probability: number | null` (null for none/device designs).
- `stress_scenarios`: at most one `{id:"slower_enrollment",label,tag:"assumption",levers,delta,
  stockout_probability,reason}`; `delta` is null when either forecast is unavailable.
- `blocked`: `{code,endpoint_roles,reason}` for every code that may not be recommended for removal.

Recommendation and rejection `levers` contain only changed fields relative to `current_levers`.
For arrays the field value is the final merged array, preserving existing entries; the frontend
can apply ordinary object spread. Example: current home visits `[1]` plus new visit 3 yields
`{"home_visit_numbers":[1,3]}`. Scalar values are final values, not arithmetic increments.

Global refusals use `reviewed_schedule_required` or `forecast_unavailable` as their id,
`levers: {}` and `delta: null`. Their labels and reasons describe the missing evidence.

## Behavior

1. Work from the explicitly pinned stored design and one parameter snapshot throughout the
   request. Compare every candidate to the user's current selection using `engine.compare`'s
   paired per-draw deltas. Obtain candidate supply risk with `engine.compute`.
2. Preserve existing selections, including procedure removals, and disclose that retaining a
   removal is not approval of its clinical appropriateness. Remove no-ops, avoid reverting
   remote/local shares above 50%, merge home visits without telehealth collisions, and choose
   exclusions only among remaining sites. Added countries are assumed sites, not registry sites.
3. Collect endpoint roles per procedure code across all visits. Any code with a
   `supports_primary`, `supports_secondary` or `unknown` role, including one that mixes these
   with `not_linked`, goes to `blocked` and is never recommended for removal. Each code whose
   roles are only `not_linked` becomes its own single removal candidate
   (`remove_procedure:<code>`, patch `{"removed_procedures": [...current, code]}`). Its reason
   states that this is not clinical approval and that manual protocol review is still required
   for safety, eligibility and treatment needs.
4. Refuse all action recommendations when visits are empty, every procedure list is empty, or
   `missing_fields` includes `visits`. A baseline estimate may still be shown.
5. Require a known database-lock forecast on both baseline and candidate. A fallback planned
   duration with a zero delta does not pass this gate, including for none/device studies.
6. Compute the baseline and each candidate once with seed 7 and 200 requested draws. Reject
   unknown or nonnegative cost P50 deltas, unknown or positive duration P50 deltas, and missing
   or excessive drug stockout risk. Drug supply is not applicable to none/device studies.
   Equality at the risk threshold is allowed.
7. Rank feasible choices by paired candidate-minus-current cost P50, then staff-hours P50
   (unknown sorts last), then id. Return the top three; the remaining feasible choices go to
   `rejected` with the "ranked below the top 3" reason. If none qualifies, return an empty list
   with reasons rather than filling three slots. There is no second, larger-draw recheck.
8. Slower enrollment (0.7x the current multiplier, floored at 0.5) is computed with the same
   200 draws and reported only in `stress_scenarios` with tag `assumption`. It is never a
   candidate or recommendation, and its reason says any cost change is not a saving. When the
   current multiplier is already at the floor, no stress scenario is returned and a warning
   explains why.

The sampling note says advice uses one 200-draw ranking stage, that the formal scenario uses its
own draw count (`scenario_draws`), and that the supply engine has its own draw cap; engine
sampling warnings are preserved. Formal scenario defaults remain unchanged at 2000.

## Validation

From the `api` directory:

```
.venv/Scripts/python.exe -B -m pytest tests/test_advice.py -q -p no:cacheprovider
.venv/Scripts/python.exe -B -m ruff check trialpilot_api/advice tests/test_advice.py
```

51 advice tests passed; Ruff passed (re-run 2026-10-17 after the single-stage refactor). The
real-engine regression independently recomputes the 200-draw paired comparisons plus supply for
every candidate and the stress scenario, requires a nonempty accepted set, and checks returned
ordering, the ranked-below-top-3 rejections, every metric range, stockout probability, blocked
codes and parameter version. Tests also cover conservative refusal, current-selection
preservation, merged patches, no-ops, single-code `not_linked` removal candidates, mixed-role
blocking, retained removals of blocked codes, the assumption-only stress scenario and its floor,
assumed countries, all-more-expensive scenarios, absent/excess supply risk, none/device
behavior, unknown values, unavailable baseline/candidate forecasts, incomplete schedules,
invalid query inputs, design-version pinning, `scenario_draws` following the server default and
absence of saved scenarios.

These are backend checks on the working tree; they do not assert full-project validation,
browser acceptance, independent model calibration, clinical approval or regulatory compliance.
Frontend integration and broader validation are coordinated by the parent task.

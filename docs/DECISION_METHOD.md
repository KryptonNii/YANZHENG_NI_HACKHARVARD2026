# How scenario advice is screened

TrialPilot compares incremental changes to the scenario currently selected on screen.
The saved design version, current levers and parameter-library snapshot identify the
comparison. Previewing a suggestion changes the local scenario controls and invokes
the existing calculation flow; it does not save a design, create a scenario or approve
an amendment.

## Evidence and candidate boundaries

A visit schedule must contain procedures and must no longer be marked missing or
assumed before the service recommends changes. A cached extraction accepted in an
automated demonstration is still a demonstration review, not clinical approval.

Endpoint roles are read per procedure code across every visit. A code with any
`supports_primary`, `supports_secondary` or `unknown` occurrence is listed in `blocked`
with a review explanation and is never recommended for removal, including when some of
its occurrences are `not_linked`. A code whose every occurrence is `not_linked` becomes
its own single-procedure removal candidate (`remove_procedure:<code>`) and is screened
like any other lever. A `not_linked` annotation only describes endpoint linkage: it
does not establish that an assessment is unnecessary for safety, eligibility or
treatment decisions. Passing the screen is therefore not clinical approval, and any
removal still requires manual protocol review. Existing user-selected removals remain
part of the comparison baseline; the advice service does not approve or silently
reverse them.

The other candidates use existing monitoring, laboratory, home-visit, supply, site
and assumed-country levers. Choices already selected are omitted. Other current
choices are retained, including existing list selections. Added countries are assumed
sites, not registry sites (see below).

Slower enrollment is never a candidate. The response reports it separately in
`stress_scenarios`, tagged `assumption`: the current selection with enrollment at 0.7
times the current rate, floored at the model minimum of 0.5. It shows how the current
plan behaves if recruitment is slower than expected. It is not ranked, recommended or
previewed, and any cost change it shows is not a saving. The enrollment-rate control
remains available for manual stress tests.

## Model screening policy

| Criterion | Requirement |
| --- | --- |
| Cost | The paired candidate-minus-current P50 must be known and negative. |
| Duration | Current and candidate forecasts must be available; the paired duration P50 must be known and must not increase. A fallback to the registered planned duration is insufficient evidence. |
| Drug supply | When applicable, the candidate's modeled stockout probability must be known and no greater than `supply.stockout_warning_threshold.value_mid`; the disclosed fallback is 0.05. |
| No passing candidates | Return no recommendations and explain the rejected candidates. |

These are disclosed screening assumptions. The duration rule is about P50, not a
promise that no simulated trajectory can finish later. The stockout threshold is an
existing model-policy parameter, not an independently established clinical acceptance
criterion. Supply is not applicable to designs whose drug type is `none` or `device`.

Advice runs one ranking stage. The current selection (the baseline), every candidate
and the stress scenario are computed with seed 7 and 200 requested engine draws, and
each comparison uses the existing engine's paired, common-random-number per-draw
differences (candidate minus current). The service never subtracts marginal
P10/P50/P90 values to invent a difference interval. The formal scenario computation
uses its own draw count (`scenario_draws`, the server default of 2,000), so its figures
can differ from the advice estimates; advice does not change it. Supply retains its
existing sampling budget and reports its actual draw counts through producer warnings.

Passing candidates are ranked by cost-difference P50, then site-staff-hours-difference
P50 (unknown last), then candidate id. The top three are returned; the remaining
passing candidates appear in `rejected` with the reason that they met the model
constraints but ranked below the top three. The ranking comes from one fixed 200-draw
sample over a small set of single-step candidates; it is not an exhaustive search or a
claim of global optimality. Parameter sensitivity and independent outcome calibration
remain future evaluation work.

## Assumed countries

Each added country represents one assumed site. Its expected-enrollment weight is
the median of positive, finite expected-enrollment values among existing active sites;
if unavailable, the model uses `assume.design.patients_per_site`. A patient count is
never converted into a number of sites. The site is labeled `assumed` and does not
represent a real country's recruitment capability or startup conditions.

## Verification boundaries

Regression checks cover current-scenario preservation, stale-response isolation,
explicit rejection, missing inputs, supply risk, duration tradeoffs, the top-three cap,
single-code `not_linked` removal candidates, blocked mixed-role codes, the
assumption-only stress scenario and the assumed-site construction. A real-API browser flow exercises protocol review,
scenario changes and preview behavior using a temporary database.

Software regression results support implementation behavior. They do not establish
real-world cost accuracy, forecast interval coverage, clinical appropriateness or
human QA approval. Execution results and artifact paths are recorded separately in
`handoffs/DECISION_DEPTH.md` after verification.

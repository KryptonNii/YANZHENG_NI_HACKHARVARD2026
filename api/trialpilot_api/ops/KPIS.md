# Operations command-center KPIs

The health endpoint returns 14 KPIs. They cover the operational signals that can change trial cost,
site workload, patient burden, supply continuity, or the database-lock date. The dashboard shows study,
country, and site rollups where the feed supports that level. Forecast comparisons use the current plan
and preserve uncertainty bands. In the demo, observed activity is a simulated feed; missing observations
remain unknown.

| KPI | Calculation and scope | Why it matters |
| --- | --- | --- |
| Enrollment vs plan band | Cumulative enrolled patients compared with the plan's P10/P50/P90 forecast, at study, country, and site level. Each site row also includes `weekly_enrollment` (below). | Early enrollment gaps threaten the completion date and can make the planned site mix uneconomic. |
| Enrollment rate (trailing 8 weeks) | Observed enrollment per month over the most recent eight complete weeks, rolled up by study, country, or site. | A recent rate shows whether a site is recovering or falling behind, while cumulative enrollment can hide a new slowdown. |
| Sites active / stalled / not activated | Counts sites with recent enrollment, sites that are open but have no recent enrollment, and sites whose planned activation has not occurred. | Separates a recruitment problem from a site that has not yet started or is no longer contributing. |
| Missed visits (trailing 8 weeks) | Missed scheduled follow-up visits divided by scheduled follow-up visits in the last eight complete weeks. | Missed visits increase patient burden, reduce usable data, and can delay endpoint completion. |
| Withdrawals | Cumulative patient withdrawals, rolled up by study, country, and site. | Withdrawals reduce the evaluable cohort and help teams identify sites or regions with retention pressure. |
| Open queries and median age | Count queries opened but not closed by the current clock, plus the median age in days of those open queries; study, country, and site. | A growing or aging query queue signals data-cleaning effort and database-lock risk. |
| Queries per 100 visits (trailing 8 weeks) | Queries opened per 100 completed visits over the last eight complete weeks, by study and site. | Normalizing by visits distinguishes poor data quality from a site that simply has more activity. |
| Drug on hand vs projected need | Site inventory on hand compared with projected need bands over the supply horizon; includes expiry and shortfall signals. | Excess stock risks expiry and waste; insufficient stock risks missed dosing and emergency shipments. |
| Spend to date vs plan | Finance-feed invoices accumulated to date compared with the plan's cost range, at study level. | Flags budget variance early enough to investigate its operational driver. |
| Carbon to date vs plan | Emissions estimated from observed travel and shipments compared with the plan's range, at study level. | Shows the environmental effect of operational choices such as air shipments and unbatched monitoring trips. |
| Site staff hours to date vs plan | Procedure and query-resolution hours estimated from observed activity compared with planned hours, at study and site level. | Measures coordinator workload and exposes avoidable work from missed visits or data queries. |
| Patient burden hours to date vs plan | Estimated patient time in procedures and travel compared with the planned range, at study level. | Keeps patient time visible alongside sponsor cost and site workload when teams consider interventions. |
| Milestone forecasts vs targets | Current milestone forecast dates and uncertainty compared with target dates, at study level. | Gives the team a forward-looking view of vendor and database-lock risk. |
| Open alerts by severity | Count of open or acknowledged alerts grouped by severity, with study, country, and site rollups. | Shows the team's unresolved operational risk and helps prioritize follow-up. |

The API's `kpi_definitions` field is the machine-readable source for names, units, and supported levels.
The calculations and thresholds are implemented in `health.py` and `detect.py`; the KPI list is kept here
to explain why each measure belongs on the command-center screen.

## Weekly enrollment

Each object in `health.sites` and `health.countries` has `weekly_enrollment`. It is the time series
behind the enrollment marker: one point per complete week already on the simulated clock. The open
week is omitted, the same rule as the other weekly series. No extra enrollment draws are made for
this field. A country series is the sum of its sites' feed counts and plan bands for those same
weeks. It is not a new forecast and not a resampled curve.

| Field | Meaning |
| --- | --- |
| `unit` | `patients`. |
| `actual_per_week` | Patients enrolled during that complete week. Week 0 is days `[0, 7)`. Each value is a count of `patient_enrolled` events already in the feed with `t < complete_weeks * 7`. A country value is the sum of its sites. A complete week with no such events is `0`, which is an observed count. The point is not omitted and not null. |
| `actual_cumulative` | Running sum of `actual_per_week`. Index `k` is cumulative enrollment at the end of that week, day `7 * (k + 1)`. |
| `plan` | `{p10, p50, p90}` cumulative plan band at the same week end. For a site this is the existing `site_band` at index `k + 1`. For a country it is the sum of those site bands, which is the same sum as `planned_to_date`. These are the operational plan quantiles already on the health payload, not a new forecast. |

`actual_per_week`, `actual_cumulative`, and `plan` have the same length. When at least one complete week
has elapsed, the last `plan` point is that row's `planned_to_date` band (without the `unit` key).
`enrolled` counts every `patient_enrolled` event with `t < clock_day`, so it can be higher than the
last `actual_cumulative` by the enrollments in the current incomplete week (`t >= complete_weeks * 7`).
That partial week is not a null point and is not appended.

A backup site (`expected_enrollment = 0`, not in the enrollment plan) keeps the zero plan band at
every week. Its actual counts still come from its own `patient_enrolled` events after it opens, and
those counts are included in its country sum. The zero plan is a real plan of no enrollment, not a
missing value. Before the first complete week, including clock day 0, all three lists are empty.
Other unknown health fields (`drug_need_kits` before day 42, median query age with no open queries,
first patient in with no enrollment) stay null. Weekly enrollment does not use nulls inside the lists.

## Predicted outcome of each action, and the follow-up

An alert lists recommended actions. For site-level `enrollment_lag` and `drug_overstock` alerts, the alert detail
(`GET /{trial}/alerts/{id}`, field `options`) ranks the quantified actions by predicted net value: cost avoided
minus the action's own cost, P50. Four actions are quantified: `enrollment_retraining`, `activate_backup`,
`supply_on_demand` and `transfer_excess`. Every other recommended action is listed as "not quantified" with a reason.
The "do nothing" baseline equals the alert's own impact estimate (same seeds and formulas).

The prediction uses only the observed feed and the labelled assumptions `ops.effect.*` and `ops.cost.action.*` in
`ops_params.yaml`. It never reads the simulator or its withheld ground truth, and a test enforces that. Predicted
days and dollars are model outputs, not observations.

Planning an action saves the prediction as it stood then (`ops.intervention.expectation` in the audit trail). It is
never recomputed. `GET /{trial}/effects/{id}` then carries `expectation` and `reconciliation`. The follow-up compares
the observed difference-in-differences 95% interval with the predicted range for the weeks actually observed, diluted
by the assumed start-up lag. Verdicts: `exceeded`, `met`, `partial`, `not_met`, `inconclusive`, `insufficient_data`.
Only the metric the action moves is compared (kits on hand, enrollment rate); the days and dollars are not observed
separately.

When an action is `partial` or `not_met` after at least 6 observed weeks, the system reopens the alert, records
`ops.intervention.replan` in the audit trail and the UI asks the user to plan a different action. This happens once
per intervention. A single site's enrollment rate is too noisy to resolve small predicted effects: the options table
warns about this when the predicted change is below the metric's detection floor.

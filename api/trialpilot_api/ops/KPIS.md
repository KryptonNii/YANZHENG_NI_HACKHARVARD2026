# Operations command-center KPIs

The health endpoint returns 14 KPIs. They cover the operational signals that can change trial cost,
site workload, patient burden, supply continuity, or the database-lock date. The dashboard shows study,
country, and site rollups where the feed supports that level. Forecast comparisons use the current plan
and preserve uncertainty bands. In the demo, observed activity is a simulated feed; missing observations
remain unknown.

| KPI | Calculation and scope | Why it matters |
| --- | --- | --- |
| Enrollment vs plan band | Cumulative enrolled patients compared with the plan's P10/P50/P90 forecast, at study, country, and site level. | Early enrollment gaps threaten the completion date and can make the planned site mix uneconomic. |
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

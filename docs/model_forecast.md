# Forecasting and drug supply

How TrialPilot turns a trial design into an **enrollment forecast**, a **duration**, and a **drug-supply**
comparison of upfront versus on-demand site shipments. Each headline number is a P10 / P50 / P90.
Code: `engine/trialpilot_engine/forecast.py` and `supply.py` (owner A3). Cost, carbon and the other
modules that *consume* these results are in [model.md](model.md).

A number that the library does not contain is never silently zero. The code falls back to an
explicit built-in assumption, names the id in `warnings`, and records it on the provenance item.

---

## 1. Enrollment forecast

Poisson–gamma recruitment (Anisimov & Fedorov, *Statistics in Medicine* 2007;26(27):4958–75,
doi:10.1002/sim.2956).

Site \(i\) opens at \(a_i\) and then randomises as a Poisson process with rate \(\lambda_i\):

\[
a_i \sim \mathrm{Triangular}(\texttt{site.activation\_months}), \qquad
\lambda_i \sim \mathrm{Gamma}\!\left(\alpha,\; \mathrm{mean} = m \cdot w_i\right)
\]

\(\alpha\) is `site.enrollment_rate_shape` (\(\alpha = 1/\mathrm{CV}^2\)). \(w_i\) is the site's
weight: `expected_enrollment` divided by the mean of the sites that have one, or 1 when none do.
Sites with a missing expected enrollment get weight 1 and a warning. \(m\) is the mean rate per
site-month, chosen in this order:

1. **`site.enrollment_rate_per_month` if it is in the library.** The library value wins. Baseline
   duration then does **not** match the registered plan.
2. **Otherwise the rate implied by the registered plan**, when `duration_months` is present and the
   enrollment window below is positive:
   \[
   \text{window} = \texttt{duration\_months} - \text{follow-up} - \texttt{trial.closeout\_months (mid)}
   \]
   \[
   m_{\text{plan}} = \frac{n_{\text{mid}}}{(\sum_i w_i)\;\mathbb{E}[(\text{window}-a)^+]}
   \]
   \(\mathbb{E}[(\text{window}-a)^+]\) is a 2,000-point midpoint quadrature of the activation
   triangle. The simulated mean is \(m_{\text{plan}}\) times `forecast.plan_rate_multiplier`
   (default 0.75 / 1.0 / 1.25, no optimism bias).
3. **Otherwise the built-in rate** 0.1 / 0.5 / 1.5 patients per site-month, with a warning.

Patients to randomise, so that the enrollment *target* is patients who finish:

\[
n = \left\lceil \frac{\text{target}}{1 - d} \right\rceil, \qquad
d = \mathrm{clip}\big(\texttt{patient.dropout\_rate}\cdot(1 - u_{\text{drop}}),\, 0,\, 0.95\big)
\]

\(u_{\text{drop}}\) is `lever.decentralised.dropout_reduction` times the share of on-study visits
moved home or remote. The recruitment mean is multiplied by \(1 + u_{\text{rate}}\) the same way,
using `lever.decentralised.recruitment_uplift`. Both levers default to 0: moving visits does
nothing until someone enters a sourced uplift. That assumption is written on the result.

Cumulative intensity \(M(t) = \sum_i \lambda_i (t - a_i)^+\) is piecewise linear. By the
time-change theorem the \(k\)-th randomisation is at \(M^{-1}(\Gamma_k)\) with
\(\Gamma_k \sim \mathrm{Gamma}(k, 1)\). The code inverts \(M\) exactly (no time grid, no
per-patient loop). Time to full enrollment is \(M^{-1}(\Gamma_n)\). First patient in is
\(M^{-1}(E_1)\) with \(E_1 \sim \mathrm{Exponential}(1)\).

Duration, in months from study start:

\[
\text{duration} = t_{\text{full}} + \text{follow-up} + \texttt{trial.closeout\_months}
\]

Follow-up is the last scheduled visit week minus the baseline week (first on-study week), divided
by \(52/12\). With no visit schedule it is a draw of `trial.followup_months` and a warning says so.
Milestones are first patient in, last patient in, last patient last visit, and database lock.

The enrollment curve at month \(t\), conditional on the \(n\)-th arrival having intensity
\(\Gamma_n\), is \(\mathrm{Binomial}(n-1,\, M(t)/\Gamma_n)\) before the target and \(n\) after it.
**The curve bands use the first 500 draws. Milestones and duration use every requested draw.**
Both counts are in the warning and in `provenance[0].inputs` as `curve_draws_requested` and
`curve_draws_used`. A forecast asked for fewer than 2,000 draws says so as well.

### Posterior update

`update_with_actuals` takes cumulative randomisations per site, `[(month, count), ...]`. The data
cut-off is the latest month any included site reports. For a site with \(k_i\) patients over
\(\tau_i = (\text{cut-off} - a_i)^+\) open months (activation is capped at the site's first
recorded patient, because activation itself is not observed):

\[
\lambda_i \mid k_i, \tau_i \sim \mathrm{Gamma}(\alpha + k_i,\; \alpha/m_i + \tau_i)
\]

Sites with **no** data are not treated as zero. Their count at the cut-off is drawn from the prior
predictive, and the warning says how many sites that was. The patients still to come,
\(n - K\), are forecast from the cut-off with the posterior rates. Supply can run on that updated
forecast: already-randomised patients are placed uniformly between activation and the cut-off.

`estimate_rate_hyperparameters(counts, exposure_months)` is the method-of-moments fit for building
library values, not a number the forecast invents on its own. With \(k_i \sim \mathrm{Poisson}(\lambda_i \tau_i)\)
and \(\lambda_i \sim \mathrm{Gamma}(\alpha, \text{mean }\mu)\):

\[
\hat\mu = \frac{\sum k}{\sum \tau}, \qquad
\widehat{1/\alpha} = \max\left(0,\; \frac{\sum[(k_i - \hat\mu\tau_i)^2 - \hat\mu\tau_i]}{\sum \hat\mu^2 \tau_i^2}\right)
\]

The function returns \((\hat\mu, \mathrm{CV})\) with \(\mathrm{CV} = \sqrt{1/\alpha}\).

### Forecast parameters

| id | Built-in low / mid / high | Role |
|---|---|---|
| `site.activation_months` | 1 / 4 / 10 months | Per-site opening delay |
| `site.enrollment_rate_per_month` | 0.1 / 0.5 / 1.5 | Used only when the plan cannot set \(m\). **If the library has this id, it replaces the plan.** |
| `site.enrollment_rate_shape` | 0.7 / 1.5 / 4 | Gamma shape \(\alpha\) (between-site CV about 1.2 to 0.5) |
| `forecast.plan_rate_multiplier` | 0.75 / 1.0 / 1.25 | Uncertainty around the plan-implied rate |
| `patient.dropout_rate` | 0.05 / 0.15 / 0.25 | Share who do not finish |
| `trial.followup_months` | 6 / 12 / 24 | Only when the design has no visits |
| `trial.closeout_months` | 2 / 4 / 6 | Last visit to database lock |
| `lever.decentralised.recruitment_uplift` | 0 / 0 / 0 | Relative rate change if every visit were home/remote |
| `lever.decentralised.dropout_reduction` | 0 / 0 / 0 | Relative dropout cut in that same case |

Draws are triangular. A point value (low = mid = high) is constant. The uniform numbers behind a
parameter depend only on `(seed, parameter id)`, so two scenarios share draws. Excluding a site
drops that site's column and leaves every other site's rate and activation draws unchanged.

---

## 2. Drug supply

For each forecast draw the simulation places that draw's patients on sites and weeks, gives each
the protocol's dispensing visits, and steps every site's inventory week by week.

**Patients.** Conditional on \(n\) arrivals before \(t_{\text{full}}\), site is multinomial with
probabilities proportional to \(\lambda_i (t_{\text{full}} - a_i)^+\), and the week is uniform on
that interval. Patients already observed (`update_with_actuals`) are uniform between activation and
the cut-off. A dropout stops after a uniformly random number of dispensings (at least one). The
same forecast draws and the same seed produce the same patients for both strategies.

**Schedule.** Visits whose procedure code contains `dispens`, `imp_admin`, `drug_admin`,
`ip_admin`, `dosing` or `infusion` (A4: `drug_dispensing`, `imp_administration`). Weeks are
relative to the baseline visit. If no dispensing code is found, every on-study visit except the
last is treated as dispensing and the assumption is recorded. With no visits at all, a dispensing
every `supply.dispensing_interval_weeks` is assumed.

**One week at a site, in order.**

1. Shipments that were ordered `lead time` weeks ago arrive. A site opening this week receives its
   initial stock.
2. FIFO expiry. A shipment expires `shelf life` after it reaches the site. With one shelf life per
   draw, FIFO-by-arrival is FIFO-by-expiry, so the kits expiring at week \(t\) are
   \(\max(0,\; \text{cumulative arrivals up to } t-\text{shelf} - \text{cumulative removals})\).
   Kits that will expire before a resupply could arrive are not counted as usable.
3. Dispensing. Demand the site cannot meet is a **stockout**, filled the same week by an emergency
   shipment (it is produced, it is not taken from a lot that then expires).
4. Resupply. The IRT's projected need is the dispensings of patients already randomised that fall
   in the next \(k\) weeks, **including visits a future dropout will miss**, plus the planned
   recruitment rate times new-patient kits. It does not know the realised site rate and it does not
   know future dropouts. When usable stock + in transit is below that projection plus safety
   stock, the site is shipped up to `order_up_to_factor` times the projection, plus safety stock.

The two strategies differ **only** in the initial shipment at activation:

- **upfront** — planned patients at the site × kits per patient × \((1 + \texttt{supply.overage\_share.upfront})\)
- **on-demand** — projected need for the next \(k\) weeks + safety stock

They then share the resupply rule above. Kits still at the site or in transit when that draw's
trial ends are destroyed.

\[
\text{produced} = \text{dispensed} + \text{expired} + \text{destroyed at close}
\]

That identity is checked on every draw. Waste share is \(100 \times \text{wasted} / \text{produced}\)
(percent). Shipment totals use unit `count` (contract v4) and are built with normal
`MetricRange` validation. `stockout_probability` is the share of draws with any emergency shipment.
Above `supply.stockout_warning_threshold` (default 5%) the result carries a warning.

`drug_type` of `none` or `device` returns zero kits and a warning. `unknown` uses the generic shelf
life and says so. `supply.shelf_life_months.<drug_type>` overrides the generic shelf life.

### Supply parameters

Policy settings use the **mid** value only (they are decisions, not uncertainties): safety stock,
cover window, order-up-to factor, stockout threshold. The others are drawn per forecast draw.

| id | Built-in low / mid / high | Role |
|---|---|---|
| `supply.kits_per_dispensing_visit` | 1 / 1 / 1 kit | Kits handed out at each dispensing visit |
| `supply.dispensing_interval_weeks` | 4 / 4 / 4 | Only with no visit schedule |
| `supply.overage_share.upfront` | 0.50 / 0.75 / 1.00 | Initial upfront shipment above planned need |
| `supply.site_safety_stock_kits` | 4 | Kits kept at an active site (mid only) |
| `supply.on_demand.cover_weeks` | 6 | Trigger window \(k\) (mid only) |
| `supply.order_up_to_factor` | 2 | Resupply covers two trigger windows (mid only) |
| `supply.resupply_lead_time_weeks` | 1 / 1 / 2 | Depot to site |
| `supply.shelf_life_months` | 12 / 18 / 24 | Remaining shelf life on arrival. `supply.shelf_life_months.<drug_type>` wins |
| `supply.stockout_warning_threshold` | 0.05 | Warn above this share of draws |

Depot and production overage above what is shipped to sites is out of scope. The on-demand
projection sees the visit schedule exactly and only hides future dropouts, so its waste is
optimistic relative to an IRT that also mis-forecasts visit dates.

### How many draws supply actually runs

The caller asks for `draws` (default **500**, `SUPPLY_DRAWS`). The forecast may have more; supply
never uses more than it was given. A work budget of 6,000,000 (sites × weeks + half of
patient-dispensings, per draw) can lower the count, but not below **100** (`_MIN_DRAWS`) unless
the caller asked for fewer than 100. The result always carries:

- `draws_requested` — the `draws` argument
- `draws_used` — the count actually simulated
- the same pair in the warning, when they differ, and in the provenance assumption and inputs
  (`draws_requested`, `draws_available`, `draws`)

This cap was **not** tightened to chase a latency target. Ranges from fewer draws are noisier;
the warning says that.

---

## 3. Calibration

Built-in upfront overage 0.50 / 0.75 / 1.00 is read from ZS (2025), "Rethinking waste management
in clinical supply chains": teams routinely plan for 150% to 200% overage, taken here as shipping
1.5–2× planned need. With that range, simulated upfront waste on a 40-site test design sits near
the median **50%** of IMP kits reported by IQVIA (2024), "Reducing Waste with Intelligent
Automation" (Duerr). ZS also reports about 60% of manufactured clinical supplies lost. The check
in `test_upfront_waste_lands_in_the_industry_range` requires upfront P50 waste in 40–65% on that
40-site design. These citations are assumptions about the *policy*, not fitted coefficients.

Seed 7, built-in parameters, forecast 2,000 draws (milestones), supply requested 500. Measured
2026-10-16 on this machine (see §5 for how many supply draws actually ran):

| trial | sites | duration P50 (plan) | supply draws | upfront waste | on-demand waste | shipments up / on-demand |
|---|---|---|---|---|---|---|
| NCT03930732 BOREAS | 275 | 48.7 mo (plan 48.6) | 103 of 500 | 60% | 16% | 1444 / 2521 |
| NCT04429503 PHOTON | 138 | 47.6 mo (plan 47.6) | 188 of 500 | 58% | 9% | 872 / 1409 |
| NCT04535986 | 122 | 26.1 mo (plan 26.1) | 444 of 500 | 51% | 20% | 174 / 687 |

On-demand wastes less and ships more often. That is the comparison `compare_strategies` is for:
same patients, same resupply rule, different initial allocation. Stockout risk on these built-in
runs was 0 or about 1% (PHOTON on-demand).

---

## 4. Worked example

40 sites, target 400, 30 months, 13 dispensing visits every 4 weeks, biologic, **built-in**
parameters, seed 7, supply on the first 200 forecast draws (no budget cut at this size).
Recompute with `forecast` then `compare_strategies(..., seed=7, draws=200)`.

| | upfront | on-demand |
|---|---|---|
| waste P50 | 50.8% | 4.9% |
| shipments P50 | 77 | 387 |
| stockout | 0 | 0 |

Kits produced equal kits dispensed + expired + destroyed on every draw. Shortening shelf life to
6 months makes upfront expiry positive; 240 months makes it zero. Two kits per dispensing visit
doubles kits needed. A posterior update that puts every site at 3 patients by month 6 shortens
P50 time-to-full-enrollment from 13.1 months to 9.7 months, and supply on that updated forecast
still conserves kits.

---

## 5. Real library, and a posterior update

The checked-in parameter library **contains** `site.enrollment_rate_per_month`, so rule 1 in §1
applies: the plan-implied rate is not used, and duration moves off the registered plan. No
coefficient was tuned to pull it back. Same seed 7, forecast 2,000 draws, supply requested 500.

| trial | enrol P50 | duration P50 (P10–P90) | supply draws | upfront waste / shipments | on-demand waste / shipments | on-demand stockout |
|---|---|---|---|---|---|---|
| NCT03930732 | 8.8 mo | 27.2 (26.0–29.2) | 170 of 500 | 66% / 438 | 15% / 1947 | 0.24 |
| NCT04429503 | 10.0 mo | 48.2 (46.5–51.1); plan-rate run was 47.6 | 178 of 500 | 70% / 1294 | 6% / 2277 | 0.19 |
| NCT04535986 | 11.3 mo | 19.1 (16.8–22.8) | 500 of 500 | 65% / 134 | 18% / 622 | 0.19 |

PHOTON's library duration stays near the plan because that trial's follow-up dominates. BOREAS
does not: 48.7 months on the built-in plan rate, **27.2 months** once the library rate is used.
On-demand stockout risk is no longer ~0; the result warns, because 0.24 is above the 5% threshold.

Posterior, library, seed 7: the first 10 sites each report 1 patient at month 8, and the other
sites are drawn from the prior predictive (not set to zero).

| trial | enrol P50 before → after | duration P50 before → after |
|---|---|---|
| NCT03930732 | 8.80 → 8.87 | 27.21 → 27.28 |
| NCT04429503 | 9.99 → 10.18 | 48.24 → 48.40 |
| NCT04535986 | 11.29 → 11.54 | 19.09 → 19.32 |

Ten sites of data do not move a hundreds-site prior very far. The direction is "slightly slower",
which is what one patient at month 8 against a fast library rate should do. Supply still runs on
the updated draws and still conserves kits (`test_supply_runs_on_an_updated_forecast`).

---

## 6. Performance limits

What is capped, and what was not done to look faster:

- Enrollment **milestones and duration use every requested draw** (the API asks for 2,000).
- The **enrollment curve uses 500** of those draws. The warning and the provenance inputs name
  both counts. Curve points are at most about 120.
- **Supply asks for 500** draws by default and may run fewer under the work budget above, never
  below 100 unless the caller asked for fewer. Requested and actual are on the result. The budget
  and the 500 were **not** reduced in order to pass a timer.
- Test seeds were not pinned to a fast seed. The latency numbers below are every call, not the
  minimum alone. No result cache is included: each line is a fresh function call.
- The 120-site unit test still asserts that the fastest of three calls is under 1 second. That
  assertion is not the 300 ms full-interface target. The handoff lists all three calls.

120 sites, 1,200 patients, 13 dispensing visits, on-demand, seed 7, forecast 2,000 + supply
(232 of 500 draws). Three calls in one process, no discarded warmup: **0.203 s, 0.172 s, 0.167 s**
(median **0.172 s**). An earlier trio taken while another snapshot of the same functions was
running on this machine was 0.325 s, 0.408 s, 0.373 s. Do not read the gap as a pure speedup;
the later trio is the one to cite.

One PHOTON library on-demand `simulate_supply` profiled before the week-index tightening was
0.26 s inside that function. The same call afterwards, wall clock, was **0.121 s** (178 of 500
draws). Forecast on these three trials is about 0.02–0.05 s at 2,000 draws.

**The full HTTP compute is a different measurement and is not under 300 ms.** Independent run of
the OQ protocol (`POST /api/scenarios/compute`, NCT03930732, real library, draws 2,000, seeds
200–206, each `X-Cache: miss`, queue 0), 2026-10-16. Every `X-Compute-Ms`:

**615.5, 492.6, 523.0, 591.8, 657.0, 620.0, 701.1.** Median **615.5 ms**. The fastest seed is
492.6 ms and is not the result. The same machine's direct `forecast` + `simulate_supply` on this
trial is about 0.05 s + 0.11 s, so most of the 615 ms is outside those two calls (the header
covers the whole compute, including the engine and response assembly). A5's earlier clean-clone
full run (median 664.1 ms at commit `38e2073`) is the validation record; this measurement does
not replace it, and it does not clear the 300 ms gate. Slider repeats that hit A5's cache are a
different path.

---

## 7. What this model does not claim

Integration update (2026-10-17): the API's forecast view now carries
`draws_requested`, `draws_used`, `curve_draws_used` and provenance; the supply
view carries `draws_requested`, `draws_used` and provenance. Existing records
without counts return null. Producer warnings and assumptions survive saving,
the signed record hash, and exports. No numerical sampling cap was changed.
The timing measurements above are preserved historical observations; the final
combined-commit cold HTTP measurements are recorded in handoffs/BACKEND_FINAL.md.

- Screen failures are not separate from the dropout inflation.
- Sites have no enrollment caps and do not compete for patients.
- Ranges are uncertainty about the average rates and policy parameters, plus the Poisson–gamma
  recruitment noise. They are not a between-patient residual on top of that.
- On-demand waste is optimistic (§2).
- Home or remote visits do not shorten enrollment unless a sourced decentralised uplift is set.

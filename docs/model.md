# TrialPilot calculation model

How TrialPilot turns a trial design and a set of design levers into **cost, site staff time, patient
time, carbon, duration and drug waste**, each as a P10 / P50 / P90 range with a provenance trail.
Code: `engine/trialpilot_engine/` (owner A2). Forecasting and drug-supply simulation (A3):
[model_forecast.md](model_forecast.md).

Carbon follows the Low Carbon Clinical Trials Group method (Griffiths, Fox, Williamson, *BMJ Open*
2024, https://bmjopen.bmj.com/content/14/1/e075755): footprint = Σ activity data × emission factor,
counting only trial-specific activity beyond routine care, reported in the paper's modules. As in the
method, every travel and freight factor also carries its well-to-tank (WTT) emissions (§5, *Well-to-tank*).
Cost and site staff time reuse the same activity data with cost and time parameters.

**The engine contains no real-world numbers.** Every value comes from the parameter library
(`data/params/*.yaml`, sources in [sources.md](sources.md)); the code holds formulas, calendar
constants (365.25 days per year) and unit conversions (1,000 kg per tonne) only.

---

## 1. How a number is made

```
TrialDesign + Levers ──► activity data ──► terms (activity × parameter draws) ──► totals ──► P10/P50/P90
   (levers.py)              (levers.py)    (burden, workload, carbon, cost .py)   (model.py)
```

1. **Activity** (`levers.build_activity`): applies the levers to the design and fixes the trial's
   structure — active sites per country, patients per country, each visit's mode (on site, home,
   telehealth) and procedures, samples per patient by temperature, dispensing visits.
2. **Terms**: each formula multiplies activity by parameter draws and yields one *term*: one metric
   (USD, kg CO2e, site staff hours or patient hours) in one module, for every Monte Carlo draw.
3. **Totals**: module cost = Σ its cost terms; module carbon = Σ its carbon terms; headline cost /
   carbon / site staff hours / patient hours = Σ over modules (the `intervention` module is excluded).
4. **Ranges**: P10, P50, P90 of the per-draw totals.

Every term becomes a `ProvenanceItem` in its module (`ScenarioResult.modules[].provenance`):
`formula_id` (prefix = metric family: `cost.*` USD, `carbon.*` kg CO2e, `workload.*` site staff hours,
`burden.*` patient hours), a plain-English `description`, `inputs` (activity counts plus the term's
own `result_p10/result_p50/result_p90/result_unit`), the `parameter_ids` it read, and `assumptions`
(fallbacks taken, missing parameters, design assumptions). The UI finds e.g. the provenance of
*site staff hours* by collecting `workload.*` items across modules.

## 2. Uncertainty

- **Sampling.** Each parameter is drawn from triangular(`value_low`, `value_mid`, `value_high`); a point
  value (low = mid = high) is constant. N = 2,000 draws by default, seed 7.
- **Common random numbers.** The uniform numbers behind a parameter depend only on (seed, parameter id).
  Two scenarios computed with the same seed see the same draw of every shared parameter, so per-draw
  differences isolate the levers. Parameters are sampled independently of each other.
- **One draw per parameter per iteration.** A parameter (e.g. a country's patient round-trip distance)
  takes one value per draw and applies to every patient it covers: the ranges express uncertainty about
  the *average*, not patient-to-patient variability.
- **`compare(a, b)`** returns b − a computed draw by draw (not P50 − P50), for the six headline metrics
  and for `cost_usd.<module>` / `co2e_kg.<module>`. Both results must come from `compute_scenario` in
  the same process with the same seed and draws; otherwise it raises `DrawsUnavailableError` and
  `compare_levers(design, levers_a, levers_b, params, …)` recomputes both and compares.
- **`drivers(…, metric)`** ranks parameters by the share of the metric's variance each explains alone
  (squared Pearson correlation between the parameter's draws and the metric's draws, 0–1). With
  independent inputs and a near-additive model the shares add up to about 1; multiplicative
  interactions make the sum smaller. When an A3 forecast is passed and varies, the trial duration
  appears as `a3.forecast.duration_months`.
- **Inputs from A3 as ranges.** A3's `ForecastResult.duration_months` and `SupplyResult` arrive as
  P10/P50/P90. The engine rebuilds per-draw values with a piecewise-linear quantile function through
  (0.1, P10), (0.5, P50), (0.9, P90), outer segments extended linearly to quantiles 0 and 1, clipped at
  0. Kits produced, waste share and shipments share one uniform stream (perfectly rank-correlated).
  If the forecast object also carries a `duration_draws` array of length N, it is used directly.
  An **unknown** A3 range (P10/P50/P90 `null`, contract v2) gives NaN draws, never zeros: duration (or
  kits made / waste / shipments) and every term that uses it are unknown and excluded, and a warning names
  the A3 output. An unordered known range (P10 > P50 or P50 > P90) raises `ValueError`.

## 3. Missing inputs — unknown is not zero

- A parameter missing from the library yields NaN draws. Any term touching it is **unknown**: it is
  excluded from totals, its provenance says `result: unknown …` and names the missing id, and
  `ScenarioResult.warnings` says which metric excludes which term and that the total is understated.
- A total with terms but none known is **unknown**: its `MetricRange` has `p10 = p50 = p90 = None`
  (JSON `null`, contract v2), shown as "unknown", never 0. A total with some known terms is the sum of
  those, and the warnings say it is understated.
- `missing_parameters(design, levers, params)` lists the ids a scenario needs that the library lacks.
- Country-specific parameters are looked up as `<id>.<cc>` (lowercase ISO 3166 alpha-2, from country
  names such as "United Kingdom" → `gb`), else `<id>.global`; procedure minutes as
  `time.site.procedure.<code>`, else `time.site.procedure.default`. Every fallback is written into the
  term's `assumptions`.
- Incomplete designs:
  - **No visit schedule** → round(mid of `assume.design.visits_per_patient`) visits, evenly spaced over the
    planned duration, with no procedures; a warning says so. If that parameter is also missing the engine
    raises `EngineInputError("design_incomplete")`.
  - **No sites** → ceil(enrollment ÷ mid of `assume.design.patients_per_site`) sites in an unknown country
    (`.global` parameters); a warning says so.
  - **Site expected enrollment missing** → patients split equally (or missing sites get the mean of the
    known ones); noted in provenance.
  - **Sample temperature missing** → shipped as ambient; warning (understates frozen shipping if they are frozen).
  - **No dispensing procedure** in a drug trial → every visit assumed to dispense kits; warning.
- Lever problems: shares outside 0–1, all sites excluded, or `draws < 1` raise `EngineInputError`
  (`code` = `invalid_levers` / `invalid_design` / `invalid_request`; the API maps it to HTTP 422).
  Lever targets that do not exist (visit numbers, procedure codes, site ids) are ignored with a warning.

## 4. Activity model and levers

Notation: P = enrollment target (patients), S = active sites, S<sub>c</sub> / P<sub>c</sub> = sites /
patients in country c, D = trial duration in months (A3 forecast per draw, else the planned duration),
V<sub>site</sub>, V<sub>home</sub>, V<sub>remote</sub> = visits per patient by mode.

- **Patients per site**: P is split over active sites in proportion to `Site.expected_enrollment`
  (equal when unknown), then grouped by country. Every enrolled patient attends every scheduled visit
  (no dropout in the engine; A3 handles dropout in the forecast).
- **Sample events** per patient: one per procedure with `ships_sample`, by temperature class
  (`frozen_-20`/`frozen_-80` → frozen; `refrigerated`; `ambient` or unstated → ambient).
- **Dispensing visits**: visits with a procedure whose code contains `dispens`, `imp_admin`,
  `drug_admin`, `ip_admin`, `dosing` or `infusion` (A4 vocabulary: `drug_dispensing`, `imp_administration`).

| Lever | Effect on activity (only this) | Moves |
|---|---|---|
| `remote_monitoring_share` = r | monitoring visits split: on-site trips × (1 − r), remote reviews × r | meetings_travel cost and carbon, site staff hours |
| `home_visit_numbers` | those visits become home-nursing visits: no patient travel; nurse cost + nurse car km; site staff procedure minutes × home factor | patient_assessments, patient hours, site staff hours |
| `remote_visit_numbers` | those visits become telehealth: no patient travel; telehealth cost; procedure minutes × telehealth factor. Samples in a telehealth visit are still counted (warning) | patient_assessments, patient hours, site staff hours |
| `local_lab_share` = l | central-lab shipments × (1 − l); lab price mix; harmonisation cost l × S | samples, laboratory cost |
| `drug_supply_strategy` | waste share `supply.waste_share.<strategy>` and shipments, or A3's simulation when passed | drug_supply, drug waste share |
| `removed_procedures` | codes removed from every visit (minutes, samples, dispensing) | site staff hours; samples, laboratory if they shipped samples |
| `excluded_site_ids` | sites removed; P redistributed over the remaining sites (target unchanged); A3's forecast lengthens | every per-site term; duration via A3 |

A visit moved home or to telehealth while `can_be_remote` is false is still moved (the lever is the
user's decision) but produces a warning. A visit in both lists is treated as a home visit.

## 5. Formulas by module

Units: USD, kg CO2e, hours; km are round trips unless stated "one way". `share` parameters are 0–1.

### patient_assessments (patient travel and visits)

| formula_id | Formula |
|---|---|
| `burden.patient_travel_time.v1` | Σ<sub>c</sub> P<sub>c</sub> × V<sub>site</sub> × `dist.patient.roundtrip_km.<cc>` ÷ `time.patient.travel_speed_kmh.<cc>` |
| `burden.patient_visit_time.v1` | P × (V<sub>site</sub> × `time.patient.visit_at_site` + V<sub>home</sub> × `time.patient.home_visit` + V<sub>remote</sub> × `time.patient.remote_visit`) |
| `carbon.patient_travel.v1` | Σ<sub>c</sub> P<sub>c</sub> × V<sub>site</sub> × km<sub>c</sub> × [car × `ef.travel.car.average_km` + (1 − car) × (rail × `ef.travel.rail.passenger_km` + (1 − rail) × `ef.travel.bus.passenger_km`)], car = `rate.patient.mode_share.car.<cc>`, rail = `rate.patient.mode_share.rail.<cc>` (share of the non-car km) |
| `carbon.home_nurse_travel.v1` | P × V<sub>home</sub> × `dist.home_nurse.roundtrip_km` × `ef.travel.car.average_km` |
| `carbon.procedures.v1` | P × Σ<sub>visits</sub> Σ procedures with a factor `ef.procedure.<code>` (optional: codes without a factor are listed as not modelled; no `.default`) |
| `workload.patient_visits.v1` | P × Σ<sub>visits</sub> [`time.site.visit_admin` + f<sub>mode</sub> × Σ procedure minutes] ÷ 60; procedure minutes = `Procedure.site_minutes` from the design if given, else `time.site.procedure.<code>`; f = 1 on site, `rate.site.minutes_factor.home_visit`, `rate.site.minutes_factor.remote_visit` |
| `cost.patient_reimbursement.v1` | P × V<sub>site</sub> × `cost.patient.reimbursement_visit` |
| `cost.home_nursing.v1` | P × V<sub>home</sub> × `cost.home_nurse.visit` |
| `cost.telehealth.v1` | P × V<sub>remote</sub> × `cost.telehealth.visit` |
| `cost.site_staff_visits.v1` | hours of `workload.patient_visits.v1` × `cost.site_staff.hour` |

One patient per car trip (vehicle-km factor); companions add no car km. Telehealth energy is not modelled.

### meetings_travel (monitoring trips + investigator meeting)

Monitoring visits in country c = S<sub>c</sub> × `rate.monitoring.onsite_visits_per_site_month` × D;
on site × (1 − r), remote × r.

A CRA trip (also used for site initiation and close-out) in country c has round trip
`dist.monitoring.roundtrip_km.<cc>`; it is flown when the one-way distance exceeds
`dist.monitoring.flight_threshold_km` (domestic flight factor `ef.travel.flight.domestic.passenger_km`),
otherwise driven (`ef.travel.car.average_km`).

| formula_id | Formula |
|---|---|
| `carbon.monitoring_trips.v1` | Σ<sub>c</sub> on-site visits<sub>c</sub> × round trip<sub>c</sub> × (car or domestic flight factor) |
| `carbon.investigator_meeting.v1` | one kickoff: S × `rate.investigator_meeting.attendees_per_site` × `dist.investigator_meeting.roundtrip_km` × factor; factor = car below the flight threshold (one way), `ef.travel.flight.short_haul.passenger_km` up to `dist.flight.short_haul_max_km`, else `ef.travel.flight.long_haul.passenger_km` |
| `workload.monitoring_support.v1` | on-site visits × `time.site.monitoring_visit_support` |
| `workload.remote_monitoring_review.v1` | remote visits × `time.site.remote_monitoring_review` |
| `cost.monitoring_onsite.v1` | on-site visits × (`cost.monitoring.cra_day_rate` × `time.monitoring.onsite_visit_days` + `cost.monitoring.travel_expenses_per_trip`) |
| `cost.monitoring_remote.v1` | remote visits × `cost.monitoring.cra_day_rate` × `time.monitoring.remote_visit_days` |
| `cost.site_staff_monitoring.v1`, `cost.site_staff_remote_review.v1` | the workload hours above × `cost.site_staff.hour` |
| `cost.investigator_meeting.v1` | S × attendees per site × `cost.investigator_meeting.per_attendee` |

Remote monitoring has no travel emissions. Monitoring frequency applies over the whole trial duration.

### setup and closeout

| formula_id | Formula |
|---|---|
| `carbon.site_initiation_trips.v1` | Σ<sub>c</sub> S<sub>c</sub> × one CRA trip<sub>c</sub> |
| `carbon.setup_per_site.v1` | S × `ef.setup.per_site` (set-up other than initiation travel) |
| `cost.setup.v1` | S × `cost.setup.per_site` |
| `carbon.closeout_trips.v1` | Σ<sub>c</sub> S<sub>c</sub> × one CRA trip<sub>c</sub> |
| `carbon.archiving.v1` | S × `rate.closeout.archive_boxes_per_site` × `time.closeout.archive_years` × `ef.closeout.archiving_per_box_year` |
| `cost.closeout.v1` | S × `cost.closeout.per_site` |

### trial_management, data_collection, supplies_equipment

| formula_id | Formula |
|---|---|
| `carbon.trial_management.v1` | `rate.trial_management.fte` × D ÷ 12 × `ef.trial_management.per_fte_year` |
| `cost.trial_management.v1` | `rate.trial_management.fte` × D ÷ 12 × `cost.trial_management.per_fte_year` |
| `carbon.data_collection.v1` | P × (last − first scheduled visit week) ÷ 52.18 × `ef.data_collection.per_patient_year` |
| `cost.data_collection.v1` | P × `cost.data_collection.per_patient` |
| `workload.query_handling.v1` | P × `rate.queries.per_patient` × `time.site.query_resolution` ÷ 60 |
| `cost.site_staff_queries.v1` | query hours × `cost.site_staff.hour` |
| `carbon.supplies.v1` / `cost.supplies.v1` | P × `ef.supplies_equipment.per_patient` / `cost.supplies_equipment.per_patient` |

### samples and laboratory

Central-lab shipments in country c, temperature t = P<sub>c</sub> × samples per patient<sub>t</sub> ×
(1 − l) ÷ `supply.sample.samples_per_shipment`.

| formula_id | Formula |
|---|---|
| `carbon.sample_freight.v1` | Σ<sub>c,t</sub> shipments × `supply.sample.shipment_weight_kg.<temp>` ÷ 1000 × `dist.sample.to_central_lab_km.<cc>` × (`ef.freight.air.tonne_km` if frozen, else `ef.freight.van.tonne_km`) |
| `carbon.dry_ice.v1` | frozen shipments × `supply.sample.dry_ice_kg_per_shipment` × `ef.dry_ice.kg` |
| `carbon.freezer_storage.v1` | if any −80 °C sample: Σ<sub>c</sub> S<sub>c</sub> × `energy.freezer.minus80.trial_share` × `energy.freezer.minus80.kwh_per_day` × D × 30.44 days × `ef.electricity.grid.<cc>` |
| `cost.sample_courier.v1` | Σ shipments × `cost.courier.shipment.<temp>` |
| `cost.local_lab_harmonisation.v1` | l × S × `cost.lab.local_harmonisation_per_site` |
| `carbon.lab_analysis.v1` | P × samples per patient × `ef.laboratory.per_sample` (same locally or centrally) |
| `cost.lab_analysis.v1` | P × samples × ((1 − l) × `cost.lab.central_per_sample` + l × `cost.lab.local_per_sample`) |

Local-lab samples are assumed analysed close to the site (no transport modelled). −80 °C storage is
modelled at sites for the whole trial.

### Well-to-tank (WTT) of travel and freight

The published method adds well-to-tank (upstream fuel production and distribution) to every travel and
freight factor: each of its factors is a DESNZ direct factor plus the matching DESNZ WTT factor
([sources.md](sources.md) §1.3). The engine keeps WTT as a **separate term** next to each travel or
freight term, in the same module:

> `carbon.<name>_wtt.v1` = the activity of `carbon.<name>.v1` × WTT(f) in place of every direct factor f

Every travel and freight formula is linear in its factors, so `carbon.<name>.v1` + `carbon.<name>_wtt.v1`
= activity × (f + WTT(f)), the method's factor. Mode choices (car or flight by one-way distance, short- or
long-haul, air or van by temperature) are made once and are the same for both terms.

| Direct factor f | WTT(f) |
|---|---|
| `ef.travel.car.average_km` | `ef.wtt.travel.car.average_km` |
| `ef.travel.bus.passenger_km` | `ef.wtt.travel.bus.passenger_km` |
| `ef.travel.rail.passenger_km` | `ef.wtt.travel.rail.passenger_km` |
| `ef.travel.flight.domestic.passenger_km` | `ef.wtt.travel.flight.domestic.passenger_km` |
| `ef.travel.flight.short_haul.passenger_km` | `ef.wtt.travel.flight.short_haul.passenger_km` |
| `ef.travel.flight.long_haul.passenger_km` | `ef.wtt.travel.flight.long_haul.passenger_km` |
| `ef.freight.van.tonne_km` | `ef.wtt.freight.van.tonne_km` |
| `ef.freight.air.tonne_km` | `ef.wtt.freight.air.long_haul.tonne_km`: `ef.freight.air.tonne_km` is DESNZ's international air-freight row, which DESNZ sets equal to long-haul; the international WTT row equals the long-haul one (library note: D96 = D95) |

Twins: `carbon.patient_travel_wtt.v1`, `carbon.home_nurse_travel_wtt.v1`, `carbon.monitoring_trips_wtt.v1`,
`carbon.investigator_meeting_wtt.v1`, `carbon.site_initiation_trips_wtt.v1`, `carbon.closeout_trips_wtt.v1`,
`carbon.sample_freight_wtt.v1`, `carbon.drug_shipping_wtt.v1` (the last in the `drug_supply` extension).
The mapping is `carbon.WTT_FACTOR`; a test checks it covers every direct travel / freight id in the catalog.

- **Missing WTT factor** → only the twin is unknown: excluded from totals, named in warnings and provenance
  (never 0). The direct term is still counted, so the carbon total is understated by that WTT.
- **Direct ids are direct-only.** `ef.travel.*` and `ef.freight.*` are the DESNZ direct factor
  (tank-to-wheel / combustion; aviation with radiative forcing). The twin multiplies the same activity
  by `ef.wtt.*` and by nothing else. Putting a factor that already includes WTT into the direct id, while
  `ef.wtt.*` is also supplied, counts upstream fuel twice. The paper's published travel and freight
  factors are those sums (sources.md §1.3): rail 0.04441 = 0.03549 + 0.00892, domestic flight 0.27278,
  short-haul 0.17034, long-haul 0.21423, long-haul / international air freight 1.13047 = 1.0189 + 0.11157.
  Pass the two parts as the two ids, or set the twin to 0. The road figure 0.19443 matches no DESNZ row
  with or without WTT; it is not `ef.wtt.freight.van.tonne_km`.
- **Values are the library's** (DESNZ 2026 WTT cells, 2022–2026 vintage range); the engine does not
  rescale them toward the paper's DESNZ 2022 numbers.
- Other factors (electricity, dry ice, per-site / per-patient / per-sample / per-kit / per-procedure)
  are used as the library gives them. No WTT twin is added. `ef.drug_kit.unit` excludes transport;
  kit transport is only `carbon.drug_shipping.v1` plus `carbon.drug_shipping_wtt.v1`.

### drug_supply (TrialPilot extension, beyond the published method)

Without an A3 `SupplyResult`: kits needed = P × dispensing visits × `supply.kits_per_dispensing_visit`;
kits made = needed ÷ (1 − w), w = `supply.waste_share.<strategy>` (`upfront` / `on_demand`; w ≥ 1 is
invalid → unknown); shipments = S × `supply.shipments_per_site.<strategy>`. With A3's simulation:
kits made, waste share and shipments come from it (see §2).

| formula_id | Formula |
|---|---|
| `carbon.drug_kits.v1` | kits made × `ef.drug_kit.unit` (manufacture + packaging + storage, excluding transport) |
| `carbon.drug_shipping.v1` | kits made × `supply.kit_shipping_weight_kg` ÷ 1000 × `dist.drug.depot_to_site_km` × `ef.freight.van.tonne_km` |
| `cost.drug_kits.v1` | kits made × `cost.drug.kit.<drug_type>` (`biologic`, `small_molecule`, else `default`) |
| `cost.drug_shipments.v1` | shipments × `cost.drug.shipment` |

`drug_waste_share` (percent) = 100 × w. Trials with `drug_type = "none"` have no kits.

### intervention

Zero, with the warning "drug manufacture excluded (as in the published method)". Not part of totals.
**Headline carbon includes the `drug_supply` extension**; to compare with the published method,
subtract `modules["drug_supply"]`.

## 6. Headline metrics

| ScenarioResult field | Definition |
|---|---|
| `cost_usd` | Σ cost terms of all modules except `intervention` (includes site staff time at `cost.site_staff.hour` and drug kits) |
| `site_staff_hours` | Σ `workload.*` terms: patient visits + monitoring support + remote review + query handling |
| `patient_travel_hours` | Σ `burden.*` terms: travel time **plus** time spent in visits (on site, home, telehealth) — the patient time burden |
| `co2e_kg` | Σ carbon terms of all modules except `intervention` (includes `drug_supply` and the WTT twins) |
| `duration_months` | A3 forecast `duration_months` if passed, else the planned `TrialDesign.duration_months` as a point range (with a warning) |
| `drug_waste_share` | percent of kits made that are never dispensed (A3 or `supply.waste_share.<strategy>`) |

## 7. Parameter catalog

Every id the engine can read (`PARAMETER_CATALOG` in `provenance.py`; a test checks this list against
the code and this page). `<cc>` = lowercase ISO 3166 alpha-2 or `global` (the `.global` id must exist);
`<code>` = procedure code or `default`; `<temp>` = `ambient` | `refrigerated` | `frozen`;
`<drug_type>` = `biologic` | `small_molecule` | `default`; `<strategy>` = `upfront` | `on_demand`.

| id | unit | meaning |
|---|---|---|
| `dist.patient.roundtrip_km.<cc>` | km/visit | patient home ↔ site round trip per on-site visit |
| `rate.patient.mode_share.car.<cc>` | share | share of patient km by car |
| `rate.patient.mode_share.rail.<cc>` | share | share of the non-car km by rail (rest by bus) |
| `time.patient.travel_speed_kmh.<cc>` | km/hour | door-to-door average speed |
| `time.patient.visit_at_site` | hours/visit | patient time at site per visit |
| `time.patient.home_visit` | hours/visit | patient time per home-nursing visit |
| `time.patient.remote_visit` | hours/visit | patient time per telehealth visit |
| `ef.travel.car.average_km` | kg_co2e/km | average car per vehicle-km |
| `ef.travel.bus.passenger_km` | kg_co2e/passenger_km | local bus |
| `ef.travel.rail.passenger_km` | kg_co2e/passenger_km | national rail |
| `cost.patient.reimbursement_visit` | usd/visit | patient travel reimbursement per on-site visit |
| `cost.home_nurse.visit` | usd/visit | one home-nursing visit |
| `dist.home_nurse.roundtrip_km` | km/visit | home nurse round trip by car |
| `cost.telehealth.visit` | usd/visit | one telehealth visit |
| `ef.procedure.<code>` | kg_co2e/procedure | optional per-procedure factor (e.g. imaging energy) |
| `time.site.visit_admin` | minutes/visit | scheduling + documentation per patient visit |
| `time.site.procedure.<code>` | minutes/procedure | site staff minutes per procedure |
| `rate.site.minutes_factor.home_visit` | share | procedure minutes still on site staff for a home visit |
| `rate.site.minutes_factor.remote_visit` | share | procedure minutes still on site staff for a telehealth visit |
| `time.site.monitoring_visit_support` | hours/visit | site staff hours per on-site monitoring visit |
| `time.site.remote_monitoring_review` | hours/visit | site staff hours per remote monitoring visit |
| `rate.queries.per_patient` | queries/patient | data queries per patient |
| `time.site.query_resolution` | minutes/query | site time per query |
| `cost.site_staff.hour` | usd/hour | loaded site research staff hour |
| `rate.monitoring.onsite_visits_per_site_month` | visits/site/month | monitoring frequency |
| `dist.monitoring.roundtrip_km.<cc>` | km/trip | CRA base ↔ site, same country |
| `dist.monitoring.flight_threshold_km` | km | one-way distance above which a trip is flown |
| `ef.travel.flight.domestic.passenger_km` | kg_co2e/passenger_km | domestic flight (with RF) |
| `ef.travel.flight.short_haul.passenger_km` | kg_co2e/passenger_km | short-haul flight (with RF) |
| `ef.travel.flight.long_haul.passenger_km` | kg_co2e/passenger_km | long-haul flight (with RF) |
| `dist.flight.short_haul_max_km` | km | one-way distance up to which a flight is short-haul |
| `cost.monitoring.cra_day_rate` | usd/day | loaded CRA day |
| `time.monitoring.onsite_visit_days` | days/visit | CRA days per on-site visit incl. travel |
| `time.monitoring.remote_visit_days` | days/visit | CRA days per remote visit |
| `cost.monitoring.travel_expenses_per_trip` | usd/trip | travel + subsistence per on-site trip |
| `rate.investigator_meeting.attendees_per_site` | people/site | kickoff attendees per site |
| `dist.investigator_meeting.roundtrip_km` | km/attendee | kickoff round trip |
| `cost.investigator_meeting.per_attendee` | usd/attendee | travel + venue per attendee |
| `ef.setup.per_site` | kg_co2e/site | set-up excluding initiation travel |
| `cost.setup.per_site` | usd/site | site start-up |
| `cost.closeout.per_site` | usd/site | site close-out |
| `rate.closeout.archive_boxes_per_site` | boxes/site | archive boxes |
| `time.closeout.archive_years` | years | archive retention |
| `ef.closeout.archiving_per_box_year` | kg_co2e/box_year | archive storage |
| `rate.trial_management.fte` | fte | coordinating-unit / sponsor staff |
| `ef.trial_management.per_fte_year` | kg_co2e/fte_year | office energy + commuting |
| `cost.trial_management.per_fte_year` | usd/fte_year | loaded staff cost |
| `ef.data_collection.per_patient_year` | kg_co2e/patient_year | EDC hosting / data exchange |
| `cost.data_collection.per_patient` | usd/patient | EDC + data management |
| `ef.supplies_equipment.per_patient` | kg_co2e/patient | trial-specific supplies |
| `cost.supplies_equipment.per_patient` | usd/patient | trial-specific supplies |
| `supply.sample.samples_per_shipment` | samples/shipment | batching |
| `supply.sample.shipment_weight_kg.<temp>` | kg/shipment | shipped weight incl. packaging |
| `dist.sample.to_central_lab_km.<cc>` | km/shipment | site → central lab, one way |
| `ef.freight.van.tonne_km` | kg_co2e/tonne_km | road courier |
| `ef.freight.air.tonne_km` | kg_co2e/tonne_km | air freight (with RF) |
| `supply.sample.dry_ice_kg_per_shipment` | kg/shipment | dry ice per frozen shipment |
| `ef.dry_ice.kg` | kg_co2e/kg | dry ice |
| `cost.courier.shipment.<temp>` | usd/shipment | courier price |
| `energy.freezer.minus80.kwh_per_day` | kwh/day | one −80 °C freezer |
| `energy.freezer.minus80.trial_share` | share | share of one freezer used by the trial, per site |
| `ef.electricity.grid.<cc>` | kg_co2e/kwh | grid electricity |
| `cost.lab.local_harmonisation_per_site` | usd/site | harmonising a local lab |
| `ef.laboratory.per_sample` | kg_co2e/sample | analysis of one sample |
| `cost.lab.central_per_sample` | usd/sample | central lab price |
| `cost.lab.local_per_sample` | usd/sample | local lab price |
| `supply.kits_per_dispensing_visit` | kits/visit | kits per dispensing visit |
| `supply.waste_share.<strategy>` | share | kits made but never dispensed |
| `supply.shipments_per_site.<strategy>` | shipments/site | depot → site shipments (without A3) |
| `cost.drug.kit.<drug_type>` | usd/kit | one patient kit |
| `ef.drug_kit.unit` | kg_co2e/kit | manufacture + packaging + storage per kit, excluding transport |
| `supply.kit_shipping_weight_kg` | kg/kit | shipped weight per kit |
| `dist.drug.depot_to_site_km` | km | depot → site, one way |
| `cost.drug.shipment` | usd/shipment | one depot → site shipment |
| `ef.wtt.travel.car.average_km` | kg_co2e/km | well-to-tank, average car per vehicle-km |
| `ef.wtt.travel.bus.passenger_km` | kg_co2e/passenger_km | well-to-tank, local bus |
| `ef.wtt.travel.rail.passenger_km` | kg_co2e/passenger_km | well-to-tank, national rail |
| `ef.wtt.travel.flight.domestic.passenger_km` | kg_co2e/passenger_km | well-to-tank, domestic flight |
| `ef.wtt.travel.flight.short_haul.passenger_km` | kg_co2e/passenger_km | well-to-tank, short-haul flight |
| `ef.wtt.travel.flight.long_haul.passenger_km` | kg_co2e/passenger_km | well-to-tank, long-haul flight |
| `ef.wtt.freight.van.tonne_km` | kg_co2e/tonne_km | well-to-tank, road courier (van) |
| `ef.wtt.freight.air.long_haul.tonne_km` | kg_co2e/tonne_km | well-to-tank, air freight (twin of `ef.freight.air.tonne_km`) |
| `assume.design.visits_per_patient` | visits | visits assumed when the schedule is missing |
| `assume.design.patients_per_site` | patients/site | used to assume sites when none are listed |

## 8. Worked example (illustrative TEST values, not real data)

The unit tests (`engine/tests/test_modules.py`) use a tiny trial and round **test** numbers so every
step can be checked by hand. The values below are those test fixtures — they are not sourced and must
not be read as real-world estimates.

Design: 1 site in Spain (no `.es` parameters → `.global` used, noted in provenance), P = 10 patients,
D = 12 months, biologic. Visits: V1 week 0 (blood draw frozen −80 °C, ECG, drug dispensing), V2 week 26
(blood draw ambient, drug dispensing), V3 week 52 (questionnaire, 20 site minutes stated in the protocol).
Default levers (everything on site, upfront supply).

| Step | Test parameter values | Arithmetic | Result |
|---|---|---|---|
| Patient travel time | round trip 20 km, speed 30 km/h | 10 × 3 visits × 20 ÷ 30 | 20 h |
| Patient visit time | 2 h at site | 10 × 3 × 2 | 60 h → **patient time 80 h** |
| Patient travel carbon | car share 0.5 (0.2 kg/km), rail share 0.5 of the rest (0.05), bus 0.1 | 600 km × (0.5 × 0.2 + 0.5 × (0.5 × 0.05 + 0.5 × 0.1)) | 82.5 kg |
| … its WTT twin | WTT car 0.05, rail 0.01, bus 0.02 | 600 km × (0.5 × 0.05 + 0.5 × (0.5 × 0.01 + 0.5 × 0.02)) | 19.5 kg |
| Site staff, visits | admin 30 min; blood draw 15, default 10 | (65 + 55 + 50) min × 10 ÷ 60 | 28.33 h |
| Monitoring visits | 0.5 /site/month | 1 × 0.5 × 12 | 6 on-site visits |
| Monitoring support + queries | 4 h/visit; 6 queries × 10 min | 6 × 4 + 10 × 6 × 10 ÷ 60 | 24 h + 10 h → **site staff 62.33 h** |
| Monitoring carbon | 200 km round trip, one way 100 < 300 km threshold → car 0.2 | 6 × 200 × 0.2 | 240 kg |
| Kickoff meeting | 2 attendees, 1000 km, one way 500 > 300 → short-haul 0.15 | 2 × 1000 × 0.15 | 300 kg |
| … WTT twins | WTT car 0.05; WTT short-haul 0.03 | 6 × 200 × 0.05; 2 × 1000 × 0.03 | 60 kg; 60 kg |
| Site initiation, close-out trips | 1 car trip each (as monitoring) | 200 × 0.2 (+ WTT 200 × 0.05) each | 40 + 10 kg each |
| Monitoring cost | CRA 1000/day × 1.5 days + 400 expenses | 6 × 1900 | $11,400 |
| Sample freight | frozen 5 kg air 2.0/t·km; ambient 2 kg van 0.6; 500 km | 10 × 0.005 × 500 × 2.0 + 10 × 0.002 × 500 × 0.6 | 50 + 6 kg |
| … its WTT twin | WTT air 0.5, van 0.15 | 25 t·km × 0.5 + 10 t·km × 0.15 | 12.5 + 1.5 kg |
| Dry ice, freezer | 4 kg × 0.5; 0.1 freezer × 10 kWh/day × 365.25 days × 0.2 | 10 × 4 × 0.5; 365.25 × 0.2 | 20 kg; 73.05 kg |
| Drug kits | 2 dispensing visits, 1 kit each, upfront waste 0.5 | 20 needed ÷ (1 − 0.5) | 40 kits, waste 50 % |
| Drug cost | $1000/kit (biologic), 2 shipments × $150 | 40 × 1000 + 300 | $40,300 |
| Drug carbon | 10 kg/kit; 2 kg/kit by van 0.6 over 500 km (+ WTT van 0.15) | 40 × 10; 40 t·km × 0.6 (+ × 0.15) | 400 + 24 + 6 kg |
| Trial management | 2 FTE, $120,000 and 1,000 kg per FTE-year | 2 × 1 year | $240,000; 2,000 kg |

Totals for this test design: **cost $334,240, carbon 3,749.7 kg CO2e (3,570.2 direct + 179.5 WTT), site
staff 62.33 h, patient time 80 h, drug waste 50 %, duration 12 months** (P10 = P50 = P90 because test
parameters are points).

Lever effects on the same test design (checked in `engine/tests/test_levers.py`):
- Remote monitoring 50 %: on-site trips 6 → 3, meetings_travel carbon 660 → 510 kg (incl. WTT), site staff hours
  62.33 → 56.33 (3 × 4 h support replaced by 3 × 2 h remote review); patient travel unchanged.
- V2 as a home visit: patient time 80 → 63.3 h, but cost rises (home nurse $300 vs reimbursement $50)
  — an honest trade-off; monitoring unchanged.
- On-demand supply (waste 0.2): kits 40 → 25, drug_supply cost $40,300 → $25,900.

## 9. Simplifications (stated, not hidden)

- Every enrolled patient completes every visit (dropout only in A3's forecast).
- One parameter value per draw for all patients / sites it covers (uncertainty of averages).
- CRA trips stay within the site's country (distance per country, not from geocoded bases); flights for
  CRA trips use the domestic factor.
- Monitoring frequency and −80 °C storage apply over the whole trial duration.
- Local-lab sample transport and telehealth energy are not modelled; procedure-level emissions only
  for codes that have an `ef.procedure.<code>` factor.
- Investigational product manufacture is excluded (published method); the `drug_supply` extension
  estimates kits and their shipping with wide, flagged ranges.

## 10. Engine API (for A5, A10, A3)

```python
from trialpilot_engine import compute_scenario, compare, compare_levers, drivers, missing_parameters
result = compute_scenario(design, levers, params, seed=7, draws=2000, forecast=None, supply=None)
deltas = compare(a, b)                                  # same process, same seed/draws
a, b, deltas = compare_levers(design, levers_a, levers_b, params, seed=7)
top = drivers(design, levers, params, "co2e_kg", top=5)  # [(parameter_id, variance share 0..1)]
missing_parameters(design, levers, params)              # ids the library lacks
```

Errors: `EngineInputError` (`.code`: `invalid_levers`, `invalid_design`, `design_incomplete`,
`invalid_request`, `invalid_metric`) → HTTP 422; `DrawsUnavailableError` → use `compare_levers`.
`forecast` / `supply` accept any object with the attributes of A3's `ForecastResult.duration_months`
and `SupplyResult.kits_produced / waste_share / shipments` (MetricRange).

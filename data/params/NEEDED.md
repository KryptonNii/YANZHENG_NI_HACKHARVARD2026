# Parameter ids — what the library will contain (A10 → A2, A3)

Status: **v0, 2026-10-16 21:20 ET.** Proposed ids so the engine can code against them now. Values land in
`data/params/*.yaml` as they are sourced (column "file"). **If A2/A3 publish different ids in their HANDOFF,
theirs win — tell the human and A10 renames.** Format and validation: `SCHEMA.md`.

Conventions
- Country-specific values: one id per country, suffix = lowercase ISO-3166 alpha-2 (`.gb`, `.es`, `.au`, `.us`, …),
  plus a `.global` fallback that always exists. Resolver: try `.<cc>`, then `.global`. (`region` field set to match.)
- Procedure-specific values: `time.site.procedure.<code>`, with `time.site.procedure.default` as fallback.
- Shares/probabilities are fractions 0..1 (unit `share`), not percent.
- Flights: DESNZ factors **with radiative-forcing uplift** everywhere (consistent with the BMJ Open 2024 method check).
- Carbon in `kg_co2e`, money in `usd` (non-USD sources converted; rate + year stated in the rationale), time in
  `hours` or `minutes` as the unit says.

## Emission factors (`emission_factors.yaml`, `grid_factors.yaml`)
| id | unit | meaning |
|---|---|---|
| `ef.travel.car.average_km` | kg_co2e/km | average car, unknown fuel, per vehicle-km |
| `ef.travel.bus.passenger_km` | kg_co2e/passenger_km | average local bus |
| `ef.travel.rail.passenger_km` | kg_co2e/passenger_km | national rail |
| `ef.travel.taxi.passenger_km` | kg_co2e/passenger_km | regular taxi |
| `ef.travel.flight.domestic.passenger_km` | kg_co2e/passenger_km | domestic flight, average passenger, with RF |
| `ef.travel.flight.short_haul.passenger_km` | kg_co2e/passenger_km | short-haul international, average passenger, with RF |
| `ef.travel.flight.long_haul.passenger_km` | kg_co2e/passenger_km | long-haul international, average passenger, with RF |
| `ef.freight.air.tonne_km` | kg_co2e/tonne_km | air freight, international, with RF |
| `ef.freight.van.tonne_km` | kg_co2e/tonne_km | average van (courier), per tonne-km |
| `ef.freight.road.tonne_km` | kg_co2e/tonne_km | average HGV, per tonne-km |
| `ef.electricity.grid.<cc>` | kg_co2e/kwh | grid electricity, `gb`, `es`, `au`, `us`, `de`, `fr`, `global` |
| `ef.dry_ice.kg` | kg_co2e/kg | dry ice used in frozen shipments |
| `ef.paper.kg` | kg_co2e/kg | paper (CRFs, printed documents) |
| `ef.drug_kit.unit` | kg_co2e/kit | **extension**: manufacture + packaging + cold chain per kit (assumption, wide) |

## Energy (`energy.yaml`)
| id | unit | meaning |
|---|---|---|
| `energy.freezer.minus80.kwh_per_day` | kwh/day | one −80 °C upright freezer |
| `energy.freezer.minus80.trial_share` | share | fraction of one freezer occupied by a trial's samples (assumption) |

## Distances and travel (`travel.yaml`)
| id | unit | meaning |
|---|---|---|
| `dist.patient.roundtrip_km.<cc>` | km/visit | patient home ↔ site round trip |
| `rate.patient.mode_share.car.<cc>` | share | share of patient trips by car (rest = public transport) |
| `rate.patient.mode_share.rail.<cc>` | share | share of the public-transport trips by rail (rest = bus) |
| `time.patient.travel_speed_kmh.<cc>` | km/hour | door-to-door average speed (travel hours = km / speed) |
| `time.patient.visit_at_site` | hours/visit | patient time at site per visit (waiting + procedures), default |
| `dist.monitoring.roundtrip_km.<cc>` | km/trip | CRA base ↔ site round trip, same country |
| `dist.monitoring.flight_threshold_km` | km | one-way distance above which a monitoring trip is flown |
| `dist.sample.to_central_lab_km.<cc>` | km/shipment | site → central lab, road |
| `dist.investigator_meeting.roundtrip_km` | km/attendee | investigator meeting travel |

## Monitoring, site and patient time (`site_time.yaml`)
| id | unit | meaning |
|---|---|---|
| `rate.monitoring.onsite_visits_per_site_month` | visits/site/month | on-site monitoring frequency (100% on-site) |
| `time.monitoring.onsite_visit_days` | days/visit | CRA days per on-site visit incl. travel |
| `time.monitoring.remote_visit_days` | days/visit | CRA days per remote monitoring visit |
| `time.site.monitoring_visit_support` | hours/visit | site staff hours supporting an on-site monitoring visit |
| `time.site.remote_monitoring_review` | hours/visit | site staff hours per remote monitoring visit |
| `time.site.procedure.<code>` | minutes/procedure | codes: `blood_draw`, `pk_sample`, `ecg`, `vital_signs`, `physical_exam`, `questionnaire`, `informed_consent`, `drug_dispensing`, `urine_sample`, `mri`, `ct_scan`, `x_ray`, `mammogram`, `echocardiogram`, `biopsy`, `default` |
| `time.site.visit_admin` | minutes/visit | scheduling + documentation per patient visit |
| `rate.queries.per_patient` | queries/patient | data queries raised per patient |
| `time.site.query_resolution` | minutes/query | site time to resolve one query |

## Costs (`costs.yaml`)
| id | unit | meaning |
|---|---|---|
| `cost.monitoring.cra_day_rate` | usd/day | fully loaded CRA day |
| `cost.monitoring.travel_expenses_per_trip` | usd/trip | travel + subsistence for one on-site monitoring trip |
| `cost.home_nurse.visit` | usd/visit | one home-nursing visit |
| `cost.telehealth.visit` | usd/visit | one telehealth visit |
| `cost.courier.shipment.ambient` / `.refrigerated` / `.frozen` | usd/shipment | one sample shipment |
| `cost.drug.kit.biologic` / `cost.drug.kit.small_molecule` | usd/kit | one patient kit |
| `cost.site_staff.hour` | usd/hour | site research staff (coordinator/nurse), loaded |
| `cost.patient.reimbursement_visit` | usd/visit | patient travel reimbursement / stipend |
| `cost.lab.local_harmonisation_per_site` | usd/site | harmonising a local lab with the central lab |
| `cost.investigator_meeting.per_attendee` | usd/attendee | travel + venue per attendee |

## Drug supply and samples (`supply.yaml`)
| id | unit | meaning |
|---|---|---|
| `supply.waste_share.upfront` | share | share of manufactured kits never dispensed, upfront stocking (industry-reported) |
| `supply.overage_share.upfront` | share | overage stocked at activation |
| `supply.kits_per_dispensing_visit` | kits/visit | kits dispensed per dispensing visit |
| `supply.shelf_life_months` | months | kit shelf life |
| `supply.on_demand.cover_weeks` | weeks | on-demand resupply covers next k weeks |
| `supply.stockout_warning_threshold` | share | warn if stockout probability above this |
| `supply.kit_shipping_weight_kg` | kg/kit | shipped weight per kit incl. packaging |
| `supply.sample.shipment_weight_kg.<temp>` | kg/shipment | `ambient`, `refrigerated`, `frozen` (incl. packaging) |
| `supply.sample.dry_ice_kg_per_shipment` | kg/shipment | dry ice per frozen shipment |
| `supply.sample.samples_per_shipment` | samples/shipment | batching of samples per shipment |

## Forecast (A3) (`forecast.yaml`)
| id | unit | meaning |
|---|---|---|
| `site.activation_months` | months | site activation time from study start |
| `site.enrollment_rate_per_month` | patients/site/month | mean recruitment rate per active site |
| `site.enrollment_rate_shape` | dimensionless | gamma shape α (between-site heterogeneity) |
| `patient.dropout_rate` | share | patients who drop out |
| `trial.closeout_months` | months | last patient last visit → database lock |

## Simple module factors (`modules.yaml`) — refined after reading the paper's appendices C/D
| id | unit | meaning |
|---|---|---|
| `ef.trial_management.per_fte_year` | kg_co2e/fte_year | coordinating-unit energy + commuting per FTE-year |
| `rate.trial_management.fte` | fte | coordinating-unit staff on the trial |
| `ef.setup.per_site` | kg_co2e/site | site set-up (SIF delivery, initiation visit travel excluded) |
| `ef.data_collection.per_patient_year` | kg_co2e/patient_year | EDC hosting/data exchange |
| `ef.supplies_equipment.per_patient` | kg_co2e/patient | trial-specific supplies |
| `ef.laboratory.per_sample` | kg_co2e/sample | analysis of one sample |
| `ef.closeout.archiving_per_box_year` | kg_co2e/box_year | archive storage |

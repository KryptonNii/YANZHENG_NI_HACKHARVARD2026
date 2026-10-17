# Parameter ids — engine `PARAMETER_CATALOG`

Status: **aligned to `engine/trialpilot_engine/provenance.py` `PARAMETER_CATALOG`, 2026-10-16.** This table is that
catalog: same ids, same order, same unit, same meaning. Values live in `data/params/*.yaml` (column "file").
Narrative use of each id is `docs/model.md` §7. Format and validation: `SCHEMA.md`.

Placeholders, as in the catalog: `<cc>` = lowercase ISO 3166 alpha-2 or `global` (the `.global` id is the fallback);
`<code>` = procedure code or `default`; `<temp>` = `ambient` | `refrigerated` | `frozen`; `<drug_type>` =
`biologic` | `small_molecule` | `default`; `<strategy>` = `upfront` | `on_demand`.

`ef.procedure.<code>` is optional per code and has no `.default`. The YAML library also holds factors the catalog
does not read (forecast rates, unused WTT variants, hotels, LCCT building factors). Those stay in the YAML files and are
not catalog ids, so they are not listed here.

| id | unit | meaning | file |
|---|---|---|---|
| `dist.patient.roundtrip_km.<cc>` | `km/visit` | patient home to site round trip per on-site visit | travel.yaml |
| `rate.patient.mode_share.car.<cc>` | `share` | share of patient km travelled by car | travel.yaml |
| `rate.patient.mode_share.rail.<cc>` | `share` | share of the non-car km by rail (rest by bus) | travel.yaml |
| `time.patient.travel_speed_kmh.<cc>` | `km/hour` | door-to-door average patient travel speed | travel.yaml |
| `time.patient.visit_at_site` | `hours/visit` | patient time at site per visit | travel.yaml |
| `time.patient.home_visit` | `hours/visit` | patient time per home-nursing visit | site_time.yaml |
| `time.patient.remote_visit` | `hours/visit` | patient time per telehealth visit | site_time.yaml |
| `ef.travel.car.average_km` | `kg_co2e/km` | average car per vehicle-km | emission_factors.yaml |
| `ef.travel.bus.passenger_km` | `kg_co2e/passenger_km` | average local bus | emission_factors.yaml |
| `ef.travel.rail.passenger_km` | `kg_co2e/passenger_km` | national rail | emission_factors.yaml |
| `cost.patient.reimbursement_visit` | `usd/visit` | patient travel reimbursement per on-site visit | costs.yaml |
| `cost.home_nurse.visit` | `usd/visit` | one home-nursing visit | costs.yaml |
| `dist.home_nurse.roundtrip_km` | `km/visit` | home nurse round trip by car per home visit | travel.yaml |
| `cost.telehealth.visit` | `usd/visit` | one telehealth visit | costs.yaml |
| `ef.procedure.<code>` | `kg_co2e/procedure` | optional per-procedure factor (e.g. imaging energy) | lcct_method.yaml |
| `time.site.visit_admin` | `minutes/visit` | scheduling + documentation per patient visit | site_time.yaml |
| `time.site.procedure.<code>` | `minutes/procedure` | site staff minutes per procedure | site_time.yaml |
| `rate.site.minutes_factor.home_visit` | `share` | share of a visit's procedure minutes still borne by site staff when done at home | site_time.yaml |
| `rate.site.minutes_factor.remote_visit` | `share` | share of a visit's procedure minutes still borne by site staff when done by telehealth | site_time.yaml |
| `time.site.monitoring_visit_support` | `hours/visit` | site staff hours per on-site monitoring visit | site_time.yaml |
| `time.site.remote_monitoring_review` | `hours/visit` | site staff hours per remote monitoring visit | site_time.yaml |
| `rate.queries.per_patient` | `queries/patient` | data queries raised per patient | site_time.yaml |
| `time.site.query_resolution` | `minutes/query` | site time to resolve one query | site_time.yaml |
| `cost.site_staff.hour` | `usd/hour` | loaded cost of one site research staff hour | costs.yaml |
| `rate.monitoring.onsite_visits_per_site_month` | `visits/site/month` | monitoring visit frequency (all on-site at remote share 0) | site_time.yaml |
| `dist.monitoring.roundtrip_km.<cc>` | `km/trip` | CRA base to site round trip, same country | travel.yaml |
| `dist.monitoring.flight_threshold_km` | `km` | one-way distance above which a trip is flown | travel.yaml |
| `ef.travel.flight.domestic.passenger_km` | `kg_co2e/passenger_km` | domestic flight, with RF | emission_factors.yaml |
| `ef.travel.flight.short_haul.passenger_km` | `kg_co2e/passenger_km` | short-haul flight, with RF | emission_factors.yaml |
| `ef.travel.flight.long_haul.passenger_km` | `kg_co2e/passenger_km` | long-haul flight, with RF | emission_factors.yaml |
| `dist.flight.short_haul_max_km` | `km` | one-way distance up to which a flight is short-haul | travel.yaml |
| `cost.monitoring.cra_day_rate` | `usd/day` | fully loaded CRA day | costs.yaml |
| `time.monitoring.onsite_visit_days` | `days/visit` | CRA days per on-site visit incl. travel | site_time.yaml |
| `time.monitoring.remote_visit_days` | `days/visit` | CRA days per remote monitoring visit | site_time.yaml |
| `cost.monitoring.travel_expenses_per_trip` | `usd/trip` | travel + subsistence per on-site trip | costs.yaml |
| `rate.investigator_meeting.attendees_per_site` | `people/site` | kickoff meeting attendees per site | travel.yaml |
| `dist.investigator_meeting.roundtrip_km` | `km/attendee` | kickoff meeting round trip | travel.yaml |
| `cost.investigator_meeting.per_attendee` | `usd/attendee` | travel + venue per attendee | costs.yaml |
| `ef.setup.per_site` | `kg_co2e/site` | site set-up excluding initiation-visit travel | modules.yaml |
| `cost.setup.per_site` | `usd/site` | site start-up (contracts, ethics, initiation) | costs.yaml |
| `cost.closeout.per_site` | `usd/site` | site close-out | costs.yaml |
| `rate.closeout.archive_boxes_per_site` | `boxes/site` | archive boxes per site | modules.yaml |
| `time.closeout.archive_years` | `years` | archive retention period | lcct_method.yaml |
| `ef.closeout.archiving_per_box_year` | `kg_co2e/box_year` | archive storage | modules.yaml |
| `rate.trial_management.fte` | `fte` | coordinating-unit / sponsor staff on the trial | lcct_method.yaml |
| `ef.trial_management.per_fte_year` | `kg_co2e/fte_year` | office energy + commuting per FTE-year | modules.yaml |
| `cost.trial_management.per_fte_year` | `usd/fte_year` | loaded cost per FTE-year | costs.yaml |
| `ef.data_collection.per_patient_year` | `kg_co2e/patient_year` | EDC hosting / data exchange | modules.yaml |
| `cost.data_collection.per_patient` | `usd/patient` | EDC + data management per patient | costs.yaml |
| `ef.supplies_equipment.per_patient` | `kg_co2e/patient` | trial-specific supplies | modules.yaml |
| `cost.supplies_equipment.per_patient` | `usd/patient` | trial-specific supplies | costs.yaml |
| `supply.sample.samples_per_shipment` | `samples/shipment` | samples batched per shipment | supply.yaml |
| `supply.sample.shipment_weight_kg.<temp>` | `kg/shipment` | shipped weight incl. packaging | supply.yaml |
| `dist.sample.to_central_lab_km.<cc>` | `km/shipment` | site to central lab, one way | supply.yaml |
| `ef.freight.van.tonne_km` | `kg_co2e/tonne_km` | road courier (van) | emission_factors.yaml |
| `ef.freight.air.tonne_km` | `kg_co2e/tonne_km` | air freight, with RF | emission_factors.yaml |
| `supply.sample.dry_ice_kg_per_shipment` | `kg/shipment` | dry ice per frozen shipment | supply.yaml |
| `ef.dry_ice.kg` | `kg_co2e/kg` | dry ice | emission_factors.yaml |
| `cost.courier.shipment.<temp>` | `usd/shipment` | one sample shipment | costs.yaml |
| `energy.freezer.minus80.kwh_per_day` | `kwh/day` | one -80 C upright freezer | energy.yaml |
| `energy.freezer.minus80.trial_share` | `share` | share of one freezer used by the trial, per site | supply.yaml |
| `ef.electricity.grid.<cc>` | `kg_co2e/kwh` | grid electricity | grid_factors.yaml (`.gb` in emission_factors.yaml) |
| `cost.lab.local_harmonisation_per_site` | `usd/site` | harmonising a local lab with the central lab | costs.yaml |
| `ef.laboratory.per_sample` | `kg_co2e/sample` | analysis of one sample | modules.yaml |
| `cost.lab.central_per_sample` | `usd/sample` | central lab analysis per sample | costs.yaml |
| `cost.lab.local_per_sample` | `usd/sample` | local lab analysis per sample | costs.yaml |
| `supply.kits_per_dispensing_visit` | `kits/visit` | kits dispensed per dispensing visit | supply.yaml |
| `supply.waste_share.<strategy>` | `share` | share of manufactured kits never dispensed | supply.yaml |
| `supply.shipments_per_site.<strategy>` | `shipments/site` | depot to site shipments per site | supply.yaml |
| `cost.drug.kit.<drug_type>` | `usd/kit` | one patient kit | costs.yaml |
| `ef.drug_kit.unit` | `kg_co2e/kit` | manufacture + packaging (+ cold storage) per kit, excl. transport | supply.yaml |
| `supply.kit_shipping_weight_kg` | `kg/kit` | shipped weight per kit incl. packaging | supply.yaml |
| `dist.drug.depot_to_site_km` | `km` | depot to site, one way | supply.yaml |
| `cost.drug.shipment` | `usd/shipment` | one depot to site shipment | costs.yaml |
| `ef.wtt.travel.car.average_km` | `kg_co2e/km` | well-to-tank, average car per vehicle-km | emission_factors.yaml |
| `ef.wtt.travel.bus.passenger_km` | `kg_co2e/passenger_km` | well-to-tank, average local bus | emission_factors.yaml |
| `ef.wtt.travel.rail.passenger_km` | `kg_co2e/passenger_km` | well-to-tank, national rail | emission_factors.yaml |
| `ef.wtt.travel.flight.domestic.passenger_km` | `kg_co2e/passenger_km` | well-to-tank, domestic flight | emission_factors.yaml |
| `ef.wtt.travel.flight.short_haul.passenger_km` | `kg_co2e/passenger_km` | well-to-tank, short-haul flight | emission_factors.yaml |
| `ef.wtt.travel.flight.long_haul.passenger_km` | `kg_co2e/passenger_km` | well-to-tank, long-haul flight | emission_factors.yaml |
| `ef.wtt.freight.van.tonne_km` | `kg_co2e/tonne_km` | well-to-tank, road courier (van) | emission_factors.yaml |
| `ef.wtt.freight.air.long_haul.tonne_km` | `kg_co2e/tonne_km` | well-to-tank, air freight (twin of `ef.freight.air.tonne_km`: international = long-haul) | emission_factors.yaml |
| `assume.design.visits_per_patient` | `visits` | visits assumed when the design has no schedule | modules.yaml |
| `assume.design.patients_per_site` | `patients/site` | used to assume sites when none are listed | modules.yaml |

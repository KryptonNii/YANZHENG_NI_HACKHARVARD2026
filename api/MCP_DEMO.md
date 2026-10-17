# TrialPilot MCP server - recorded session

Recorded 2026-10-17 02:15 UTC by `api/scripts/mcp_demo.py` (git `144338e`): real stdio transport, real A2 engine + A3 forecast/supply, A10 parameter library, DEMO_OFFLINE=1, temporary database. The two saved scenarios were created by the script as the demo author (the MCP server cannot save). Ranges are shown as `P10 / P50 / P90 unit` (k = thousand, M = million); long lists are cut; nothing else is edited.

### tools/list

- `list_designs` (read-only: True) - List stored trial designs (latest version of each): id, title, registry id, size.
- `list_scenarios` (read-only: True) - List saved scenarios (newest first), optionally for one design: id, name, version,
- `compute_scenario` (read-only: True) - Compute cost, site staff hours, patient travel hours, CO2e, duration and drug waste
- `compare_scenarios` (read-only: True) - Compare two saved scenarios on the same design version: per-draw deltas B - A
- `explain_metric` (read-only: True) - Explain one metric: its range, the formulas that produce it (with inputs, parameter
- `get_parameter` (read-only: True) - One parameter from the library: low/mid/high values, unit, source (title, URL,

### tools/call `list_designs`

```json
{}
```

Result (2988 ms round trip):

```json
{
 "designs": [
  {
   "id": "dc60ef19-dfd2-5aed-81cc-fae3dda590dd",
   "version": 1,
   "title": "A Phase 3 Clinical Trial to Evaluate the Safety and Efficacy of Ensifentrine in Patients With COPD",
   "registry_id": "NCT04535986",
   "phase": "Phase 3",
   "source": "ctgov",
   "enrollment_target": 763,
   "duration_months": 26.1,
   "site_count": 122,
   "visit_count": 7,
   "countries": [
    "Bulgaria",
    "Czechia",
    "Germany",
    "Greece",
    "... 8 more"
   ],
   "missing_fields": [
    "visits",
    "sites.expected_enrollment"
   ]
  },
  {
   "id": "3b11a429-d73c-5eeb-b756-73f7c52c8bf9",
   "version": 1,
   "title": "NOTUS: Pivotal Study to Assess the Efficacy, Safety and Tolerability of Dupilumab in Patients With Moderate to Severe COPD With Type 2 Inflammation",
   "registry_id": "NCT04456673",
   "phase": "Phase 3",
   "source": "ctgov",
   "enrollment_target": 935,
   "duration_months": 46.7,
   "site_count": 334,
   "visit_count": 12,
   "countries": [
    "Argentina",
    "Australia",
    "Belgium",
    "Brazil",
    "... 25 more"
   ],
   "missing_fields": [
    "visits",
    "sites.expected_enrollment"
   ]
  },
  {
   "id": "847abfde-88ce-5625-9c63-ffdd673e5ee5",
   "version": 1,
   "title": "PHOTON: Study of a High-Dose Aflibercept in Participants With Diabetic Eye Disease",
   "registry_id": "NCT04429503",
   "phase": "Phase 2/3",
   "source": "ctgov",
   "enrollment_target": 660,
   "duration_months": 47.6,
   "site_count": 138,
   "visit_count": 18,
   "countries": [
    "Canada",
    "Czechia",
    "Germany",
    "Hungary",
    "... 4 more"
   ],
   "missing_fields": [
    "visits",
    "sites.expected_enrollment"
   ]
  },
  {
   "id": "41774a6b-4338-595f-bee7-493e4a5e62b6",
   "version": 1,
   "title": "BOREAS: Pivotal Study to Assess the Efficacy, Safety and Tolerability of Dupilumab in Patients With Moderate-to-severe COPD With Type 2 Inflammation",
   "registry_id": "NCT03930732",
   "phase": "Phase 3",
   "source": "ctgov",
   "enrollment_target": 939,
   "duration_months": 48.6,
   "site_count": 275,
   "visit_count": 11,
   "countries": [
    "Argentina",
    "Bulgaria",
    "Canada",
    "Chile",
    "... 20 more"
   ],
   "missing_fields": [
    "visits",
    "sites.expected_enrollment"
   ]
  }
 ]
}
```

### tools/call `compute_scenario`

```json
{
 "design_id": "41774a6b-4338-595f-bee7-493e4a5e62b6"
}
```

Result (1073 ms round trip):

```json
{
 "design_id": "41774a6b-4338-595f-bee7-493e4a5e62b6",
 "levers": {
  "remote_monitoring_share": 0.0,
  "home_visit_numbers": [],
  "remote_visit_numbers": [],
  "local_lab_share": 0.0,
  "drug_supply_strategy": "upfront",
  "removed_procedures": [],
  "excluded_site_ids": []
 },
 "metrics": {
  "cost_usd": "132.64M / 222.19M / 404.30M usd",
  "site_staff_hours": "106.00k / 142.24k / 186.05k hours",
  "patient_travel_hours": "21.66k / 26.71k / 33.30k hours",
  "co2e_kg": "765.26k / 1.06M / 1.47M kg_co2e",
  "duration_months": "26.0 / 27.2 / 29.2 months",
  "drug_waste_share": "57.0 / 65.7 / 73.1 percent"
 },
 "modules": [
  {
   "module": "setup",
   "cost_usd": "2.97M / 5.29M / 8.41M usd",
   "co2e_kg": "20.82k / 30.63k / 41.43k kg_co2e"
  },
  {
   "module": "trial_management",
   "cost_usd": "655.50k / 1.51M / 2.99M usd",
   "co2e_kg": "6.37k / 14.55k / 27.63k kg_co2e"
  },
  {
   "module": "meetings_travel",
   "cost_usd": "12.71M / 21.44M / 35.79M usd",
   "co2e_kg": "439.95k / 716.20k / 1.09M kg_co2e"
  },
  {
   "module": "intervention",
   "cost_usd": "0 / 0 / 0 usd",
   "co2e_kg": "0 / 0 / 0 kg_co2e"
  },
  "... 7 more"
 ],
 "warnings": [
  "10 sample-shipping procedures (per patient) have no storage temperature: shipped as ambient (understates frozen shipping and dry ice if they are frozen).",
  "Module 'intervention' is excluded (drug manufacture is excluded in the published method); the 'drug_supply' extension estimates kits separately and is included in the totals."
 ],
 "parameter_set_version": "1249d0f0eed8",
 "seed": 7,
 "draws": 2000,
 "compute_ms": "1009.6",
 "cache": "miss",
 "note": "Ranges are P10/P50/P90 over the Monte Carlo draws (triangular low/mid/high per parameter); null means unknown, see warnings. Parameter sources: get_parameter."
}
```

### tools/call `compute_scenario`

```json
{
 "design_id": "41774a6b-4338-595f-bee7-493e4a5e62b6",
 "levers": {
  "remote_monitoring_share": 0.5,
  "drug_supply_strategy": "on_demand"
 }
}
```

Result (850 ms round trip):

```json
{
 "design_id": "41774a6b-4338-595f-bee7-493e4a5e62b6",
 "levers": {
  "remote_monitoring_share": 0.5,
  "home_visit_numbers": [],
  "remote_visit_numbers": [],
  "local_lab_share": 0.0,
  "drug_supply_strategy": "on_demand",
  "removed_procedures": [],
  "excluded_site_ids": []
 },
 "metrics": {
  "cost_usd": "78.24M / 114.10M / 170.23M usd",
  "site_staff_hours": "99.31k / 129.90k / 169.92k hours",
  "patient_travel_hours": "21.66k / 26.71k / 33.30k hours",
  "co2e_kg": "530.08k / 745.32k / 1.06M kg_co2e",
  "duration_months": "26.0 / 27.2 / 29.2 months",
  "drug_waste_share": "9.85 / 14.9 / 16.1 percent"
 },
 "modules": [
  {
   "module": "setup",
   "cost_usd": "2.97M / 5.29M / 8.41M usd",
   "co2e_kg": "20.82k / 30.63k / 41.43k kg_co2e"
  },
  {
   "module": "trial_management",
   "cost_usd": "655.50k / 1.51M / 2.99M usd",
   "co2e_kg": "6.37k / 14.55k / 27.63k kg_co2e"
  },
  {
   "module": "meetings_travel",
   "cost_usd": "10.49M / 17.55M / 29.10M usd",
   "co2e_kg": "288.95k / 489.61k / 798.51k kg_co2e"
  },
  {
   "module": "intervention",
   "cost_usd": "0 / 0 / 0 usd",
   "co2e_kg": "0 / 0 / 0 kg_co2e"
  },
  "... 7 more"
 ],
 "warnings": [
  "10 sample-shipping procedures (per patient) have no storage temperature: shipped as ambient (understates frozen shipping and dry ice if they are frozen).",
  "Module 'intervention' is excluded (drug manufacture is excluded in the published method); the 'drug_supply' extension estimates kits separately and is included in the totals."
 ],
 "parameter_set_version": "1249d0f0eed8",
 "seed": 7,
 "draws": 2000,
 "compute_ms": "830.1",
 "cache": "miss",
 "note": "Ranges are P10/P50/P90 over the Monte Carlo draws (triangular low/mid/high per parameter); null means unknown, see warnings. Parameter sources: get_parameter."
}
```

### tools/call `compute_scenario`

```json
{
 "design_id": "41774a6b-4338-595f-bee7-493e4a5e62b6",
 "levers": {
  "remote_monitoring": 0.5
 }
}
```

**is_error: true** (13 ms)

```text
Error executing tool compute_scenario: validation_error (HTTP 422): Invalid request: levers.remote_monitoring: Extra inputs are not permitted Details: {'errors': [{'loc': ['body', 'levers', 'remote_monitoring'], 'msg': 'Extra inputs are not permitted', 'type': 'extra_forbidden'}], 'request_id': 'bc4b6598006541d5'}
```

### tools/call `explain_metric`

```json
{
 "metric": "co2e_kg",
 "design_id": "41774a6b-4338-595f-bee7-493e4a5e62b6",
 "top": 3
}
```

Result (161 ms round trip):

```json
{
 "metric": "co2e_kg",
 "range": "765.26k / 1.06M / 1.47M kg_co2e",
 "formulas": [
  {
   "module": "meetings_travel",
   "formula_id": "carbon.monitoring_trips.v1",
   "description": "on-site monitoring visits (sites × visits/site/month × months × (1 − remote share)) × round-trip km × (car factor, or domestic flight factor above the flight threshold)",
   "contribution": "226.53k / 416.43k / 706.28k kg_co2e",
   "inputs": {
    "active_sites": 275.0,
    "remote_monitoring_share": 0.0,
    "duration_months_p50": 27.2
   },
   "parameter_ids": [
    "rate.monitoring.onsite_visits_per_site_month",
    "dist.monitoring.roundtrip_km.global",
    "dist.monitoring.flight_threshold_km",
    "ef.travel.car.average_km"
   ],
   "assumptions": [
    "Remote monitoring visits have no travel emissions.",
    "No country-specific `dist.monitoring.roundtrip_km.ar` in the library; used `dist.monitoring.roundtrip_km.global`.",
    "No country-specific `dist.monitoring.roundtrip_km.bg` in the library; used `dist.monitoring.roundtrip_km.global`.",
    "No country-specific `dist.monitoring.roundtrip_km.ca` in the library; used `dist.monitoring.roundtrip_km.global`.",
    "... 22 more"
   ]
  },
  {
   "module": "meetings_travel",
   "formula_id": "carbon.investigator_meeting.v1",
   "description": "one kickoff meeting: sites × attendees per site × round-trip km × (car, short-haul or long-haul flight factor by one-way distance)",
   "contribution": "101.59k / 256.11k / 559.14k kg_co2e",
   "inputs": {
    "active_sites": 275.0,
    "meetings": 1.0
   },
   "parameter_ids": [
    "rate.investigator_meeting.attendees_per_site",
    "dist.investigator_meeting.roundtrip_km",
    "dist.monitoring.flight_threshold_km",
    "ef.travel.car.average_km",
    "... 3 more"
   ],
   "assumptions": [
    "Site expected enrollment not given: patients split equally across sites."
   ]
  },
  {
   "module": "drug_supply",
   "formula_id": "carbon.drug_kits.v1",
   "description": "kits made (kits needed ÷ (1 − waste share)) × factor per kit",
   "contribution": "51.69k / 120.70k / 257.25k kg_co2e",
   "inputs": {
    "kits_produced_p50": 25133.0,
    "waste_share_p50": 65.9,
    "shipments_p50": 451.0,
    "source": "A3 drug supply simulation"
   },
   "parameter_ids": [
    "ef.drug_kit.unit"
   ],
   "assumptions": [
    "drug_supply is a TrialPilot extension beyond the published method.",
    "Site expected enrollment not given: patients split equally across sites."
   ]
  },
  {
   "module": "patient_assessments",
   "formula_id": "carbon.patient_travel.v1",
   "description": "patients × on-site visits × round-trip km × (car share × car factor + rest × (rail share × rail factor + bus share × bus factor)), per country",
   "contribution": "45.92k / 64.74k / 92.25k kg_co2e",
   "inputs": {
    "on_site_visits_per_patient": 11.0,
    "patients.ar": 41.0,
    "patients.bg": 27.3,
    "patients.ca": 68.3,
    "patients.cl": 27.3,
    "patients.cn": 126.3,
    "patients.cz": 27.3,
    "patients.de": 23.9,
    "patients.dk": 23.9,
    "patients.es": 30.7,
    "patients.fi": 6.829,
    "patients.hu": 37.6,
    "patients.il": 23.9,
    "patients.it": 17.1,
    "patients.jp": 75.1,
    "patients.kr": 20.5,
    "patients.mx": 23.9,
    "patients.pl": 30.7,
    "patients.ro": 27.3,
    "patients.ru": 30.7,
    "patients.se": 6.829,
    "patients.sk": 17.1,
    "patients.turkey_t_rkiye": 23.9,
    "patients.ua": 27.3,
    "patients.us": 174.1
   },
   "parameter_ids": [
    "rate.patient.mode_share.car.global",
    "rate.patient.mode_share.rail.global",
    "ef.travel.rail.passenger_km",
    "ef.travel.bus.passenger_km",
    "... 8 more"
   ],
   "assumptions": [
    "One patient per car trip (vehicle-km factor); companions add no car km.",
    "No country-specific `rate.patient.mode_share.car.ar` in the library; used `rate.patient.mode_share.car.global`.",
    "No country-specific `rate.patient.mode_share.rail.ar` in the library; used `rate.patient.mode_share.rail.global`.",
    "No country-specific `dist.patient.roundtrip_km.ar` in the library; used `dist.patient.roundtrip_km.global`.",
    "... 64 more"
   ]
  },
  "... 12 more"
 ],
 "drivers": [
  {
   "parameter_id": "dist.investigator_meeting.roundtrip_km",
   "share": 0.336,
   "label": "Investigator meeting round trip per attendee",
   "unit": "km/attendee",
   "value_low": 200.0,
   "value_mid": 1500.0,
   "value_high": 10000.0,
   "source_title": null,
   "source_url": null,
   "source_year": null,
   "assumption": true
  },
  {
   "parameter_id": "dist.monitoring.roundtrip_km.global",
   "share": 0.215,
   "label": "CRA base to site round trip, same country (fallback)",
   "unit": "km/trip",
   "value_low": 200.0,
   "value_mid": 500.0,
   "value_high": 1000.0,
   "source_title": null,
   "source_url": null,
   "source_year": null,
   "assumption": true
  },
  {
   "parameter_id": "rate.monitoring.onsite_visits_per_site_month",
   "share": 0.182,
   "label": "On-site monitoring visits per site per month (fully on-site monitoring)",
   "unit": "visits/site/month",
   "value_low": 0.22,
   "value_mid": 0.54,
   "value_high": 1.09,
   "source_title": "US FDA. Oversight of Clinical Investigations - A Risk-Based Approach to Monitoring (Guidance for Industry), Aug 2013, p.3: 'on-site monitoring visits at approximately 4- to 8-week intervals'",
   "source_url": "https://www.fda.gov/media/116754/download",
   "source_year": 2013,
   "assumption": false
  }
 ],
 "drivers_error": null,
 "parameter_set_version": "1249d0f0eed8",
 "warnings": [
  "10 sample-shipping procedures (per patient) have no storage temperature: shipped as ambient (understates frozen shipping and dry ice if they are frozen).",
  "Module 'intervention' is excluded (drug manufacture is excluded in the published method); the 'drug_supply' extension estimates kits separately and is included in the totals."
 ],
 "note": "drivers.share = the parameter's share of this metric's variance (engine definition). Ranges are P10/P50/P90 over the Monte Carlo draws (triangular low/mid/high per parameter); null means unknown, see warnings. Parameter sources: get_parameter."
}
```

### tools/call `compare_scenarios`

```json
{
 "a_id": "44c5a7cc-1acf-49c3-b057-22b7d550d408",
 "b_id": "6ac315dc-e4ac-4a51-8547-52c311089c23"
}
```

Result (460 ms round trip):

```json
{
 "a_id": "44c5a7cc-1acf-49c3-b057-22b7d550d408",
 "b_id": "6ac315dc-e4ac-4a51-8547-52c311089c23",
 "deltas": {
  "cost_usd": "-235.29M / -108.22M / -52.41M usd | decrease (P90 of B - A below 0)",
  "site_staff_hours": "-23.17k / -10.85k / -1.05k hours | decrease (P90 of B - A below 0)",
  "patient_travel_hours": "0 / 0 / 0 hours | no change (B - A is 0 from P10 to P90)",
  "co2e_kg": "-459.76k / -301.05k / -185.77k kg_co2e | decrease (P90 of B - A below 0)",
  "duration_months": "0 / 0 / 0 months | no change (B - A is 0 from P10 to P90)",
  "drug_waste_share": "-57.1 / -50.8 / -47.1 percent | decrease (P90 of B - A below 0)"
 },
 "module_deltas": {
  "cost_usd.setup": "0 / 0 / 0 usd",
  "co2e_kg.setup": "0 / 0 / 0 kg_co2e",
  "cost_usd.trial_management": "0 / 0 / 0 usd",
  "co2e_kg.trial_management": "0 / 0 / 0 kg_co2e",
  "cost_usd.meetings_travel": "-8.51M / -3.80M / -507.63k usd",
  "co2e_kg.meetings_travel": "-353.14k / -208.21k / -113.27k kg_co2e",
  "cost_usd.intervention": "0 / 0 / 0 usd",
  "co2e_kg.intervention": "0 / 0 / 0 kg_co2e",
  "cost_usd.data_collection": "0 / 0 / 0 usd",
  "co2e_kg.data_collection": "0 / 0 / 0 kg_co2e",
  "cost_usd.supplies_equipment": "0 / 0 / 0 usd",
  "co2e_kg.supplies_equipment": "0 / 0 / 0 kg_co2e",
  "cost_usd.patient_assessments": "0 / 0 / 0 usd",
  "co2e_kg.patient_assessments": "0 / 0 / 0 kg_co2e",
  "cost_usd.samples": "0 / 0 / 0 usd",
  "co2e_kg.samples": "0 / 0 / 0 kg_co2e",
  "cost_usd.laboratory": "0 / 0 / 0 usd",
  "co2e_kg.laboratory": "0 / 0 / 0 kg_co2e",
  "cost_usd.closeout": "0 / 0 / 0 usd",
  "co2e_kg.closeout": "0 / 0 / 0 kg_co2e",
  "cost_usd.drug_supply": "-230.28M / -104.40M / -48.69M usd",
  "co2e_kg.drug_supply": "-177.89k / -78.42k / -34.79k kg_co2e"
 },
 "a_metrics": {
  "cost_usd": "132.64M / 222.19M / 404.30M usd",
  "site_staff_hours": "106.00k / 142.24k / 186.05k hours",
  "patient_travel_hours": "21.66k / 26.71k / 33.30k hours",
  "co2e_kg": "765.26k / 1.06M / 1.47M kg_co2e",
  "duration_months": "26.0 / 27.2 / 29.2 months",
  "drug_waste_share": "57.0 / 65.7 / 73.1 percent"
 },
 "b_metrics": {
  "cost_usd": "78.24M / 114.10M / 170.23M usd",
  "site_staff_hours": "99.31k / 129.90k / 169.92k hours",
  "patient_travel_hours": "21.66k / 26.71k / 33.30k hours",
  "co2e_kg": "530.08k / 745.32k / 1.06M kg_co2e",
  "duration_months": "26.0 / 27.2 / 29.2 months",
  "drug_waste_share": "9.85 / 14.9 / 16.1 percent"
 },
 "same_parameter_set": true,
 "seed": 7,
 "draws": 2000,
 "parameter_set_version": "1249d0f0eed8",
 "warnings": [],
 "note": "Deltas are B - A computed per Monte Carlo draw, then P10/P50/P90."
}
```

### tools/call `get_parameter`

```json
{"parameter_id": "dist.investigator_meeting.roundtrip_km"}
```

Result:

```json
{
 "id": "dist.investigator_meeting.roundtrip_km",
 "label": "Investigator meeting round trip per attendee",
 "value_low": 200.0,
 "value_mid": 1500.0,
 "value_high": 10000.0,
 "unit": "km/attendee",
 "source_title": null,
 "source_url": null,
 "source_year": null,
 "assumption": true,
 "rationale": "No source. National meetings ~hundreds of km; international meetings ~thousands. Wide assumption.",
 "version": 1,
 "region": "global"
}
```

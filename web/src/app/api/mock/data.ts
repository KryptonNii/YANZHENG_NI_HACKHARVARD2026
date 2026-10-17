/**
 * MOCK DATA — fictional, for UI development and e2e only (VITE_MOCK_API=1).
 * Nothing here is a real trial or a real parameter value; every parameter is marked as an
 * assumption with a "mock" rationale, and every computed result carries a mock warning.
 */
import type { Parameter, Procedure, Site, TrialDesign, Visit } from "../../contracts";

const P = (code: string, label: string, site_minutes: number, ships_sample = false): Procedure => ({
  code,
  label,
  site_minutes,
  ships_sample,
  sample_temp: ships_sample ? "frozen_-80" : null,
});

const STD = [P("vitals", "Vital signs", 10), P("blood_draw", "Blood draw", 15, true), P("questionnaire", "Patient questionnaire", 15)];

const visits: Visit[] = [
  { number: 1, label: "Screening", week: -2, procedures: [...STD, P("ecg", "ECG", 20), P("physical_exam", "Physical exam", 25)], can_be_remote: false },
  { number: 2, label: "Baseline / randomisation", week: 0, procedures: [...STD, P("pk_sample", "PK sample", 10, true), P("spirometry", "Spirometry", 30)], can_be_remote: false },
  { number: 3, label: "Week 2", week: 2, procedures: [...STD], can_be_remote: true },
  { number: 4, label: "Week 4", week: 4, procedures: [...STD, P("pk_sample", "PK sample", 10, true)], can_be_remote: true },
  { number: 5, label: "Week 8", week: 8, procedures: [...STD, P("spirometry", "Spirometry", 30)], can_be_remote: false },
  { number: 6, label: "Week 12", week: 12, procedures: [...STD, P("ecg", "ECG", 20)], can_be_remote: true },
  { number: 7, label: "Week 16", week: 16, procedures: [...STD], can_be_remote: true },
  { number: 8, label: "Week 24", week: 24, procedures: [...STD, P("spirometry", "Spirometry", 30), P("mri", "Chest imaging", 45)], can_be_remote: false },
  { number: 9, label: "Week 36", week: 36, procedures: [...STD], can_be_remote: true },
  { number: 10, label: "Week 52 / end of treatment", week: 52, procedures: [...STD, P("ecg", "ECG", 20), P("spirometry", "Spirometry", 30), P("physical_exam", "Physical exam", 25)], can_be_remote: false },
  { number: 11, label: "Follow-up", week: 64, procedures: [P("vitals", "Vital signs", 10), P("questionnaire", "Patient questionnaire", 15)], can_be_remote: true },
];

// City coordinates are approximate public geography; site names are fictional.
const CITIES: Array<[string, string, number, number]> = [
  ["Boston", "United States", 42.36, -71.06],
  ["Chicago", "United States", 41.88, -87.63],
  ["Houston", "United States", 29.76, -95.37],
  ["Seattle", "United States", 47.61, -122.33],
  ["Atlanta", "United States", 33.75, -84.39],
  ["Denver", "United States", 39.74, -104.99],
  ["Toronto", "Canada", 43.65, -79.38],
  ["Montreal", "Canada", 45.5, -73.57],
  ["London", "United Kingdom", 51.51, -0.13],
  ["Manchester", "United Kingdom", 53.48, -2.24],
  ["Berlin", "Germany", 52.52, 13.4],
  ["Munich", "Germany", 48.14, 11.58],
  ["Paris", "France", 48.86, 2.35],
  ["Lyon", "France", 45.76, 4.84],
  ["Madrid", "Spain", 40.42, -3.7],
  ["Barcelona", "Spain", 41.39, 2.17],
  ["Milan", "Italy", 45.46, 9.19],
  ["Warsaw", "Poland", 52.23, 21.01],
  ["Prague", "Czechia", 50.08, 14.44],
  ["Tokyo", "Japan", 35.68, 139.69],
  ["Osaka", "Japan", 34.69, 135.5],
  ["Seoul", "South Korea", 37.57, 126.98],
  ["Sydney", "Australia", -33.87, 151.21],
  ["São Paulo", "Brazil", -23.55, -46.63],
];

const sites: Site[] = CITIES.map(([city, country, lat, lon], i) => ({
  id: `mock-site-${String(i + 1).padStart(2, "0")}`,
  name: `Mock Research Site ${i + 1}`,
  city,
  country,
  lat,
  lon,
  expected_enrollment: null,
}));

export const MOCK_DESIGN: TrialDesign = {
  id: "mock-design-0001",
  source: "fixture",
  registry_id: "MOCK-0001",
  title: "MOCK — Fictional Phase 3 biologic trial (mock data for UI development)",
  phase: "PHASE3",
  conditions: ["Fictional condition"],
  enrollment_target: 480,
  duration_months: 30,
  sites,
  visits,
  drug_type: "biologic",
  missing_fields: ["visits"],
};

const mockParam = (id: string, label: string, low: number, mid: number, high: number, unit: string): Parameter => ({
  id,
  label,
  value_low: low,
  value_mid: mid,
  value_high: high,
  unit,
  source_title: null,
  source_url: null,
  source_year: null,
  assumption: true,
  rationale: "MOCK value for UI development only — not a real parameter. The real library comes from GET /api/params.",
  version: 1,
  region: "global",
});

export const MOCK_PARAMS: Parameter[] = [
  mockParam("mock.cost.site_visit", "Mock: site cost per patient visit", 300, 450, 700, "usd/visit"),
  mockParam("mock.cost.monitoring_trip", "Mock: cost per on-site monitoring trip", 1500, 2200, 3200, "usd/trip"),
  mockParam("mock.cost.remote_review", "Mock: cost per remote monitoring review", 400, 600, 900, "usd/review"),
  mockParam("mock.cost.home_nurse_visit", "Mock: home-nurse visit cost", 350, 550, 800, "usd/visit"),
  mockParam("mock.cost.telehealth_visit", "Mock: telehealth visit cost", 60, 110, 180, "usd/visit"),
  mockParam("mock.cost.sample_shipment", "Mock: frozen sample shipment cost", 120, 200, 320, "usd/shipment"),
  mockParam("mock.cost.local_lab_harmonisation", "Mock: local lab harmonisation cost per sample", 15, 30, 55, "usd/sample"),
  mockParam("mock.cost.kit", "Mock: cost per drug kit", 600, 900, 1400, "usd/kit"),
  mockParam("mock.ef.car_km", "Mock: car emission factor", 0.12, 0.17, 0.22, "kg_co2e/km"),
  mockParam("mock.ef.flight_trip", "Mock: monitor flight per trip", 120, 250, 400, "kg_co2e/trip"),
  mockParam("mock.ef.shipment", "Mock: courier shipment emissions", 8, 15, 25, "kg_co2e/shipment"),
  mockParam("mock.ef.kit", "Mock: emissions per drug kit", 5, 9, 15, "kg_co2e/kit"),
  mockParam("mock.travel.roundtrip_km", "Mock: patient round trip distance", 30, 55, 90, "km"),
  mockParam("mock.travel.hours_per_visit", "Mock: patient travel time per visit", 1.0, 1.8, 3.0, "hours"),
  mockParam("mock.staff.minutes_per_visit_overhead", "Mock: site overhead minutes per visit", 30, 45, 70, "minutes/visit"),
  mockParam("mock.staff.remote_review_hours", "Mock: site hours per remote review", 1.5, 2.5, 4, "hours/review"),
  mockParam("mock.monitoring.trips_per_site_month", "Mock: monitoring trips per site-month", 0.3, 0.5, 0.8, "trips/site-month"),
  mockParam("mock.supply.overage_upfront", "Mock: upfront kit overage", 0.3, 0.45, 0.6, "fraction"),
  mockParam("mock.supply.overage_on_demand", "Mock: on-demand kit overage", 0.08, 0.15, 0.25, "fraction"),
  mockParam("mock.forecast.rate_per_site_month", "Mock: enrollment rate per site-month", 0.6, 0.9, 1.3, "patients/site-month"),
];

/**
 * MOCK ENGINE — illustrative arithmetic so the UI can be built and tested before the real engine
 * (A2/A3 via A5) is reachable. Results are NOT estimates: every result carries a mock warning and
 * the header shows "Mock API — fictional data". Never used unless VITE_MOCK_API=1.
 */
import type { Levers, MetricRange, MetricRangeUnit, ModuleBreakdown, ProvenanceItem, TrialDesign } from "../../contracts";
import type { Driver, ScenarioResultX } from "../types";
import { MOCK_PARAMS } from "./data";

const mid = (id: string): number => {
  const p = MOCK_PARAMS.find((x) => x.id === id);
  if (!p) throw new Error(`mock param ${id} missing`);
  return p.value_mid;
};

const range = (v: number, unit: MetricRangeUnit, spread = 0.2, skew = 1.25): MetricRange => ({
  p10: v * (1 - spread),
  p50: v,
  p90: v * (1 + spread * skew),
  unit,
});

const item = (formula_id: string, description: string, inputs: Record<string, number | string>, parameter_ids: string[], assumptions: string[] = []): ProvenanceItem => ({
  formula_id,
  description,
  inputs,
  parameter_ids,
  assumptions: ["Mock engine: illustrative arithmetic, not an estimate.", ...assumptions],
});

export const MOCK_WARNING = "MOCK ENGINE — fictional illustrative numbers, not estimates. Start the API for real results.";

export function mockCompute(design: TrialDesign, levers: Levers): ScenarioResultX {
  const activeSites = Math.max(design.sites.length - levers.excluded_site_ids.filter((id) => design.sites.some((s) => s.id === id)).length, 1);
  const N = design.enrollment_target;
  const removed = new Set(levers.removed_procedures);
  const home = new Set(levers.home_visit_numbers);
  const tele = new Set(levers.remote_visit_numbers);

  const siteVisitsPerPatient = design.visits.filter((v) => !home.has(v.number) && !tele.has(v.number)).length;
  const homeVisitsPerPatient = design.visits.filter((v) => home.has(v.number)).length;
  const teleVisitsPerPatient = design.visits.filter((v) => tele.has(v.number)).length;
  const procMinutesPerPatient = design.visits
    .filter((v) => !tele.has(v.number))
    .reduce((acc, v) => acc + v.procedures.filter((p) => !removed.has(p.code)).reduce((a, p) => a + (p.site_minutes ?? 15), 0), 0);
  const samplesPerPatient = design.visits.reduce((acc, v) => acc + v.procedures.filter((p) => p.ships_sample && !removed.has(p.code) && !tele.has(v.number)).length, 0);

  const siteVisits = N * siteVisitsPerPatient;
  const homeVisits = N * homeVisitsPerPatient;
  const teleVisits = N * teleVisitsPerPatient;
  const samples = N * samplesPerPatient;
  const centralShipments = (samples * (1 - levers.local_lab_share)) / 4;
  const localSamples = samples * levers.local_lab_share;

  // forecast (mock): enrollment months from a per-site rate, then follow-up + closeout
  const rate = mid("mock.forecast.rate_per_site_month");
  const enrollMonths = N / (activeSites * rate);
  const lastWeek = Math.max(...design.visits.map((v) => v.week), 0);
  const durationMonths = enrollMonths + lastWeek / 4.345 + 3;

  const monitoringTrips = activeSites * durationMonths * mid("mock.monitoring.trips_per_site_month") * (1 - levers.remote_monitoring_share);
  const remoteReviews = activeSites * durationMonths * mid("mock.monitoring.trips_per_site_month") * levers.remote_monitoring_share;

  const overage = levers.drug_supply_strategy === "upfront" ? mid("mock.supply.overage_upfront") : mid("mock.supply.overage_on_demand");
  const kitsNeeded = N * 8;
  const kitsProduced = kitsNeeded * (1 + overage);
  const kitsWasted = kitsProduced - kitsNeeded;
  const wasteShare = (kitsWasted / kitsProduced) * 100;
  const kitShipments = levers.drug_supply_strategy === "upfront" ? activeSites * 2 : activeSites * durationMonths * 0.8;

  const km = mid("mock.travel.roundtrip_km");
  const efCar = mid("mock.ef.car_km");

  const modules: ModuleBreakdown[] = [];
  const add = (module: string, cost: number, co2: number, provenance: ProvenanceItem[]) =>
    modules.push({ module, cost_usd: range(cost, "usd"), co2e_kg: range(co2, "kg_co2e", 0.25, 1.4), provenance });

  add("setup", activeSites * 12000, activeSites * 150, [
    item("cost.setup.mock", "active sites × setup cost per site", { active_sites: activeSites, usd_per_site: 12000 }, []),
  ]);
  add("trial_management", durationMonths * 20000, durationMonths * 300, [
    item("cost.trial_management.mock", "trial months × management cost per month", { months: Math.round(durationMonths * 10) / 10, usd_per_month: 20000 }, []),
  ]);
  add("meetings_travel", monitoringTrips * mid("mock.cost.monitoring_trip") + remoteReviews * mid("mock.cost.remote_review"), monitoringTrips * mid("mock.ef.flight_trip"), [
    item("cost.monitoring.mock", "on-site trips × trip cost + remote reviews × review cost", { onsite_trips: Math.round(monitoringTrips), remote_reviews: Math.round(remoteReviews) }, ["mock.cost.monitoring_trip", "mock.cost.remote_review", "mock.monitoring.trips_per_site_month"]),
    item("carbon.monitoring_travel.mock", "on-site trips × flight emissions per trip", { onsite_trips: Math.round(monitoringTrips) }, ["mock.ef.flight_trip"]),
    item("workload.remote_review.mock", "remote reviews × site hours per review", { remote_reviews: Math.round(remoteReviews) }, ["mock.staff.remote_review_hours"]),
  ]);
  add("intervention", 0, 0, [item("cost.intervention.mock", "excluded by default (routine-care comparator)", {}, [])]);
  add("data_collection", N * design.visits.length * 40, N * design.visits.length * 0.4, [
    item("cost.data_collection.mock", "patients × visits × data entry cost", { patients: N, visits: design.visits.length, usd_per_visit: 40 }, []),
  ]);
  add(
    "patient_assessments",
    siteVisits * mid("mock.cost.site_visit") + homeVisits * mid("mock.cost.home_nurse_visit") + teleVisits * mid("mock.cost.telehealth_visit"),
    siteVisits * km * efCar + homeVisits * (km / 2) * efCar,
    [
      item("cost.patient_visits.mock", "site visits × visit cost + home visits × nurse cost + telehealth visits × telehealth cost", { site_visits: siteVisits, home_visits: homeVisits, telehealth_visits: teleVisits }, ["mock.cost.site_visit", "mock.cost.home_nurse_visit", "mock.cost.telehealth_visit"]),
      item("carbon.patient_travel.mock", "site visits × round-trip km × car factor (+ nurse travel for home visits)", { site_visits: siteVisits, home_visits: homeVisits, roundtrip_km: km }, ["mock.travel.roundtrip_km", "mock.ef.car_km"]),
      item("burden.patient_travel.mock", "site visits × travel hours per visit", { site_visits: siteVisits }, ["mock.travel.hours_per_visit"]),
      item("workload.site_visits.mock", "patients × (procedure minutes + overhead per visit) ÷ 60", { patients: N, procedure_minutes_per_patient: procMinutesPerPatient, site_visits_per_patient: siteVisitsPerPatient }, ["mock.staff.minutes_per_visit_overhead"]),
    ],
  );
  add("samples", centralShipments * mid("mock.cost.sample_shipment"), centralShipments * mid("mock.ef.shipment"), [
    item("cost.samples.mock", "central-lab shipments × shipment cost (4 samples per shipment)", { samples, central_shipments: Math.round(centralShipments) }, ["mock.cost.sample_shipment"]),
    item("carbon.samples.mock", "central-lab shipments × courier emissions", { central_shipments: Math.round(centralShipments) }, ["mock.ef.shipment"]),
  ]);
  add("laboratory", samples * 40 + localSamples * mid("mock.cost.local_lab_harmonisation"), samples * 0.5, [
    item("cost.laboratory.mock", "samples × analysis cost + local samples × harmonisation", { samples, local_samples: Math.round(localSamples) }, ["mock.cost.local_lab_harmonisation"]),
  ]);
  add("closeout", activeSites * 3000, activeSites * 40, [item("cost.closeout.mock", "active sites × closeout cost", { active_sites: activeSites }, [])]);
  add("drug_supply", kitsProduced * mid("mock.cost.kit") + kitShipments * 250, kitsProduced * mid("mock.ef.kit") + kitShipments * 20, [
    item("cost.drug_supply.mock", "kits produced × kit cost + kit shipments × shipping cost", { kits_produced: Math.round(kitsProduced), kit_shipments: Math.round(kitShipments) }, ["mock.cost.kit"]),
    item("supply.waste.mock", "kit overage ÷ (1 + overage)", { overage, strategy: levers.drug_supply_strategy }, [levers.drug_supply_strategy === "upfront" ? "mock.supply.overage_upfront" : "mock.supply.overage_on_demand"]),
  ]);

  const counted = modules.filter((m) => m.module !== "intervention");
  const cost = counted.reduce((a, m) => a + m.cost_usd.p50, 0);
  const co2 = counted.reduce((a, m) => a + m.co2e_kg.p50, 0);
  const staffHours = (N * procMinutesPerPatient + siteVisits * mid("mock.staff.minutes_per_visit_overhead")) / 60 + remoteReviews * mid("mock.staff.remote_review_hours") + homeVisits * 0.3;
  const travelHours = siteVisits * mid("mock.travel.hours_per_visit");

  const months = Math.ceil(durationMonths);
  const curve: Array<[number, number, number, number]> = [];
  for (let m = 0; m <= months; m++) {
    const at = (r: number) => Math.min(N, Math.max(0, (m - 2) * activeSites * r));
    curve.push([m, at(rate * 0.7), at(rate), at(rate * 1.35)]);
  }

  return {
    design_id: design.id,
    levers,
    cost_usd: range(cost, "usd", 0.15),
    site_staff_hours: range(staffHours, "hours", 0.2),
    patient_travel_hours: range(travelHours, "hours", 0.3, 1.4),
    co2e_kg: range(co2, "kg_co2e", 0.25, 1.4),
    duration_months: range(durationMonths, "months", 0.1, 1.5),
    drug_waste_share: range(wasteShare, "percent", 0.2),
    modules,
    warnings: [MOCK_WARNING, ...(levers.drug_supply_strategy === "on_demand" ? ["On-demand supply: stockout risk 6% of simulations (mock)."] : [])],
    parameter_set_version: "mock-1",
    computed_at: new Date().toISOString(),
    forecast: {
      months_to_full_enrollment: range(enrollMonths + 2, "months", 0.2),
      milestone_dates: {
        first_patient_in: range(2, "months", 0.25),
        last_patient_in: range(enrollMonths + 2, "months", 0.2),
        database_lock: range(durationMonths, "months", 0.1, 1.5),
      },
      enrollment_curve: curve,
    },
    supply: {
      kits_needed: range(kitsNeeded, "kits", 0.1),
      kits_produced: range(kitsProduced, "kits", 0.1),
      kits_wasted: range(kitsWasted, "kits", 0.25),
      waste_share: range(wasteShare, "percent", 0.2),
      shipments: range(kitShipments, "kits", 0.2),
      stockout_probability: levers.drug_supply_strategy === "upfront" ? 0.01 : 0.06,
    },
  };
}

export function mockDrivers(metric: string): Driver[] {
  const byMetric: Record<string, string[]> = {
    cost_usd: ["mock.cost.kit", "mock.cost.site_visit", "mock.cost.monitoring_trip", "mock.supply.overage_upfront", "mock.cost.home_nurse_visit"],
    co2e_kg: ["mock.ef.flight_trip", "mock.ef.car_km", "mock.travel.roundtrip_km", "mock.ef.kit", "mock.ef.shipment"],
    site_staff_hours: ["mock.staff.minutes_per_visit_overhead", "mock.staff.remote_review_hours", "mock.cost.site_visit", "mock.monitoring.trips_per_site_month", "mock.forecast.rate_per_site_month"],
    patient_travel_hours: ["mock.travel.hours_per_visit", "mock.forecast.rate_per_site_month", "mock.travel.roundtrip_km", "mock.ef.car_km", "mock.cost.site_visit"],
    duration_months: ["mock.forecast.rate_per_site_month", "mock.monitoring.trips_per_site_month", "mock.supply.overage_upfront", "mock.cost.kit", "mock.ef.car_km"],
  };
  const shares = [0.41, 0.23, 0.14, 0.09, 0.05];
  return (byMetric[metric] ?? byMetric.cost_usd).map((id, i) => ({ parameter_id: id, share: shares[i] }));
}

/**
 * Operations API adapter. A8's client covers plan/compliance; the command center calls A6
 * (`/api/ops/...`) through the same `request` helper so identity headers and error shape match.
 */
import { ApiError, request } from "@/app/api/client";
import type { Alert, EffectEstimate, Intervention, OpsEvent, ProvenanceItem } from "@/app/contracts";

export { ApiError };

export const DEMO_TRIAL_ID = "demo-40";

export interface ClockInfo {
  trial_id: string;
  run_id: string;
  clock_day: number;
  now: string;
  epoch: string;
  horizon_day: number;
  speed_days_per_second: number;
  seed: number;
  scenario: string;
  simulated: boolean;
  new_events?: number;
}

export interface Band {
  p10: number;
  p50: number;
  p90: number;
  unit?: string;
}

export interface UiKpi {
  id: string;
  label: string;
  unit: string;
  value: number | null;
  value_text: string | null;
  plan: Band | null;
  status: string;
}

export interface SiteRow {
  site_id: string;
  name: string;
  city: string | null;
  country: string;
  status: string;
  enrolled: number;
  planned_to_date: Band;
  open_queries: number;
  median_query_age_days: number | null;
  drug_on_hand_kits: number;
  drug_need_kits: Band | null;
}

export interface CountryRow {
  country: string;
  region?: string;
  n_sites: number;
  enrolled: number;
  open_queries: number;
  stalled_sites: number;
  planned_to_date: Band;
}

export interface MilestoneLock {
  p50?: string | null;
  target?: string | null;
  slip_days_p50?: number | null;
  status?: string;
}

export interface StudySnapshot {
  enrollment?: { value?: number; target?: number; plan?: Band; status?: string };
  sites_status?: { value?: Record<string, number> };
  open_queries?: { value?: number; median_age_days?: number | null };
  drug_supply?: {
    kits_on_hand?: number;
    kits_in_transit?: number;
    projected_expiry_kits?: number;
  };
  milestones?: { db_lock?: MilestoneLock };
}

export interface HealthSnapshot {
  trial_id: string | null;
  trial_title: string;
  as_of: string;
  simulated?: boolean;
  data_label?: string;
  kpis: UiKpi[];
  countries: CountryRow[];
  sites: SiteRow[];
  study: StudySnapshot;
  clock?: ClockInfo;
  provenance?: Record<string, ProvenanceItem>;
  plan_notes?: string[];
}

export interface EffectValues {
  treated_pre?: number;
  treated_post?: number;
  control_pre?: number;
  control_post?: number;
  did?: number;
}

/** EffectEstimate plus the before/after numbers A6 returns on the detail route. */
export interface EffectDetail {
  estimate: EffectEstimate;
  metric_label?: string;
  unit?: string;
  treated_units?: string[];
  control_units?: string[];
  control_tier?: string;
  values?: EffectValues | null;
}

const enc = encodeURIComponent;

function asItems<T>(body: unknown): T[] {
  if (Array.isArray(body)) return body as T[];
  if (body && typeof body === "object" && Array.isArray((body as { items?: unknown }).items)) {
    return (body as { items: T[] }).items;
  }
  return [];
}

function isObj(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function band(v: unknown): Band | null {
  if (!isObj(v)) return null;
  const p10 = num(v.p10);
  const p50 = num(v.p50);
  const p90 = num(v.p90);
  if (p10 === null || p50 === null || p90 === null) return null;
  return { p10, p50, p90, unit: typeof v.unit === "string" ? v.unit : undefined };
}

function normalizeHealth(raw: unknown): HealthSnapshot {
  const d = isObj(raw) ? raw : {};
  const kpis = asItems<unknown>(isObj(d) && Array.isArray(d.kpis) ? d.kpis : []).map((row) => {
    const k = isObj(row) ? row : {};
    return {
      id: typeof k.id === "string" ? k.id : "kpi",
      label: typeof k.label === "string" ? k.label : "KPI",
      unit: typeof k.unit === "string" ? k.unit : "",
      value: num(k.value),
      value_text: typeof k.value_text === "string" ? k.value_text : null,
      plan: band(k.plan),
      status: typeof k.status === "string" ? k.status : "unknown",
    } satisfies UiKpi;
  });
  const sites = asItems<unknown>(Array.isArray(d.sites) ? d.sites : []).map((row) => {
    const s = isObj(row) ? row : {};
    return {
      site_id: typeof s.site_id === "string" ? s.site_id : "",
      name: typeof s.name === "string" ? s.name : "Site",
      city: typeof s.city === "string" ? s.city : null,
      country: typeof s.country === "string" ? s.country : "",
      status: typeof s.status === "string" ? s.status : "unknown",
      enrolled: num(s.enrolled) ?? 0,
      planned_to_date: band(s.planned_to_date) ?? { p10: 0, p50: 0, p90: 0, unit: "patients" },
      open_queries: num(s.open_queries) ?? 0,
      median_query_age_days: num(s.median_query_age_days),
      drug_on_hand_kits: num(s.drug_on_hand_kits) ?? 0,
      drug_need_kits: band(s.drug_need_kits),
    } satisfies SiteRow;
  });
  const countries = asItems<unknown>(Array.isArray(d.countries) ? d.countries : []).map((row) => {
    const c = isObj(row) ? row : {};
    return {
      country: typeof c.country === "string" ? c.country : "",
      region: typeof c.region === "string" ? c.region : undefined,
      n_sites: num(c.n_sites) ?? num(c.sites) ?? 0,
      enrolled: num(c.enrolled) ?? 0,
      open_queries: num(c.open_queries) ?? 0,
      stalled_sites: num(c.stalled_sites) ?? 0,
      planned_to_date: band(c.planned_to_date) ?? { p10: 0, p50: 0, p90: 0, unit: "patients" },
    } satisfies CountryRow;
  });
  return {
    trial_id: typeof d.trial_id === "string" ? d.trial_id : null,
    trial_title: typeof d.trial_title === "string" ? d.trial_title : "Trial",
    as_of: typeof d.as_of === "string" ? d.as_of : "",
    simulated: d.simulated !== false,
    data_label: typeof d.data_label === "string" ? d.data_label : undefined,
    kpis,
    countries,
    sites,
    study: (isObj(d.study) ? d.study : {}) as StudySnapshot,
    clock: isObj(d.clock) ? (d.clock as unknown as ClockInfo) : undefined,
    provenance: isObj(d.provenance) ? (d.provenance as unknown as Record<string, ProvenanceItem>) : undefined,
    plan_notes: Array.isArray(d.plan_notes) ? d.plan_notes.filter((n): n is string => typeof n === "string") : [],
  };
}

function normalizeEffect(raw: unknown, fallback?: EffectEstimate): EffectDetail {
  const d = isObj(raw) ? raw : {};
  const estimate = (isObj(d.estimate) ? d.estimate : isObj(d) && typeof d.intervention_id === "string" ? d : fallback) as
    | EffectEstimate
    | undefined;
  if (!estimate) {
    throw new Error("Unexpected effect response");
  }
  const values = isObj(d.values) ? (d.values as EffectValues) : null;
  return {
    estimate,
    metric_label: typeof d.metric_label === "string" ? d.metric_label : undefined,
    unit: typeof d.unit === "string" ? d.unit : estimate.effect?.unit,
    treated_units: Array.isArray(d.treated_units) ? d.treated_units.filter((x): x is string => typeof x === "string") : undefined,
    control_units: Array.isArray(d.control_units) ? d.control_units.filter((x): x is string => typeof x === "string") : undefined,
    control_tier: typeof d.control_tier === "string" ? d.control_tier : undefined,
    values,
  };
}

export function simulate(trialId: string) {
  return request<ClockInfo & { event_count?: number; alerts?: number; data_label?: string }>(
    "POST",
    `/ops/${enc(trialId)}/simulate`,
    { body: { seed: 42, speed: 0, scenario: "demo" }, silent: true },
  );
}

export function advanceClock(trialId: string, advanceDays: number) {
  return request<ClockInfo>("POST", `/ops/${enc(trialId)}/clock`, {
    body: { advance_days: advanceDays },
    silent: true,
  });
}

export async function getHealth(trialId: string, signal?: AbortSignal): Promise<HealthSnapshot> {
  return normalizeHealth(await request("GET", `/ops/${enc(trialId)}/health`, { signal, silent: true }));
}

export async function listAlerts(trialId: string): Promise<Alert[]> {
  return asItems<Alert>(await request("GET", `/ops/${enc(trialId)}/alerts`, { silent: true }));
}

export function patchAlert(trialId: string, alertId: string, status: Alert["status"], reason?: string) {
  return request<Alert>("POST", `/ops/${enc(trialId)}/alerts/${enc(alertId)}`, {
    body: { status, reason: reason ?? null },
    silent: true,
  });
}

export async function listInterventions(trialId: string): Promise<Intervention[]> {
  return asItems<Intervention>(await request("GET", `/ops/${enc(trialId)}/interventions`, { silent: true }));
}

export function createIntervention(
  trialId: string,
  body: { alert_id?: string; action: string; owner: string; target_site_ids: string[]; metric?: string },
) {
  return request<Intervention>("POST", `/ops/${enc(trialId)}/interventions`, { body, silent: true });
}

export async function listEffects(trialId: string): Promise<EffectDetail[]> {
  const items = asItems<EffectEstimate>(await request("GET", `/ops/${enc(trialId)}/effects`, { silent: true }));
  const details = await Promise.all(
    items.map(async (est) => {
      try {
        return normalizeEffect(await request("GET", `/ops/${enc(trialId)}/effects/${enc(est.intervention_id)}`, { silent: true }), est);
      } catch {
        return normalizeEffect(est, est);
      }
    }),
  );
  return details;
}

export async function listEvents(trialId: string, limit = 20): Promise<OpsEvent[]> {
  const body = await request("GET", `/ops/${enc(trialId)}/events?limit=${limit}`, { silent: true });
  return asItems<OpsEvent>(body).slice(0, limit);
}

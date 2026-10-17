/**
 * Defensive normalisers for API responses whose envelope is not fixed by §5. The §5 models
 * themselves are passed through unchanged; only envelopes (lists, wrappers, optional
 * extensions) are adapted. Unknown or missing values become null / [] — never invented numbers.
 */
import type { ApprovalRequest, Levers, MetricRange, TrialDesign, Visit } from "../contracts";
import type {
  ApprovalView,
  CompareResult,
  DesignSummary,
  Driver,
  SignatureView,
  ExtractionCandidate,
  ForecastDetail,
  ImportCtgovResponse,
  ProtocolExtractionResponse,
  SavedScenario,
  ScenarioResultX,
  ScenarioStatus,
  ScienceModuleRow,
  ScienceResults,
  ScienceTrial,
  SupplyDetail,
} from "./types";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const strList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** Accepts `[...]`, `{<key>: [...]}`, `{items: [...]}` or `{results: [...]}`. */
export function asArray<T>(data: unknown, key?: string): T[] {
  if (Array.isArray(data)) return data as T[];
  if (isObj(data)) {
    for (const k of [key, "items", "results", "data"]) {
      if (k && Array.isArray(data[k])) return data[k] as T[];
    }
  }
  return [];
}

export function isMetricRange(v: unknown): v is MetricRange {
  return isObj(v) && num(v.p10) !== null && num(v.p50) !== null && num(v.p90) !== null && typeof v.unit === "string";
}

const range = (v: unknown): MetricRange | null => (isMetricRange(v) ? v : null);

export const DEFAULT_LEVERS: Levers = {
  remote_monitoring_share: 0,
  home_visit_numbers: [],
  remote_visit_numbers: [],
  local_lab_share: 0,
  drug_supply_strategy: "upfront",
  removed_procedures: [],
  excluded_site_ids: [],
};

export function normalizeLevers(v: unknown): Levers {
  if (!isObj(v)) return { ...DEFAULT_LEVERS };
  const nums = (x: unknown) => (Array.isArray(x) ? x.filter((n): n is number => typeof n === "number") : []);
  return {
    remote_monitoring_share: num(v.remote_monitoring_share) ?? 0,
    home_visit_numbers: nums(v.home_visit_numbers),
    remote_visit_numbers: nums(v.remote_visit_numbers),
    local_lab_share: num(v.local_lab_share) ?? 0,
    drug_supply_strategy: v.drug_supply_strategy === "on_demand" ? "on_demand" : "upfront",
    removed_procedures: strList(v.removed_procedures),
    excluded_site_ids: strList(v.excluded_site_ids),
  };
}

export function normalizeImport(data: unknown): ImportCtgovResponse {
  const d = isObj(data) ? data : {};
  const design = (isObj(d.design) ? d.design : d) as unknown as TrialDesign;
  return {
    design,
    raw_cached: d.raw_cached === true,
    missing_fields: strList(d.missing_fields).length ? strList(d.missing_fields) : (design.missing_fields ?? []),
    warnings: strList(d.warnings),
  };
}

function toCandidate(item: unknown): ExtractionCandidate | null {
  if (!isObj(item)) return null;
  const visit = (isObj(item.visit) ? item.visit : item) as unknown as Visit;
  if (typeof visit.number !== "number" && typeof visit.label !== "string") return null;
  return {
    visit: {
      number: num(visit.number) ?? 0,
      label: str(visit.label) ?? "",
      week: num(visit.week) ?? 0,
      procedures: Array.isArray(visit.procedures) ? visit.procedures : [],
      can_be_remote: visit.can_be_remote === true,
    },
    source_page: num(item.source_page) ?? num(item.page),
    quote: str(item.quote),
    confidence: num(item.confidence),
  };
}

export function normalizeExtraction(data: unknown): ProtocolExtractionResponse {
  const d = isObj(data) ? data : {};
  const raw = Array.isArray(d.candidates) ? d.candidates : Array.isArray(d.visits) ? d.visits : [];
  return {
    candidates: raw.map(toCandidate).filter((c): c is ExtractionCandidate => c !== null),
    warnings: strList(d.warnings),
  };
}

function normalizeForecast(v: unknown): ForecastDetail | null {
  if (!isObj(v)) return null;
  const curve = Array.isArray(v.enrollment_curve)
    ? v.enrollment_curve.filter(
        (row): row is [number, number, number, number] =>
          Array.isArray(row) && row.length >= 4 && row.slice(0, 4).every((x) => typeof x === "number"),
      )
    : [];
  const milestones: Record<string, MetricRange> = {};
  if (isObj(v.milestone_dates)) {
    for (const [k, r] of Object.entries(v.milestone_dates)) if (isMetricRange(r)) milestones[k] = r;
  }
  return { months_to_full_enrollment: range(v.months_to_full_enrollment), milestone_dates: milestones, enrollment_curve: curve };
}

function normalizeSupply(v: unknown): SupplyDetail | null {
  if (!isObj(v)) return null;
  return {
    kits_needed: range(v.kits_needed),
    kits_produced: range(v.kits_produced),
    kits_wasted: range(v.kits_wasted),
    waste_share: range(v.waste_share),
    shipments: range(v.shipments),
    stockout_probability: num(v.stockout_probability),
  };
}

export function normalizeScenarioResult(data: unknown): ScenarioResultX {
  const d = (isObj(data) && isObj(data.result) && !isMetricRange(data.cost_usd) ? data.result : data) as Obj;
  const result = { ...(d as object) } as ScenarioResultX;
  result.modules = Array.isArray(d.modules) ? (d.modules as ScenarioResultX["modules"]) : [];
  result.warnings = strList(d.warnings);
  result.forecast = normalizeForecast(d.forecast);
  result.supply = normalizeSupply(d.supply);
  return result;
}

const STATUSES: ScenarioStatus[] = ["draft", "submitted", "approved", "rejected"];
const HEADLINE = ["cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg", "duration_months", "drug_waste_share"] as const;

function metricMap(v: unknown): Record<string, MetricRange> {
  const out: Record<string, MetricRange> = {};
  if (isObj(v)) for (const [k, r] of Object.entries(v)) if (isObj(r) && typeof r.unit === "string") out[k] = r as unknown as MetricRange;
  return out;
}

export function normalizeSavedScenario(data: unknown): SavedScenario {
  const d = isObj(data) ? (isObj(data.scenario) ? data.scenario : data) : {};
  const status = STATUSES.includes(d.status as ScenarioStatus) ? (d.status as ScenarioStatus) : "draft";
  const result = isObj(d.result) ? normalizeScenarioResult(d.result) : null;
  let metrics = metricMap(d.metrics);
  if (!Object.keys(metrics).length && result) {
    metrics = Object.fromEntries(HEADLINE.map((k) => [k, result[k]]));
  }
  const approval = isApproval(d.approval) ? normalizeApproval(d.approval) : null;
  return {
    id: String(d.id ?? ""),
    lineage_id: str(d.lineage_id) ?? String(d.id ?? ""),
    version: num(d.version) ?? 1,
    parent_id: str(d.parent_id),
    name: str(d.name) ?? "Untitled scenario",
    design_id: String(d.design_id ?? ""),
    design_version: num(d.design_version),
    status,
    author: str(d.author) ?? "unknown",
    created_at: str(d.created_at),
    parameter_set_version: str(d.parameter_set_version),
    record_hash: str(d.record_hash),
    metrics,
    levers: isObj(d.levers) ? normalizeLevers(d.levers) : null,
    result,
    approval_id: str(d.approval_id) ?? approval?.id ?? null,
    approval,
  };
}

function isApproval(v: unknown): v is ApprovalRequest {
  return isObj(v) && typeof v.id === "string" && Array.isArray(v.required_meanings);
}

export function normalizeApproval(data: unknown): ApprovalView {
  const d = isObj(data) ? data : {};
  const candidate = isApproval(d) ? d : isApproval(d.approval) ? d.approval : isApproval(d.approval_request) ? d.approval_request : null;
  if (!candidate) {
    throw new Error("Unexpected approval response shape");
  }
  return {
    ...(candidate as unknown as ApprovalView),
    signatures: Array.isArray(candidate.signatures) ? (candidate.signatures as SignatureView[]) : [],
  };
}

export function normalizeDesignSummary(v: unknown): DesignSummary | null {
  if (!isObj(v) || typeof v.id !== "string") return null;
  const sites = Array.isArray(v.sites) ? (v.sites as Array<{ country?: string }>) : null;
  return {
    id: v.id,
    version: num(v.version) ?? 1,
    title: str(v.title) ?? v.id,
    source: str(v.source) ?? "unknown",
    registry_id: str(v.registry_id),
    phase: str(v.phase),
    enrollment_target: num(v.enrollment_target) ?? 0,
    duration_months: num(v.duration_months) ?? 0,
    site_count: num(v.site_count) ?? sites?.length ?? 0,
    visit_count: num(v.visit_count) ?? (Array.isArray(v.visits) ? v.visits.length : 0),
    countries: strList(v.countries).length ? strList(v.countries) : [...new Set((sites ?? []).map((s) => s.country ?? ""))].filter(Boolean),
    drug_type: str(v.drug_type) ?? "unknown",
    missing_fields: strList(v.missing_fields),
    created_at: str(v.created_at),
  };
}

export function normalizeCompare(data: unknown): CompareResult {
  const d = isObj(data) ? data : {};
  return {
    deltas: metricMap(d.deltas),
    a_metrics: metricMap(d.a_metrics),
    b_metrics: metricMap(d.b_metrics),
    same_parameter_set: d.same_parameter_set !== false,
    parameter_set_version: str(d.parameter_set_version),
    warnings: strList(d.warnings),
  };
}

export function normalizeDrivers(data: unknown): Driver[] {
  const rows = asArray<unknown>(data, "drivers");
  const out: Driver[] = [];
  for (const r of rows) {
    if (Array.isArray(r) && typeof r[0] === "string" && typeof r[1] === "number") {
      out.push({ parameter_id: r[0], share: r[1] });
    } else if (isObj(r)) {
      const id = str(r.parameter_id) ?? str(r.id) ?? str(r.parameter);
      const share = num(r.share) ?? num(r.variance_share) ?? num(r.contribution);
      if (id && share !== null) out.push({ parameter_id: id, share, label: str(r.label), unit: str(r.unit) });
    }
  }
  return out.slice(0, 5);
}

function normalizeScienceModule(m: unknown, key?: string): ScienceModuleRow | null {
  if (!isObj(m)) return null;
  const published = isObj(m.published) ? num(m.published.kg ?? m.published.p50) : num(m.published_kg ?? m.published);
  return {
    module: str(m.module) ?? key ?? "unknown",
    published_kg: published,
    ours: range(m.ours) ?? range(m.ours_kg) ?? range(m.engine),
    pct_diff: num(m.pct_diff) ?? num(m.percent_difference) ?? num(m.diff_pct),
    note: str(m.note) ?? str(m.explanation),
  };
}

function normalizeScienceTrial(t: unknown, key?: string): ScienceTrial | null {
  if (!isObj(t)) return null;
  const modulesRaw = t.modules;
  const modules: ScienceModuleRow[] = Array.isArray(modulesRaw)
    ? modulesRaw.map((m) => normalizeScienceModule(m)).filter((m): m is ScienceModuleRow => m !== null)
    : isObj(modulesRaw)
      ? Object.entries(modulesRaw)
          .map(([k, m]) => normalizeScienceModule(m, k))
          .filter((m): m is ScienceModuleRow => m !== null)
      : [];
  const total = isObj(t.total) ? t.total : {};
  const paper = isObj(t.paper) ? t.paper : {};
  return {
    id: str(t.id) ?? key ?? str(t.name) ?? "trial",
    name: str(t.name) ?? str(t.trial) ?? key ?? "Trial",
    registry_id: str(t.registry_id),
    paper_url: str(t.paper_url) ?? str(paper.url) ?? str(t.source_url),
    paper_title: str(t.paper_title) ?? str(paper.title),
    published_total_kg: num(t.published_total_kg) ?? num(total.published_kg) ?? num(total.published),
    ours_total: range(t.ours_total) ?? range(total.ours) ?? range(total.ours_kg),
    pct_diff: num(t.pct_diff) ?? num(total.pct_diff),
    modules,
    matched: strList(t.matched),
    not_matched: strList(t.not_matched) .length ? strList(t.not_matched) : strList(t.mismatched),
    explanation: str(t.explanation) ?? str(t.summary),
    check: str(t.check) ?? str(t.method),
  };
}

export function normalizeScience(data: unknown): ScienceResults {
  const d = isObj(data) ? data : {};
  let trials: ScienceTrial[] = [];
  if (Array.isArray(d.trials)) {
    trials = d.trials.map((t) => normalizeScienceTrial(t)).filter((t): t is ScienceTrial => t !== null);
  } else if (isObj(d.trials)) {
    trials = Object.entries(d.trials)
      .map(([k, t]) => normalizeScienceTrial(t, k))
      .filter((t): t is ScienceTrial => t !== null);
  } else if (Array.isArray(data)) {
    trials = data.map((t) => normalizeScienceTrial(t)).filter((t): t is ScienceTrial => t !== null);
  }
  return { trials, generated_at: str(d.generated_at), notes: strList(d.notes) };
}

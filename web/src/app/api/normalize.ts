/**
 * Defensive normalisers for API responses whose envelope is not fixed by §5. The §5 models
 * themselves are passed through unchanged; only envelopes (lists, wrappers, optional
 * extensions) are adapted. Unknown or missing values become null / [] — never invented numbers.
 */
import type { ApprovalRequest, Levers, MetricRange, Procedure, ProvenanceItem, TrialDesign } from "../contracts";
import { parseImportNotes } from "../../features/scenario/importNotes";
import type {
  ApprovalView,
  CachedStudy,
  RegistryDocument,
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
  ScienceBandTrial,
  ScienceCheck,
  ScienceDesignInput,
  ScienceFinding,
  ScienceIndustryBand,
  ScienceLineChange,
  ScienceModuleRow,
  SciencePublished,
  ScienceRange,
  ScienceResults,
  ScienceRowStatus,
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

/** A range is known (three finite numbers) or unknown (three nulls / NaN). A partial range is dropped. */
export function isMetricRange(v: unknown): v is MetricRange {
  if (!isObj(v) || typeof v.unit !== "string" || !["usd", "hours", "kg_co2e", "months", "patients", "percent", "kits", "count"].includes(v.unit)) return false;
  const raw = [v.p10, v.p50, v.p90];
  const vals = raw.map((x) => (x === null || (typeof x === "number" && Number.isNaN(x)) ? null : num(x)));
  const junk = raw.some((x, i) => vals[i] === null && x !== null && x !== undefined && !(typeof x === "number" && Number.isNaN(x)));
  if (junk) return false;
  return vals.every((x) => x !== null) || vals.every((x) => x === null);
}

const range = (v: unknown): MetricRange | null => {
  if (!isMetricRange(v)) return null;
  return { p10: num(v.p10), p50: num(v.p50), p90: num(v.p90), unit: v.unit };
};

export const DEFAULT_LEVERS: Levers = {
  enrollment_rate_multiplier: 1,
  added_country_count: 0,
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
    enrollment_rate_multiplier: num(v.enrollment_rate_multiplier) ?? 1,
    added_country_count: num(v.added_country_count) ?? 0,
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
  const fieldSources: Record<string, string> = {};
  if (isObj(d.field_sources)) for (const [k, v] of Object.entries(d.field_sources)) if (typeof v === "string") fieldSources[k] = v;
  const documents: RegistryDocument[] = Array.isArray(d.documents)
    ? d.documents.filter(isObj).map((doc) => ({
        label: str(doc.label),
        url: str(doc.url),
        has_protocol: doc.has_protocol === true,
        extraction_cached: doc.extraction_cached === true,
      }))
    : [];
  const notes = parseImportNotes(d.notes ?? d.warnings, d.notes_by_field);
  return {
    design,
    raw_cached: d.raw_cached === true,
    missing_fields: strList(d.missing_fields).length ? strList(d.missing_fields) : (design.missing_fields ?? []),
    warnings: notes.map((n) => n.text),
    notes,
    field_sources: fieldSources,
    sponsor: str(d.sponsor),
    collaborators: strList(d.collaborators),
    acronym: str(d.acronym),
    overall_status: str(d.overall_status),
    attribution: str(d.attribution),
    documents,
  };
}

export function normalizeCachedStudies(data: unknown): CachedStudy[] {
  return asArray<unknown>(data, "studies")
    .filter(isObj)
    .filter((s) => typeof s.nct_id === "string")
    .map((s) => ({
      nct_id: s.nct_id as string,
      title: str(s.title) ?? (s.nct_id as string),
      acronym: str(s.acronym),
      phase: str(s.phase),
      drug_type: str(s.drug_type),
      sites: num(s.sites),
      sponsor: str(s.sponsor),
      protocol_extraction_cached: s.protocol_extraction_cached === true,
    }));
}

function isProcedure(value: unknown): value is Procedure {
  if (!isObj(value)) return false;
  return typeof value.code === "string" && typeof value.label === "string"
    && (value.site_minutes === null || num(value.site_minutes) !== null)
    && typeof value.ships_sample === "boolean"
    && (value.sample_temp === null || ["ambient", "refrigerated", "frozen_-20", "frozen_-80"].includes(String(value.sample_temp)));
}

function toCandidate(item: unknown): ExtractionCandidate {
  if (!isObj(item)) throw new Error("The protocol response contains an invalid visit. Extract again before applying.");
  const visit = isObj(item.visit) ? item.visit : item;
  const number = num(visit.number);
  const week = num(visit.week);
  if (number === null || !Number.isInteger(number) || week === null || typeof visit.label !== "string"
    || !Array.isArray(visit.procedures) || !visit.procedures.every(isProcedure) || typeof visit.can_be_remote !== "boolean") {
    throw new Error("The protocol response contains an invalid visit, week or procedure. Missing weeks are not assumed to be zero; extract again before applying.");
  }
  return {
    visit: {
      number,
      label: visit.label,
      week,
      procedures: visit.procedures,
      can_be_remote: visit.can_be_remote,
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
    extraction_id: str(d.extraction_id),
    candidates: raw.map(toCandidate),
    warnings: strList(d.warnings),
    excluded_columns: strList(d.excluded_columns),
    method: str(d.method),
    model: str(d.model),
    soa_pages: Array.isArray(d.soa_pages) ? d.soa_pages.filter((n): n is number => typeof n === "number") : [],
    page_count: num(d.page_count),
    from_cache: d.from_cache === true,
    notice: str(d.notice),
  };
}

function provenance(v: unknown): ProvenanceItem[] {
  if (!Array.isArray(v)) return [];
  return v.filter((p): p is ProvenanceItem => isObj(p) && typeof p.formula_id === "string" && typeof p.description === "string"
    && isObj(p.inputs) && Object.values(p.inputs).every((x) => typeof x === "string" || num(x) !== null)
    && Array.isArray(p.parameter_ids) && p.parameter_ids.every((x) => typeof x === "string")
    && Array.isArray(p.assumptions) && p.assumptions.every((x) => typeof x === "string"));
}

function sampling(v: Obj) {
  const count = (x: unknown) => typeof x === "number" && Number.isInteger(x) && x > 0 ? x : null;
  return { draws_requested: count(v.draws_requested), draws_used: count(v.draws_used), provenance: provenance(v.provenance) };
}

function normalizeForecast(v: unknown): ForecastDetail | null {
  if (!isObj(v)) return null;
  const curve: ForecastDetail["enrollment_curve"] = [];
  if (Array.isArray(v.enrollment_curve)) {
    for (const row of v.enrollment_curve) {
      if (!Array.isArray(row) || row.length !== 4 || num(row[0]) === null) { curve.length = 0; break; }
      const month = num(row[0]);
      if (month === null) break;
      const [p10, p50, p90] = row.slice(1).map(num);
      const known = p10 !== null && p50 !== null && p90 !== null && p10 <= p50 && p50 <= p90;
      curve.push(known ? [month, p10, p50, p90] : [month, null, null, null]);
    }
  }
  const milestones: Record<string, MetricRange> = {};
  if (isObj(v.milestone_dates)) {
    for (const [k, r] of Object.entries(v.milestone_dates)) { const parsed = range(r); if (parsed) milestones[k] = parsed; }
  }
  return { ...sampling(v), curve_draws_used: sampling({ draws_used: v.curve_draws_used }).draws_used,
    months_to_full_enrollment: range(v.months_to_full_enrollment), milestone_dates: milestones, enrollment_curve: curve };
}

function normalizeSupply(v: unknown): SupplyDetail | null {
  if (!isObj(v)) return null;
  return {
    ...sampling(v),
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
  // The UI preserves absent details and gaps without changing the generated contract.
  result.forecast = normalizeForecast(d.forecast);
  result.supply = normalizeSupply(d.supply);
  return result;
}

const STATUSES: ScenarioStatus[] = ["draft", "submitted", "approved", "rejected"];
const HEADLINE = ["cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg", "duration_months", "drug_waste_share"] as const;

function metricMap(v: unknown): Record<string, MetricRange> {
  const out: Record<string, MetricRange> = {};
  if (isObj(v)) for (const [k, r] of Object.entries(v)) { const parsed = range(r); if (parsed) out[k] = parsed; }
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
    enrollment_target: num(v.enrollment_target),
    duration_months: num(v.duration_months),
    site_count: num(v.site_count) ?? sites?.length ?? null,
    visit_count: num(v.visit_count) ?? (Array.isArray(v.visits) ? v.visits.length : null),
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

const SCIENCE_STATUSES: ScienceRowStatus[] = ["match", "close", "gap", "not_reported", "unavailable"];

function scienceRange(v: unknown): ScienceRange | null {
  if (!isObj(v)) return null;
  const p10 = num(v.p10);
  const p50 = num(v.p50);
  const p90 = num(v.p90);
  if (p10 === null || p50 === null || p90 === null) return null;
  return { p10, p50, p90, unit: str(v.unit) ?? "kg_co2e" };
}

function scienceStatus(v: unknown, diff: number | null): ScienceRowStatus {
  if (typeof v === "string" && (SCIENCE_STATUSES as string[]).includes(v)) return v as ScienceRowStatus;
  if (diff === null) return "not_reported";
  const a = Math.abs(diff);
  if (a <= 1) return "match";
  if (a <= 10) return "close";
  return "gap";
}

function normalizeScienceModule(m: unknown, key?: string): ScienceModuleRow | null {
  if (!isObj(m)) return null;
  const published = isObj(m.published) ? num(m.published.kg ?? m.published.p50) : num(m.published_kg ?? m.published);
  const diff = num(m.diff_pct) ?? num(m.pct_diff) ?? num(m.percent_difference);
  const moduleId = str(m.module) ?? key ?? "unknown";
  return {
    module: moduleId,
    label: str(m.label) ?? "",
    published_kg: published,
    ours: scienceRange(m.ours) ?? scienceRange(m.ours_kg) ?? scienceRange(m.engine),
    diff_pct: diff,
    published_within_range: typeof m.published_within_range === "boolean" ? m.published_within_range : null,
    status: scienceStatus(m.status, diff),
    explanation: str(m.explanation) ?? str(m.note),
  };
}

function moduleList(raw: unknown): ScienceModuleRow[] {
  if (Array.isArray(raw)) return raw.map((m) => normalizeScienceModule(m)).filter((m): m is ScienceModuleRow => m !== null);
  if (isObj(raw)) {
    return Object.entries(raw)
      .map(([k, m]) => normalizeScienceModule(m, k))
      .filter((m): m is ScienceModuleRow => m !== null);
  }
  return [];
}

function normalizeLineChange(v: unknown): ScienceLineChange | null {
  if (!isObj(v)) return null;
  const item = str(v.item) ?? str(v.line_id);
  if (!item) return null;
  return {
    line_id: str(v.line_id) ?? item,
    module: str(v.module) ?? "",
    item,
    paper_factor: num(v.paper_factor),
    paper_kg: num(v.paper_kg),
    library_factor_p50: num(v.library_factor_p50),
    library_kg: scienceRange(v.library_kg),
    parameter_ids: strList(v.parameter_ids),
    kind: str(v.kind) ?? "independent",
    note: str(v.note) ?? "",
  };
}

function normalizeScienceCheck(c: unknown, index: number): ScienceCheck | null {
  if (!isObj(c)) return null;
  return {
    id: str(c.id) ?? `check-${index}`,
    title: str(c.title) ?? str(c.id) ?? "Check",
    description: str(c.description) ?? "",
    available: c.available !== false,
    unavailable_reason: str(c.unavailable_reason),
    total: isObj(c.total) ? normalizeScienceModule(c.total, "total") : null,
    modules: moduleList(c.modules),
    notes: strList(c.notes),
    line_changes: Array.isArray(c.line_changes)
      ? c.line_changes.map(normalizeLineChange).filter((row): row is ScienceLineChange => row !== null)
      : [],
  };
}

/** Earlier guess of the results shape: one total + a module list, no checks. Kept so a partial file still renders. */
function legacyCheck(t: Obj): ScienceCheck | null {
  const modules = moduleList(t.modules);
  const totalObj = isObj(t.total) ? t.total : {};
  const published = num(t.published_total_kg) ?? num(totalObj.published_kg) ?? num(totalObj.published);
  const ours = scienceRange(t.ours_total) ?? scienceRange(totalObj.ours) ?? scienceRange(totalObj.ours_kg);
  const diff = num(t.pct_diff) ?? num(totalObj.pct_diff) ?? num(totalObj.diff_pct);
  const explanation = str(t.explanation);
  if (published === null && !ours && modules.length === 0 && !explanation) return null;
  return {
    id: str(t.check) ?? "engine_library",
    title: str(t.check) ?? "Engine",
    description: "",
    available: true,
    unavailable_reason: null,
    total:
      published !== null || ours
        ? {
            module: "total",
            label: "Total",
            published_kg: published,
            ours,
            diff_pct: diff,
            published_within_range: null,
            status: scienceStatus(undefined, diff),
            explanation,
          }
        : null,
    modules,
    notes: [],
    line_changes: [],
  };
}

function normalizeFinding(v: unknown): ScienceFinding | null {
  if (!isObj(v)) return null;
  const summary = str(v.summary);
  if (!summary) return null;
  return {
    id: str(v.id) ?? summary,
    severity: str(v.severity) ?? "info",
    summary,
    detail: str(v.detail) ?? "",
    lines: strList(v.lines),
    effect_kg: num(v.effect_kg),
  };
}

function normalizeDesignInput(v: unknown): ScienceDesignInput | null {
  if (!isObj(v)) return null;
  const field = str(v.field);
  if (!field) return null;
  return { field, value: str(v.value) ?? "", origin: str(v.origin) ?? "paper", ref: str(v.ref) ?? "" };
}

function normalizePublished(t: Obj): SciencePublished {
  const published = isObj(t.published) ? t.published : {};
  const totalObj = isObj(t.total) ? t.total : {};
  const modules: Record<string, number> = {};
  if (isObj(published.modules)) {
    for (const [k, v] of Object.entries(published.modules)) {
      const n = num(v);
      if (n !== null) modules[k] = n;
    }
  }
  return {
    total_kg: num(published.total_kg) ?? num(t.published_total_kg) ?? num(totalObj.published_kg) ?? num(totalObj.published),
    total_main_text_kg: num(published.total_main_text_kg),
    modules,
  };
}

function normalizeBandTrial(v: unknown): ScienceBandTrial | null {
  if (!isObj(v)) return null;
  const designId = str(v.design_id) ?? str(v.id);
  if (!designId) return null;
  return {
    design_id: designId,
    title: str(v.title) ?? designId,
    registry_id: str(v.registry_id),
    available: v.available !== false,
    reason: str(v.reason),
    total_t: scienceRange(v.total_t),
    within_band: typeof v.within_band === "boolean" ? v.within_band : null,
  };
}

function normalizeIndustryBand(v: unknown): ScienceIndustryBand | null {
  if (!isObj(v)) return null;
  return {
    low_t: num(v.low_t),
    high_t: num(v.high_t),
    trials_t: Array.isArray(v.trials_t) ? v.trials_t.filter((n): n is number => typeof n === "number" && Number.isFinite(n)) : [],
    source: str(v.source),
    note: str(v.note),
    demo_trials: Array.isArray(v.demo_trials)
      ? v.demo_trials.map(normalizeBandTrial).filter((row): row is ScienceBandTrial => row !== null)
      : [],
  };
}

function paperRecord(v: unknown): Record<string, string> {
  if (!isObj(v)) return {};
  const out: Record<string, string> = {};
  for (const [k, val] of Object.entries(v)) if (typeof val === "string") out[k] = val;
  return out;
}

function normalizeScienceTrial(t: unknown, key?: string): ScienceTrial | null {
  if (!isObj(t)) return null;
  const checks = Array.isArray(t.checks)
    ? t.checks.map(normalizeScienceCheck).filter((c): c is ScienceCheck => c !== null)
    : [];
  const legacy = checks.length === 0 ? legacyCheck(t) : null;
  const matched = strList(t.matched);
  const notMatched = strList(t.not_matched).length ? strList(t.not_matched) : strList(t.mismatched);
  const summary = Array.isArray(t.summary) ? strList(t.summary) : str(t.summary) ? [str(t.summary) as string] : [];
  if (summary.length === 0) {
    const explanation = str(t.explanation);
    if (explanation) summary.push(explanation);
    if (matched.length) summary.push(`Matched: ${matched.join("; ")}.`);
    if (notMatched.length) summary.push(`Did not match: ${notMatched.join("; ")}.`);
  }
  const id = str(t.id) ?? key ?? str(t.name) ?? "trial";
  return {
    id,
    name: str(t.name) ?? str(t.trial) ?? key ?? id,
    registry_id: str(t.registry_id),
    title: str(t.title),
    phase: str(t.phase),
    patients: num(t.patients),
    sites: num(t.sites),
    countries: strList(t.countries),
    duration_years: num(t.duration_years),
    published: normalizePublished(t),
    source: str(t.source),
    checks: legacy ? [legacy] : checks,
    findings: Array.isArray(t.findings) ? t.findings.map(normalizeFinding).filter((f): f is ScienceFinding => f !== null) : [],
    design_inputs: Array.isArray(t.design_inputs)
      ? t.design_inputs.map(normalizeDesignInput).filter((row): row is ScienceDesignInput => row !== null)
      : [],
    summary,
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
  const thresholds = isObj(d.thresholds_pct) ? d.thresholds_pct : {};
  return {
    schema_version: num(d.schema_version),
    title: str(d.title),
    simulated: d.simulated === true,
    data_label: str(d.data_label),
    paper: paperRecord(d.paper),
    parameter_set_version: str(d.parameter_set_version),
    seed: num(d.seed),
    draws: num(d.draws),
    thresholds_pct: { match: num(thresholds.match), close: num(thresholds.close) },
    engine: isObj(d.engine) ? { available: d.engine.available !== false, reason: str(d.engine.reason) } : null,
    trials,
    industry_band: normalizeIndustryBand(d.industry_band),
    how_to_reproduce: str(d.how_to_reproduce),
  };
}

/**
 * API shapes that are NOT part of the §5 contract (request/response envelopes from A4/A5/A7/A10).
 * They follow the API table in §5 and the owners' briefs; anything A8 had to guess is listed in
 * handoffs/A8.md ("Contract deviations") and normalised in ./normalize.ts so a small shape
 * difference degrades to an empty state instead of a crash.
 */
import type {
  ApprovalRequest,
  ForecastView,
  Levers,
  MetricRange,
  ScenarioResult,
  Signature,
  SignatureMeaning,
  SupplyView,
  TrialDesign,
  Visit,
} from "../contracts";

export interface ApiErrorBody {
  error: string;
  message: string;
  details?: Record<string, unknown>;
}

/** A5: GET /api/health */
export interface HealthResponse {
  status: string;
  offline: boolean;
  version?: string;
}

/** A4: a study document listed in the registry (e.g. the protocol PDF). */
export interface RegistryDocument {
  label: string | null;
  url: string | null;
  has_protocol: boolean;
  extraction_cached: boolean;
}

/** One A4 import note. `assumption` is set only when A4 tags it, or it is the visit-template sentence. */
export interface ImportNote {
  text: string;
  field: string | null;
  assumption: boolean;
  clears_when_present?: boolean;
}

/** A4: POST /api/import/ctgov/{nct_id} (extra fields are A4's import report). */
export interface ImportCtgovResponse {
  design: TrialDesign;
  raw_cached: boolean;
  missing_fields: string[];
  /** Plain-text notes, including facts. The assumption badge does not count these. */
  warnings: string[];
  notes: ImportNote[];
  field_sources: Record<string, string>;
  sponsor: string | null;
  collaborators: string[];
  acronym: string | null;
  overall_status: string | null;
  attribution: string | null;
  documents: RegistryDocument[];
}

/** A5: TrialDesign plus the version and hash from `X-Design-Version` and `ETag`. */
export interface DesignRecord {
  design: TrialDesign;
  version: number;
  etag: string | null;
}

/** A4: GET /api/import/ctgov — studies available in the local cache (work offline). */
export interface CachedStudy {
  nct_id: string;
  title: string;
  acronym: string | null;
  phase: string | null;
  drug_type: string | null;
  sites: number | null;
  sponsor: string | null;
  protocol_extraction_cached: boolean;
}

/** A4: one candidate visit from protocol extraction (AI draft — a human confirms each row). */
export interface ExtractionCandidate {
  visit: Visit;
  source_page: number | null;
  quote: string | null;
  confidence: number | null;
}

/** A4: POST /api/import/protocol */
export interface ProtocolExtractionResponse {
  extraction_id: string | null;
  candidates: ExtractionCandidate[];
  warnings: string[];
  excluded_columns: string[];
  method: string | null;
  model: string | null;
  soa_pages: number[];
  page_count: number | null;
  from_cache: boolean;
  notice: string | null;
}

/** Display adaptation of generated ForecastView, preserving missing detail and curve gaps. */
export interface ForecastDetail extends Omit<ForecastView, "months_to_full_enrollment" | "enrollment_curve"> {
  months_to_full_enrollment: MetricRange | null;
  milestone_dates: Record<string, MetricRange>;
  /** (month, p10, p50, p90) cumulative patients */
  enrollment_curve: Array<[number, number | null, number | null, number | null]>;
}

/** Display adaptation of generated SupplyView, preserving missing detail. */
export interface SupplyDetail extends Omit<SupplyView, "kits_needed" | "kits_produced" | "kits_wasted" | "waste_share" | "shipments" | "stockout_probability"> {
  kits_needed: MetricRange | null;
  kits_produced: MetricRange | null;
  kits_wasted: MetricRange | null;
  waste_share: MetricRange | null;
  shipments: MetricRange | null;
  stockout_probability: number | null;
}

/**
 * ScenarioResult with forecast/supply widened so a missing curve, kit count, or nested
 * range stays null. The generated ForecastView/SupplyView require those objects.
 */
export type ScenarioResultX = Omit<ScenarioResult, "forecast" | "supply"> & {
  forecast: ForecastDetail | null;
  supply: SupplyDetail | null;
};

export type ScenarioStatus = "draft" | "submitted" | "approved" | "rejected";

/** A5: GET /api/designs row (latest version of each design). */
export interface DesignSummary {
  id: string;
  version: number;
  title: string;
  source: string;
  registry_id: string | null;
  phase: string | null;
  enrollment_target: number | null;
  duration_months: number | null;
  site_count: number | null;
  visit_count: number | null;
  countries: string[];
  drug_type: string;
  missing_fields: string[];
  created_at: string | null;
}

/** A7: signature as returned by the approval view (manifestation + validity). */
export type SignatureView = Signature & {
  signer_name?: string | null;
  manifestation?: string | null;
  /** null when the record cannot be resolved (validity unknown) */
  valid?: boolean | null;
  reason?: string | null;
};

/** A7: GET /api/approvals/{id} — ApprovalRequest plus workflow details. */
export type ApprovalView = Omit<ApprovalRequest, "signatures"> & {
  signatures: SignatureView[];
  next_meaning?: string | null;
  record_changed?: boolean;
  author_name?: string | null;
  title?: string | null;
  reject_reason?: string | null;
};

/**
 * A5: saved scenario. GET /api/scenarios returns summaries (metrics only, no levers/result);
 * GET /api/scenarios/{id} returns the full row with the approval embedded.
 */
export interface SavedScenario {
  id: string;
  lineage_id: string;
  version: number;
  parent_id: string | null;
  name: string;
  design_id: string;
  design_version: number | null;
  status: ScenarioStatus;
  author: string;
  created_at: string | null;
  parameter_set_version: string | null;
  record_hash: string | null;
  metrics: Partial<Record<string, MetricRange>>;
  /** null in list summaries — load the full scenario to get them */
  levers: Levers | null;
  result: ScenarioResultX | null;
  approval_id: string | null;
  approval: ApprovalView | null;
}

export interface SaveScenarioRequest {
  design_id: string;
  design_version: number;
  name: string;
  levers: Levers;
}

export interface ProtocolReviewStats {
  accepted: number;
  edited: number;
  rejected: number;
  /** Rows accepted by "Accept all remaining" without opening them. A4 excludes these from the accuracy share. */
  bulk_accepted: number;
}

/** One "top driver" of a metric's variance; share is 0..1 of total variance. */
export interface Driver {
  parameter_id: string;
  share: number;
  label?: string | null;
  unit?: string | null;
}

/** A5: POST /api/scenarios/compare — per-draw b − a deltas (common random numbers). */
export interface CompareResult {
  deltas: Record<string, MetricRange>;
  a_metrics: Record<string, MetricRange>;
  b_metrics: Record<string, MetricRange>;
  same_parameter_set: boolean;
  parameter_set_version: string | null;
  warnings: string[];
}

export interface SignRequest {
  meaning: SignatureMeaning;
  pin: string;
  reason?: string;
}

export type { ApprovalRequest };

// ---------- Science check (A10 science/out/results.json, normalised) ----------
/** A range from the science file. `unit` is whatever the file says (industry-band totals are tonnes labelled kg_co2e). */
export interface ScienceRange {
  p10: number;
  p50: number;
  p90: number;
  unit: string;
}

export type ScienceRowStatus = "match" | "close" | "gap" | "not_reported" | "unavailable";

export interface ScienceModuleRow {
  module: string;
  label: string;
  published_kg: number | null;
  ours: ScienceRange | null;
  /** (ours.p50 − published) / published × 100 */
  diff_pct: number | null;
  published_within_range: boolean | null;
  status: ScienceRowStatus;
  explanation: string | null;
}

export interface ScienceLineChange {
  line_id: string;
  module: string;
  item: string;
  paper_factor: number | null;
  paper_kg: number | null;
  library_factor_p50: number | null;
  library_kg: ScienceRange | null;
  parameter_ids: string[];
  kind: string;
  note: string;
}

/** One reproduction: method, corrected, library, engine_library, or engine_paper_factors. */
export interface ScienceCheck {
  id: string;
  title: string;
  description: string;
  available: boolean;
  unavailable_reason: string | null;
  total: ScienceModuleRow | null;
  modules: ScienceModuleRow[];
  notes: string[];
  line_changes: ScienceLineChange[];
}

export interface ScienceFinding {
  id: string;
  severity: "large" | "medium" | "info" | string;
  summary: string;
  detail: string;
  lines: string[];
  effect_kg: number | null;
}

export interface ScienceDesignInput {
  field: string;
  value: string;
  origin: string;
  ref: string;
}

export interface SciencePublished {
  total_kg: number | null;
  total_main_text_kg: number | null;
  modules: Record<string, number>;
}

export interface ScienceTrial {
  id: string;
  name: string;
  registry_id: string | null;
  title: string | null;
  phase: string | null;
  patients: number | null;
  sites: number | null;
  countries: string[];
  duration_years: number | null;
  published: SciencePublished;
  source: string | null;
  checks: ScienceCheck[];
  findings: ScienceFinding[];
  design_inputs: ScienceDesignInput[];
  /** Two sentences on match quality. */
  summary: string[];
}

export interface ScienceBandTrial {
  design_id: string;
  title: string;
  registry_id: string | null;
  available: boolean;
  reason: string | null;
  /**
   * Tonnes CO₂e. A10's file sets `unit` to `kg_co2e` but the numbers are tonnes
   * (they sit on the 1,437–2,498 t band). Do not pass them through formatCo2e.
   */
  total_t: ScienceRange | null;
  within_band: boolean | null;
}

export interface ScienceIndustryBand {
  low_t: number | null;
  high_t: number | null;
  trials_t: number[];
  source: string | null;
  note: string | null;
  demo_trials: ScienceBandTrial[];
}

export interface ScienceResults {
  schema_version: number | null;
  title: string | null;
  simulated: boolean;
  data_label: string | null;
  paper: Record<string, string>;
  parameter_set_version: string | null;
  seed: number | null;
  draws: number | null;
  thresholds_pct: { match: number | null; close: number | null };
  engine: { available: boolean; reason: string | null } | null;
  trials: ScienceTrial[];
  industry_band: ScienceIndustryBand | null;
  how_to_reproduce: string | null;
}

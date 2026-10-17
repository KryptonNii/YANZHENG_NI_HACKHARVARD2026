/**
 * API shapes that are NOT part of the §5 contract (request/response envelopes from A4/A5/A7/A10).
 * They follow the API table in §5 and the owners' briefs; anything A8 had to guess is listed in
 * handoffs/A8.md ("Contract deviations") and normalised in ./normalize.ts so a small shape
 * difference degrades to an empty state instead of a crash.
 */
import type {
  ApprovalRequest,
  Levers,
  MetricRange,
  ScenarioResult,
  Signature,
  SignatureMeaning,
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

/** A4: POST /api/import/ctgov/{nct_id} */
export interface ImportCtgovResponse {
  design: TrialDesign;
  raw_cached: boolean;
  missing_fields: string[];
  warnings: string[];
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
  candidates: ExtractionCandidate[];
  warnings: string[];
}

/** Proposed optional extension of ScenarioResult (handoffs/A8_CONTRACT_CHANGES.md): A3 ForecastResult. */
export interface ForecastDetail {
  months_to_full_enrollment: MetricRange | null;
  milestone_dates: Record<string, MetricRange>;
  /** (month, p10, p50, p90) cumulative patients */
  enrollment_curve: Array<[number, number, number, number]>;
}

/** Proposed optional extension of ScenarioResult (handoffs/A8_CONTRACT_CHANGES.md): A3 SupplyResult. */
export interface SupplyDetail {
  kits_needed: MetricRange | null;
  kits_produced: MetricRange | null;
  kits_wasted: MetricRange | null;
  waste_share: MetricRange | null;
  shipments: MetricRange | null;
  stockout_probability: number | null;
}

/** ScenarioResult plus the optional extensions the UI renders when the API provides them. */
export type ScenarioResultX = ScenarioResult & {
  forecast?: ForecastDetail | null;
  supply?: SupplyDetail | null;
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
  enrollment_target: number;
  duration_months: number;
  site_count: number;
  visit_count: number;
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
  name: string;
  levers: Levers;
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
export interface ScienceModuleRow {
  module: string;
  published_kg: number | null;
  ours: MetricRange | null;
  pct_diff: number | null;
  note: string | null;
}

export interface ScienceTrial {
  id: string;
  name: string;
  registry_id: string | null;
  paper_url: string | null;
  paper_title: string | null;
  published_total_kg: number | null;
  ours_total: MetricRange | null;
  pct_diff: number | null;
  modules: ScienceModuleRow[];
  matched: string[];
  not_matched: string[];
  explanation: string | null;
  check: string | null;
}

export interface ScienceResults {
  trials: ScienceTrial[];
  generated_at: string | null;
  notes: string[];
}

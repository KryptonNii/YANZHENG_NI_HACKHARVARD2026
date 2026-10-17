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

/** A5: saved scenario row (versioned; immutable once submitted). */
export interface SavedScenario {
  id: string;
  design_id: string;
  name: string;
  version: number;
  levers: Levers;
  result: ScenarioResultX | null;
  parameter_set_version: string | null;
  author: string;
  status: ScenarioStatus;
  created_at: string | null;
  approval_id: string | null;
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

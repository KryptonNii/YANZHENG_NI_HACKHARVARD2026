/**
 * Typed API client. Every request carries the demo identity headers (X-User / X-Role).
 * Errors become ApiError with the API's plain-English message (§5 error shape); unless a call
 * passes `silent: true`, the message is also broadcast to the toast layer.
 */
import type { Levers, Parameter, TrialDesign, Visit } from "../contracts";
import { identityHeaders } from "../identity";
import {
  asArray,
  normalizeApproval,
  normalizeCachedStudies,
  normalizeCompare,
  normalizeDesignSummary,
  normalizeDrivers,
  normalizeExtraction,
  normalizeImport,
  normalizeSavedScenario,
  normalizeScenarioResult,
  normalizeScience,
} from "./normalize";
import type {
  ApiErrorBody,
  ApprovalView,
  CachedStudy,
  CompareResult,
  DesignSummary,
  Driver,
  HealthResponse,
  ImportCtgovResponse,
  ProtocolExtractionResponse,
  SavedScenario,
  SaveScenarioRequest,
  ScenarioResultX,
  ScienceResults,
  SignRequest,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

type ErrorListener = (err: ApiError) => void;
const errorListeners = new Set<ErrorListener>();

/** Subscribe to API errors (the toast layer does). Returns an unsubscribe function. */
export function onApiError(listener: ErrorListener): () => void {
  errorListeners.add(listener);
  return () => {
    errorListeners.delete(listener);
  };
}

export const API_BASE = "/api";

export interface RequestOptions {
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  /** Do not toast this error (the caller shows it inline). */
  silent?: boolean;
}

export function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    // non-JSON error (proxy error page, empty body)
  }
  if (body && typeof body === "object") {
    const b = body as Partial<ApiErrorBody> & { detail?: unknown };
    if (typeof b.error === "string" && typeof b.message === "string") {
      return new ApiError(res.status, b.error, b.message, b.details ?? {});
    }
    // FastAPI default shapes, in case a route bypasses the §5 error handler
    if (typeof b.detail === "string") return new ApiError(res.status, `http_${res.status}`, b.detail);
    if (b.detail && typeof b.detail === "object") {
      const d = b.detail as Partial<ApiErrorBody>;
      if (typeof d.error === "string" && typeof d.message === "string") {
        return new ApiError(res.status, d.error, d.message, d.details ?? {});
      }
      if (Array.isArray(b.detail)) {
        const first = b.detail[0] as { msg?: string; loc?: unknown[] } | undefined;
        const where = first?.loc ? ` (${first.loc.join(".")})` : "";
        return new ApiError(res.status, "validation_error", `${first?.msg ?? "Invalid request"}${where}`, {
          detail: b.detail,
        });
      }
    }
  }
  if (res.status === 502 || res.status === 503 || res.status === 504) {
    return new ApiError(res.status, "api_unreachable", "The TrialPilot API is not reachable right now.");
  }
  return new ApiError(res.status, `http_${res.status}`, `Request failed (HTTP ${res.status}).`);
}

export async function request<T = unknown>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...identityHeaders() };
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { method, headers, body, signal: opts.signal });
  } catch (err) {
    if (isAbort(err)) throw err;
    const e = new ApiError(0, "network_error", "Can't reach the TrialPilot API. Check that the server is running.");
    if (!opts.silent) errorListeners.forEach((l) => l(e));
    throw e;
  }
  if (!res.ok) {
    const e = await parseError(res);
    if (!opts.silent) errorListeners.forEach((l) => l(e));
    throw e;
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const enc = encodeURIComponent;

/** Every endpoint the web app calls (§5 API table; envelopes as implemented by A4/A5/A7). */
export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>("GET", "/health", { signal, silent: true }),

  // ---- A4 importers ----
  importCtgov: async (nctId: string, opts: RequestOptions = {}): Promise<ImportCtgovResponse> =>
    normalizeImport(await request("POST", `/import/ctgov/${enc(nctId)}`, opts)),
  /** Studies in A4's local cache (they import offline). */
  cachedStudies: async (opts: RequestOptions = {}): Promise<CachedStudy[]> =>
    normalizeCachedStudies(await request("GET", "/import/ctgov", opts)),
  /** Extract a schedule of activities from an uploaded PDF, or from the registry protocol of `nctId`. */
  importProtocol: async (src: { file?: File; nctId?: string }, designId?: string, opts: RequestOptions = {}): Promise<ProtocolExtractionResponse> => {
    const form = new FormData();
    if (src.file) form.append("file", src.file);
    else if (src.nctId) form.append("nct_id", src.nctId);
    if (designId) form.append("design_id", designId);
    return normalizeExtraction(await request("POST", "/import/protocol", { ...opts, form }));
  },
  /** A4 validates the human-confirmed visits and returns the new design (A5 stores it). */
  applyProtocol: async (design: TrialDesign, visits: Visit[], extractionId: string | null, opts: RequestOptions = {}): Promise<TrialDesign> => {
    const res = await request<{ design?: TrialDesign }>("POST", "/import/protocol/apply", {
      ...opts,
      body: { design, visits, extraction_id: extractionId },
    });
    return res?.design ?? { ...design, visits, missing_fields: design.missing_fields.filter((f) => f !== "visits") };
  },
  /** Accepted / edited / rejected counts — the extraction accuracy metric. */
  logProtocolReview: (body: { extraction_id: string; design_id?: string; accepted: number; edited: number; rejected: number }, opts: RequestOptions = {}) =>
    request("POST", "/import/protocol/review", { ...opts, body }),

  // ---- A5 designs (POST with an existing id stores a new version) ----
  listDesigns: async (opts: RequestOptions = {}): Promise<DesignSummary[]> =>
    asArray<unknown>(await request("GET", "/designs", opts), "designs")
      .map(normalizeDesignSummary)
      .filter((d): d is DesignSummary => d !== null),
  getDesign: (id: string, opts: RequestOptions = {}) => request<TrialDesign>("GET", `/designs/${enc(id)}`, opts),
  saveDesign: (design: TrialDesign, opts: RequestOptions = {}) => request<TrialDesign>("POST", "/designs", { ...opts, body: design }),

  // ---- A5 scenarios ----
  compute: async (designId: string, levers: Levers, opts: RequestOptions = {}): Promise<ScenarioResultX> =>
    normalizeScenarioResult(await request("POST", "/scenarios/compute", { ...opts, body: { design_id: designId, levers } })),
  /** Top-5 drivers for an unsaved lever set. */
  drivers: async (designId: string, levers: Levers, metric: string, opts: RequestOptions = {}): Promise<Driver[]> =>
    normalizeDrivers(await request("POST", "/scenarios/drivers", { ...opts, body: { design_id: designId, levers, metric, top: 5 } })),
  compare: async (aId: string, bId: string, opts: RequestOptions = {}): Promise<CompareResult> =>
    normalizeCompare(await request("POST", "/scenarios/compare", { ...opts, body: { a_id: aId, b_id: bId } })),
  listScenarios: async (designId?: string, opts: RequestOptions = {}): Promise<SavedScenario[]> => {
    const q = designId ? `?design_id=${enc(designId)}` : "";
    const rows = asArray<unknown>(await request("GET", `/scenarios${q}`, opts), "scenarios");
    return rows.map(normalizeSavedScenario).filter((s) => !designId || s.design_id === designId);
  },
  getScenario: async (id: string, opts: RequestOptions = {}): Promise<SavedScenario> =>
    normalizeSavedScenario(await request("GET", `/scenarios/${enc(id)}`, opts)),
  saveScenario: async (req: SaveScenarioRequest, opts: RequestOptions = {}): Promise<SavedScenario> =>
    normalizeSavedScenario(await request("POST", "/scenarios", { ...opts, body: req })),
  /** New draft version in the same lineage (the base row is never modified). */
  newVersion: async (baseId: string, patch: { levers?: Levers; name?: string }, opts: RequestOptions = {}): Promise<SavedScenario> =>
    normalizeSavedScenario(await request("POST", `/scenarios/${enc(baseId)}/versions`, { ...opts, body: patch })),
  /** Freezes the draft and creates the ApprovalRequest (A7); returns the scenario with it embedded. */
  submitScenario: async (id: string, opts: RequestOptions = {}): Promise<SavedScenario> =>
    normalizeSavedScenario(await request("POST", `/scenarios/${enc(id)}/submit`, { ...opts, body: {} })),
  exportUrl: (scenarioId: string, format: "csv" | "pdf") => `${API_BASE}/export/scenario/${enc(scenarioId)}.${format}`,

  // ---- A5 parameter library ----
  params: async (opts: RequestOptions = {}): Promise<Parameter[]> =>
    asArray<Parameter>(await request("GET", "/params", opts), "parameters"),

  // ---- A7 approvals ----
  listApprovals: async (opts: RequestOptions = {}): Promise<ApprovalView[]> =>
    asArray<unknown>(await request("GET", "/approvals", opts), "items").map(normalizeApproval),
  getApproval: async (id: string, opts: RequestOptions = {}): Promise<ApprovalView> =>
    normalizeApproval(await request("GET", `/approvals/${enc(id)}`, opts)),
  sign: async (approvalId: string, req: SignRequest, opts: RequestOptions = {}): Promise<ApprovalView> => {
    const res = await request("POST", `/approvals/${enc(approvalId)}/sign`, { ...opts, body: req });
    try {
      return normalizeApproval(res);
    } catch {
      // the endpoint returned the Signature only: re-read the request to get its new status
      return api.getApproval(approvalId, opts);
    }
  },

  // ---- A10 science check (served by A5) ----
  science: async (opts: RequestOptions = {}): Promise<ScienceResults> =>
    normalizeScience(await request("GET", "/science/results", opts)),
};

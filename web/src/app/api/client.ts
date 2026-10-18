/**
 * Typed API client. Every request carries the demo identity headers (X-User / X-Role).
 * Errors become ApiError with the API's plain-English message (§5 error shape); unless a call
 * passes `silent: true`, every ApiError the client throws (HTTP, network, or a reply it rejects
 * itself) is also broadcast to the toast layer, once.
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
  DesignRecord,
  DesignSummary,
  Driver,
  HealthResponse,
  ImportCtgovResponse,
  ProtocolExtractionResponse,
  ProtocolReviewStats,
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

/** Throw `err`, broadcasting it to the toast layer first unless the call is silent. */
function raise(err: ApiError, opts: { silent?: boolean }): never {
  if (!opts.silent) errorListeners.forEach((l) => l(err));
  throw err;
}

export const API_BASE = "/api";

export interface RequestOptions {
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  /** Do not toast this error (the caller shows it inline). */
  silent?: boolean;
  /** A5 design concurrency: If-Match the ETag (`design_hash`) of the version being replaced. */
  ifMatch?: string;
  /** Pinned design version for compute, drivers, save and new scenario versions. */
  designVersion?: number | null;
}

/** Plain-English text for A5's 409 design_changed. */
export function designConflictMessage(err: ApiError): string | null {
  if (err.code !== "design_changed") return null;
  const version = err.details.version ?? err.details.design_version ?? err.details.current_version;
  const shown = typeof version === "number" ? `design v${version}` : "a newer version";
  return `This design changed while you were editing — it is now ${shown}. Reload it before saving so a confirmed protocol schedule is not replaced.`;
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

/**
 * Render's free plan sleeps the public demo after 15 idle minutes and restarts it on every deploy;
 * until the API is back, Render's proxy answers 502/503/504 with its own non-JSON page. Requests
 * that change nothing on the server wait for /api/health and are sent once more.
 */
const WAKE_TIMEOUT_MS = 90_000;
const WAKE_POLL_MS = 3_000;
const STATELESS_POSTS = new Set(["/scenarios/compute", "/scenarios/drivers", "/scenarios/compare"]);

function isRepeatable(method: string, path: string): boolean {
  return method === "GET" || (method === "POST" && STATELESS_POSTS.has(path));
}

function isProxyGap(res: Response): boolean {
  return [502, 503, 504].includes(res.status) && !(res.headers.get("Content-Type") ?? "").includes("json");
}

function pause(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    if (signal?.aborted) onAbort();
    else signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** Poll /api/health until it answers 200 (true) or WAKE_TIMEOUT_MS passes (false). */
async function waitForWake(signal?: AbortSignal): Promise<boolean> {
  const deadline = Date.now() + WAKE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await pause(WAKE_POLL_MS, signal);
    try {
      if ((await fetch(`${API_BASE}/health`, { headers: { Accept: "application/json" }, signal })).ok) return true;
    } catch (err) {
      if (isAbort(err)) throw err;
    }
  }
  return false;
}

export async function requestFull<T = unknown>(method: string, path: string, opts: RequestOptions = {}): Promise<{ data: T; response: Response }> {
  const headers: Record<string, string> = { Accept: "application/json", ...identityHeaders() };
  if (opts.ifMatch) headers["If-Match"] = `"${opts.ifMatch.replaceAll('"', "")}"`;
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const send = () => fetch(`${API_BASE}${path}`, { method, headers, body, signal: opts.signal });
  let res: Response;
  try {
    res = await send();
    if (isProxyGap(res) && isRepeatable(method, path) && (await waitForWake(opts.signal))) res = await send();
  } catch (err) {
    if (isAbort(err)) throw err;
    raise(new ApiError(0, "network_error", "Can't reach the TrialPilot API. Check that the server is running."), opts);
  }
  if (!res.ok) raise(await parseError(res), opts);
  if (res.status === 204) return { data: undefined as T, response: res };
  const text = await res.text();
  return { data: (text ? JSON.parse(text) : undefined) as T, response: res };
}

export async function request<T = unknown>(method: string, path: string, opts: RequestOptions = {}): Promise<T> {
  const { data } = await requestFull<T>(method, path, opts);
  return data;
}

function designRecord(design: TrialDesign, response: Response, opts: RequestOptions): DesignRecord {
  const raw = Number(response.headers.get("X-Design-Version"));
  const etag = response.headers.get("ETag")?.replace(/^W\//, "").replaceAll('"', "").trim() || null;
  if (!Number.isInteger(raw) || raw < 1 || !etag || response.headers.get("ETag")?.startsWith("W/")) {
    raise(new ApiError(502, "design_version_missing", "The API did not provide a valid design version and strong ETag. Reload before editing or computing."), opts);
  }
  return { design, version: raw, etag };
}

function withVersion(body: Record<string, unknown>, version: number | null | undefined): Record<string, unknown> {
  if (typeof version === "number" && version >= 1) return { ...body, design_version: version };
  return body;
}

const enc = encodeURIComponent;

/** Every endpoint the web app calls (§5 API table; envelopes as implemented by A4/A5/A7). */
export const api = {
  health: (signal?: AbortSignal) => request<HealthResponse>("GET", "/health", { signal, silent: true }),

  // ---- A4 importers ----
  importCtgov: async (nctId: string, { refresh, ...opts }: RequestOptions & { refresh?: boolean } = {}): Promise<ImportCtgovResponse> =>
    normalizeImport(await request("POST", `/import/ctgov/${enc(nctId)}${refresh ? "?refresh=true" : ""}`, opts)),
  /** Studies in A4's local cache (they import offline). */
  cachedStudies: async (opts: RequestOptions = {}): Promise<CachedStudy[]> =>
    normalizeCachedStudies(await request("GET", "/import/ctgov", opts)),
  /** Extract a schedule of activities from an uploaded PDF, or from the registry protocol of `nctId`. */
  importProtocol: async (src: { file?: File; nctId?: string; refresh?: boolean }, designId?: string, opts: RequestOptions = {}): Promise<ProtocolExtractionResponse> => {
    const form = new FormData();
    if (src.file) form.append("file", src.file);
    else if (src.nctId) form.append("nct_id", src.nctId);
    if (designId) form.append("design_id", designId);
    if (src.refresh) form.append("refresh", "true");
    return normalizeExtraction(await request("POST", "/import/protocol", { ...opts, form }));
  },
  /** A4 validates the human-confirmed visits and returns the new design (A5 stores it). */
  applyProtocol: async (design: TrialDesign, visits: Visit[], extractionId: string | null, opts: RequestOptions = {}): Promise<TrialDesign> => {
    const res = await request<{ design?: TrialDesign }>("POST", "/import/protocol/apply", {
      ...opts,
      body: { design, visits, extraction_id: extractionId },
    });
    if (!res?.design) raise(new ApiError(502, "protocol_design_missing", "The API did not return the reviewed design. Nothing was saved; retry applying the protocol."), opts);
    return res.design;
  },
  /** Accepted / edited / rejected counts — the extraction accuracy metric. `bulk_accepted` is rows never opened. */
  logProtocolReview: (body: { extraction_id: string; design_id?: string } & ProtocolReviewStats, opts: RequestOptions = {}) =>
    request("POST", "/import/protocol/review", { ...opts, body }),

  // ---- A5 designs (POST with an existing id stores a new version) ----
  listDesigns: async (opts: RequestOptions = {}): Promise<DesignSummary[]> =>
    asArray<unknown>(await request("GET", "/designs", opts), "designs")
      .map(normalizeDesignSummary)
      .filter((d): d is DesignSummary => d !== null),
  getDesign: async (id: string, opts: RequestOptions = {}): Promise<DesignRecord> => {
    const { data, response } = await requestFull<TrialDesign>("GET", `/designs/${enc(id)}`, opts);
    return designRecord(data, response, opts);
  },
  /**
   * Store a design. With `ifMatch` (the ETag of the version being replaced), A5 refuses a stale
   * tag with 409 design_changed, shown as the plain designConflictMessage sentence.
   */
  saveDesign: async (design: TrialDesign, opts: RequestOptions = {}): Promise<DesignRecord> => {
    let saved: { data: TrialDesign; response: Response };
    try {
      saved = await requestFull<TrialDesign>("POST", "/designs", { ...opts, silent: true, body: design });
    } catch (err) {
      if (err instanceof ApiError) {
        const message = err.code === "design_changed" ? (designConflictMessage(err) ?? err.message) : err.message;
        raise(message === err.message ? err : new ApiError(err.status, err.code, message, err.details), opts);
      }
      throw err;
    }
    return designRecord(saved.data, saved.response, opts);
  },

  // ---- A5 scenarios ----
  compute: async (designId: string, levers: Levers, opts: RequestOptions = {}): Promise<ScenarioResultX> => {
    const { data, response } = await requestFull("POST", "/scenarios/compute", { ...opts, body: withVersion({ design_id: designId, levers }, opts.designVersion) });
    if (opts.designVersion != null && Number(response.headers.get("X-Design-Version")) !== opts.designVersion) {
      raise(new ApiError(502, "compute_version_mismatch", "The calculation did not confirm the design version on screen. Retry before saving."), opts);
    }
    return normalizeScenarioResult(data);
  },
  /** Top-5 drivers for an unsaved lever set, on the same design version as the numbers on screen. */
  drivers: async (designId: string, levers: Levers, metric: string, opts: RequestOptions = {}): Promise<Driver[]> =>
    normalizeDrivers(
      await request("POST", "/scenarios/drivers", {
        ...opts,
        body: withVersion({ design_id: designId, levers, metric, top: 5 }, opts.designVersion),
      }),
    ),
  compare: async (aId: string, bId: string, opts: RequestOptions = {}): Promise<CompareResult> =>
    normalizeCompare(await request("POST", "/scenarios/compare", { ...opts, body: { a_id: aId, b_id: bId } })),
  listScenarios: async (designId?: string, opts: RequestOptions = {}): Promise<SavedScenario[]> => {
    const q = designId ? `?design_id=${enc(designId)}` : "";
    const rows = asArray<unknown>(await request("GET", `/scenarios${q}`, opts), "scenarios");
    return rows.map(normalizeSavedScenario).filter((s) => !designId || s.design_id === designId);
  },
  getScenario: async (id: string, opts: RequestOptions = {}): Promise<SavedScenario> =>
    normalizeSavedScenario(await request("GET", `/scenarios/${enc(id)}`, opts)),
  deleteScenario: (id: string, opts: RequestOptions = {}): Promise<void> =>
    request<void>("DELETE", `/scenarios/${enc(id)}`, opts),
  saveScenario: async (req: SaveScenarioRequest, opts: RequestOptions = {}): Promise<SavedScenario> =>
    normalizeSavedScenario(await request("POST", "/scenarios", { ...opts, body: req })),
  /** New draft version in the same lineage (the base row is never modified). */
  newVersion: async (baseId: string, patch: { levers?: Levers; name?: string; design_version?: number }, opts: RequestOptions = {}): Promise<SavedScenario> =>
    normalizeSavedScenario(await request("POST", `/scenarios/${enc(baseId)}/versions`, { ...opts, body: withVersion(patch, patch.design_version) })),
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

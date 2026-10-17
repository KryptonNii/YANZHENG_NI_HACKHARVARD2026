/**
 * In-browser MOCK API (VITE_MOCK_API=1 only). Patches window.fetch for /api/* so the real client
 * code path is exercised. Mirrors the envelopes of A5's routes and A7's approval rules (no
 * self-approval, order enforced, PIN re-authentication with A7's demo PINs). Data is fictional and
 * labelled as such everywhere.
 */
import type { ApprovalRequest, Levers, MetricRange, Signature, SignatureMeaning, TrialDesign } from "../../contracts";
import type { SavedScenario, ScenarioResultX } from "../types";
import { MOCK_DESIGN, MOCK_PARAMS } from "./data";
import { mockCompute, mockDrivers } from "./engine";

/** Same demo PINs as A7's roles.py (fictional users). */
export const MOCK_PINS: Record<string, string> = { "alex.author": "1111", "riley.reviewer": "2222", "sam.qa": "3333" };
const NAMES: Record<string, string> = { "alex.author": "Alex Author", "riley.reviewer": "Riley Reviewer", "sam.qa": "Sam QA" };
const STORE_KEY = "tp.mock.store.v2";

type Row = Omit<SavedScenario, "approval" | "metrics"> & { levers: Levers; result: ScenarioResultX };

interface Store {
  designs: TrialDesign[];
  scenarios: Row[];
  approvals: ApprovalRequest[];
}

const fresh = (): Store => ({ designs: [structuredClone(MOCK_DESIGN)], scenarios: [], approvals: [] });

function load(): Store {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw) as Store;
  } catch {
    // ignore
  }
  return fresh();
}

let store: Store = load();
const persist = () => {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(store));
  } catch {
    // ignore
  }
};

/** Test hook. */
export function resetMockStore(): void {
  store = fresh();
  persist();
}

const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
const hex = (n = 64) => Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join("");

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
function err(status: number, error: string, message: string, details: Record<string, unknown> = {}): Response {
  return json({ error, message, details }, status);
}
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

type Handler = (m: RegExpMatchArray, req: { body: unknown; headers: Headers; url: URL; form: FormData | null }) => Response | Promise<Response>;
const routes: Array<[string, RegExp, Handler]> = [];
const on = (method: string, pattern: RegExp, h: Handler) => routes.push([method, pattern, h]);

const actor = (h: Headers) => ({ user: h.get("X-User") ?? "", role: h.get("X-Role") ?? "viewer" });
const HEADLINE = ["cost_usd", "site_staff_hours", "patient_travel_hours", "co2e_kg", "duration_months", "drug_waste_share"] as const;
const metricsOf = (r: ScenarioResultX) => Object.fromEntries(HEADLINE.map((k) => [k, r[k]]));

function approvalView(a: ApprovalRequest) {
  const next = a.status === "pending" ? (a.required_meanings.find((x) => !a.signatures.some((s) => s.meaning === x)) ?? null) : null;
  return {
    ...a,
    author_name: NAMES[a.author] ?? a.author,
    next_meaning: next,
    record_changed: false,
    signatures: a.signatures.map((s) => ({ ...s, signer_name: NAMES[s.signer] ?? s.signer, valid: true, reason: null })),
  };
}

const summary = (s: Row) => {
  const { levers: _l, result, ...rest } = s;
  return { ...rest, metrics: metricsOf(result) };
};
const full = (s: Row) => {
  const a = s.approval_id ? store.approvals.find((x) => x.id === s.approval_id) : undefined;
  return { ...s, metrics: metricsOf(s.result), approval: a ? approvalView(a) : null };
};

function designOr404(id: unknown): TrialDesign | Response {
  return store.designs.find((x) => x.id === id) ?? err(404, "design_not_found", `No trial design with id ${JSON.stringify(id)}.`);
}

function requireEditor(h: Headers): Response | null {
  const me = actor(h);
  if (!me.user) return err(401, "identity_required", "Send the demo identity headers X-User and X-Role with every change.");
  if (me.role === "viewer") return err(403, "forbidden_role", "The viewer role cannot change data.");
  return null;
}

function validLevers(l: Levers | undefined): string | null {
  if (!l) return "levers are required";
  if (l.remote_monitoring_share < 0 || l.remote_monitoring_share > 1) return "remote_monitoring_share must be between 0 and 1";
  if (l.local_lab_share < 0 || l.local_lab_share > 1) return "local_lab_share must be between 0 and 1";
  return null;
}

on("GET", /^\/api\/health$/, () => json({ status: "ok", offline: false, version: "mock" }));

on("POST", /^\/api\/import\/ctgov\/([^/]+)$/, (m) => {
  const id = decodeURIComponent(m[1]).toUpperCase();
  if (!/^NCT\d{8}$/.test(id)) return err(400, "invalid_registry_id", `“${id}” is not a valid ClinicalTrials.gov ID (NCT + 8 digits).`);
  const design = store.designs.find((d) => d.id === MOCK_DESIGN.id) ?? structuredClone(MOCK_DESIGN);
  return json({
    design,
    raw_cached: true,
    missing_fields: design.missing_fields,
    warnings: [`Mock API: ClinicalTrials.gov is not contacted; ${id} returns the fictional mock trial.`],
  });
});

on("POST", /^\/api\/import\/protocol$/, async (_m, { form }) => {
  await delay(400);
  const file = form?.get("file");
  if (!(file instanceof File)) return err(422, "file_required", "Attach a PDF in the “file” field.");
  return json({
    candidates: MOCK_DESIGN.visits.slice(0, 6).map((v, i) => ({
      visit: v,
      source_page: 12 + i,
      quote: `(mock quote) ${v.label}: ${v.procedures.map((p) => p.label).join(", ")}`,
      confidence: Math.round((0.92 - i * 0.07) * 100) / 100,
    })),
    warnings: ["Mock API: no model was called; these candidates are fictional."],
  });
});

on("GET", /^\/api\/designs$/, () =>
  json(
    store.designs.map((d) => ({
      id: d.id,
      version: 1,
      title: d.title,
      source: d.source,
      registry_id: d.registry_id,
      phase: d.phase,
      enrollment_target: d.enrollment_target,
      duration_months: d.duration_months,
      site_count: d.sites.length,
      visit_count: d.visits.length,
      countries: [...new Set(d.sites.map((s) => s.country))].sort(),
      drug_type: d.drug_type,
      missing_fields: d.missing_fields,
      created_at: new Date().toISOString(),
      created_by: "mock",
    })),
  ),
);
on("GET", /^\/api\/designs\/([^/]+)$/, (m) => {
  const d = designOr404(decodeURIComponent(m[1]));
  return d instanceof Response ? d : json(d);
});
on("POST", /^\/api\/designs$/, (_m, { body, headers }) => {
  const denied = requireEditor(headers);
  if (denied) return denied;
  const d = { ...(body as TrialDesign) };
  if (!d.id) d.id = uuid();
  const i = store.designs.findIndex((x) => x.id === d.id);
  if (i >= 0) store.designs[i] = d;
  else store.designs.push(d);
  persist();
  return json(d, i >= 0 ? 200 : 201);
});

on("POST", /^\/api\/scenarios\/compute$/, async (_m, { body }) => {
  const b = body as { design_id?: string; levers?: Levers };
  const d = designOr404(b.design_id);
  if (d instanceof Response) return d;
  const bad = validLevers(b.levers);
  if (bad) return err(422, "invalid_levers", `Invalid levers: ${bad}`);
  await delay(120 + Math.random() * 120);
  return json(mockCompute(d, b.levers!));
});
on("POST", /^\/api\/scenarios\/drivers$/, async (_m, { body }) => {
  const b = body as { metric?: string };
  await delay(80);
  return json({ metric: b.metric ?? "co2e_kg", parameter_set_version: "mock-1", drivers: mockDrivers(b.metric ?? "co2e_kg"), warnings: [] });
});
on("POST", /^\/api\/scenarios\/compare$/, (_m, { body }) => {
  const { a_id, b_id } = body as { a_id: string; b_id: string };
  const a = store.scenarios.find((s) => s.id === a_id);
  const b = store.scenarios.find((s) => s.id === b_id);
  if (!a || !b) return err(404, "scenario_not_found", "No saved scenario with this id.");
  if (a.design_id !== b.design_id) return err(422, "compare_needs_same_design", "Per-draw comparison needs both scenarios on the same trial design version.");
  // mock "per draw" deltas: P50 difference with a band — illustrative only
  const deltas: Record<string, MetricRange> = {};
  for (const k of HEADLINE) {
    const d = b.result[k].p50 - a.result[k].p50;
    const w = Math.abs(d) * 0.3 + Math.abs(a.result[k].p50) * 0.01;
    deltas[k] = { p10: d - w, p50: d, p90: d + w, unit: a.result[k].unit };
  }
  return json({ a_id, b_id, deltas, seed: 7, draws: 2000, parameter_set_version: "mock-1", a_metrics: metricsOf(a.result), b_metrics: metricsOf(b.result), same_parameter_set: true, warnings: [] });
});

on("GET", /^\/api\/scenarios$/, (_m, { url }) => {
  const designId = url.searchParams.get("design_id");
  const rows = (designId ? store.scenarios.filter((s) => s.design_id === designId) : store.scenarios).slice().reverse();
  return json(rows.map(summary));
});
on("GET", /^\/api\/scenarios\/([^/]+)\/drivers$/, (_m, { url }) =>
  json({ metric: url.searchParams.get("metric") ?? "co2e_kg", parameter_set_version: "mock-1", drivers: mockDrivers(url.searchParams.get("metric") ?? "co2e_kg"), warnings: [] }),
);
on("GET", /^\/api\/scenarios\/([^/]+)$/, (m) => {
  const s = store.scenarios.find((x) => x.id === decodeURIComponent(m[1]));
  return s ? json(full(s)) : err(404, "scenario_not_found", "No saved scenario with this id.");
});

function newRow(design: TrialDesign, name: string, levers: Levers, author: string, lineage?: Row): Row {
  const id = uuid();
  return {
    id,
    lineage_id: lineage?.lineage_id ?? id,
    version: lineage ? Math.max(...store.scenarios.filter((s) => s.lineage_id === lineage.lineage_id).map((s) => s.version)) + 1 : 1,
    parent_id: lineage?.id ?? null,
    name,
    design_id: design.id,
    design_version: 1,
    status: "draft",
    author,
    created_at: new Date().toISOString(),
    parameter_set_version: "mock-1",
    record_hash: hex(),
    levers,
    result: mockCompute(design, levers),
    approval_id: null,
  };
}

on("POST", /^\/api\/scenarios$/, (_m, { body, headers }) => {
  const denied = requireEditor(headers);
  if (denied) return denied;
  const b = body as { design_id: string; name: string; levers: Levers };
  const d = designOr404(b.design_id);
  if (d instanceof Response) return d;
  const bad = validLevers(b.levers);
  if (bad) return err(422, "invalid_levers", `Invalid levers: ${bad}`);
  const row = newRow(d, b.name, b.levers, actor(headers).user);
  store.scenarios.push(row);
  persist();
  return json(full(row), 201);
});
on("POST", /^\/api\/scenarios\/([^/]+)\/versions$/, (m, { body, headers }) => {
  const denied = requireEditor(headers);
  if (denied) return denied;
  const base = store.scenarios.find((x) => x.id === decodeURIComponent(m[1]));
  if (!base) return err(404, "scenario_not_found", "No saved scenario with this id.");
  const d = designOr404(base.design_id);
  if (d instanceof Response) return d;
  const patch = (body ?? {}) as { levers?: Levers; name?: string };
  const row = newRow(d, patch.name ?? base.name, patch.levers ?? base.levers, actor(headers).user, base);
  store.scenarios.push(row);
  persist();
  return json(full(row), 201);
});
on("POST", /^\/api\/scenarios\/([^/]+)\/submit$/, (m, { headers }) => {
  const denied = requireEditor(headers);
  if (denied) return denied;
  const s = store.scenarios.find((x) => x.id === decodeURIComponent(m[1]));
  if (!s) return err(404, "scenario_not_found", "No saved scenario with this id.");
  if (s.status !== "draft") return err(409, "already_submitted", `This scenario is already ${s.status}; it cannot be submitted again.`);
  if (actor(headers).user !== s.author) return err(403, "not_author", "Only the author can submit a scenario for approval.");
  const a: ApprovalRequest = {
    id: uuid(),
    record_type: "scenario",
    record_id: s.id,
    author: s.author,
    required_meanings: ["reviewed", "approved"],
    status: "pending",
    signatures: [],
  };
  store.approvals.push(a);
  s.status = "submitted";
  s.approval_id = a.id;
  persist();
  return json(full(s));
});

on("GET", /^\/api\/params$/, () =>
  json({
    ok: true,
    parameter_set_version: "mock-1",
    count: MOCK_PARAMS.length,
    assumption_count: MOCK_PARAMS.length,
    loaded_at: new Date().toISOString(),
    problems: [],
    conflicts: [],
    parameters: MOCK_PARAMS,
  }),
);
on("GET", /^\/api\/approvals$/, () => json({ items: store.approvals.map(approvalView) }));
on("GET", /^\/api\/approvals\/([^/]+)$/, (m) => {
  const a = store.approvals.find((x) => x.id === decodeURIComponent(m[1]));
  return a ? json(approvalView(a)) : err(404, "approval_not_found", "No approval request with this id.");
});
on("POST", /^\/api\/approvals\/([^/]+)\/sign$/, (m, { body, headers }) => {
  const a = store.approvals.find((x) => x.id === decodeURIComponent(m[1]));
  if (!a) return err(404, "approval_not_found", "No approval request with this id.");
  const { meaning, pin } = body as { meaning: SignatureMeaning; pin: string };
  const me = actor(headers);
  if (!me.user) return err(401, "identity_required", "Send the X-User header.");
  if (!MOCK_PINS[me.user] || MOCK_PINS[me.user] !== pin) return err(401, "invalid_credential", "Unknown user or wrong PIN.");
  if (a.status !== "pending") return err(409, "request_closed", `This request is already ${a.status}.`);
  if (me.user === a.author && (meaning === "reviewed" || meaning === "approved")) {
    return err(403, "self_approval_forbidden", "The author of a record cannot review or approve it (segregation of duties).");
  }
  const next = a.required_meanings.find((x) => !a.signatures.some((s) => s.meaning === x));
  if (meaning !== next) return err(409, "out_of_order", `The next required signature is “${next}”.`);
  if ((meaning === "reviewed" && !["reviewer", "qa"].includes(me.role)) || (meaning === "approved" && me.role !== "qa")) {
    return err(403, "role_not_permitted", `Role “${me.role}” cannot sign “${meaning}”.`);
  }
  const s = store.scenarios.find((x) => x.id === a.record_id);
  const sig: Signature = {
    id: uuid(),
    signer: me.user,
    role: me.role as Signature["role"],
    meaning,
    signed_at: new Date().toISOString(),
    record_type: a.record_type,
    record_id: a.record_id,
    record_hash: s?.record_hash ?? hex(),
  };
  a.signatures.push(sig);
  if (a.required_meanings.every((x) => a.signatures.some((g) => g.meaning === x))) {
    a.status = "approved";
    if (s) s.status = "approved";
  }
  persist();
  return json(approvalView(a));
});

on("GET", /^\/api\/science\/results$/, () =>
  err(501, "not_ready", "The mock API does not serve science results: they must come from the real reproduction (science/out/results.json)."),
);

export function installMockApi(): void {
  const realFetch = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, window.location.origin);
    if (!url.pathname.startsWith("/api/")) return realFetch(input, init);
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    let body: unknown = null;
    let form: FormData | null = null;
    if (init?.body instanceof FormData) form = init.body;
    else if (typeof init?.body === "string") body = JSON.parse(init.body);
    if (init?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
    for (const [m, pattern, handler] of routes) {
      if (m !== method) continue;
      const match = url.pathname.match(pattern);
      if (match) {
        const res = await handler(match, { body, headers, url, form });
        if (init?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
        return res;
      }
    }
    return err(501, "not_ready", `The mock API has no handler for ${method} ${url.pathname}.`);
  };
}

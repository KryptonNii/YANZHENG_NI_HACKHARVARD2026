/**
 * In-browser MOCK API (VITE_MOCK_API=1 only). Patches window.fetch for /api/* so the real client
 * code path is exercised. Mirrors the §5 API table and the A7 approval rules (no self-approval,
 * order enforced, PIN re-authentication). Data is fictional and labelled as such everywhere.
 */
import type { ApprovalRequest, Levers, Signature, SignatureMeaning, TrialDesign } from "../../contracts";
import type { SavedScenario } from "../types";
import { MOCK_DESIGN, MOCK_PARAMS } from "./data";
import { mockCompute, mockDrivers } from "./engine";

export const MOCK_PIN = "1234";
const STORE_KEY = "tp.mock.store.v1";

interface Store {
  designs: TrialDesign[];
  scenarios: SavedScenario[];
  approvals: ApprovalRequest[];
}

function load(): Store {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw) as Store;
  } catch {
    // ignore
  }
  return { designs: [structuredClone(MOCK_DESIGN)], scenarios: [], approvals: [] };
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
  store = { designs: [structuredClone(MOCK_DESIGN)], scenarios: [], approvals: [] };
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

const actor = (h: Headers) => ({ user: h.get("X-User") ?? "anonymous", role: h.get("X-Role") ?? "viewer" });

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
  const base = MOCK_DESIGN.visits.slice(0, 6);
  return json({
    candidates: base.map((v, i) => ({ visit: v, source_page: 12 + i, quote: `(mock quote) ${v.label}: ${v.procedures.map((p) => p.label).join(", ")}`, confidence: 0.92 - i * 0.07 })),
    warnings: ["Mock API: no model was called; these candidates are fictional."],
  });
});

on("GET", /^\/api\/designs$/, () => json(store.designs));
on("GET", /^\/api\/designs\/([^/]+)$/, (m) => {
  const d = store.designs.find((x) => x.id === decodeURIComponent(m[1]));
  return d ? json(d) : err(404, "design_not_found", "No trial design with this id.");
});
on("POST", /^\/api\/designs$/, (_m, { body }) => {
  const d = { ...(body as TrialDesign), id: (body as TrialDesign).id || uuid() };
  store.designs.push(d);
  persist();
  return json(d, 201);
});
on("POST", /^\/api\/designs\/([^/]+)$/, (m, { body }) => {
  const id = decodeURIComponent(m[1]);
  const i = store.designs.findIndex((x) => x.id === id);
  if (i < 0) return err(404, "design_not_found", "No trial design with this id.");
  store.designs[i] = { ...(body as TrialDesign), id };
  persist();
  return json(store.designs[i]);
});

on("POST", /^\/api\/scenarios\/compute$/, async (_m, { body }) => {
  const b = body as { design_id?: string; levers?: Levers };
  const d = store.designs.find((x) => x.id === b.design_id);
  if (!d) return err(404, "design_not_found", "No trial design with this id.");
  const l = b.levers;
  if (!l || l.remote_monitoring_share < 0 || l.remote_monitoring_share > 1 || l.local_lab_share < 0 || l.local_lab_share > 1) {
    return err(422, "invalid_levers", "Lever shares must be between 0 and 1.");
  }
  await delay(120 + Math.random() * 120);
  return json(mockCompute(d, l));
});

on("GET", /^\/api\/scenarios$/, (_m, { url }) => {
  const designId = url.searchParams.get("design_id");
  return json(designId ? store.scenarios.filter((s) => s.design_id === designId) : store.scenarios);
});
on("GET", /^\/api\/scenarios\/([^/]+)\/drivers$/, (_m, { url }) => json({ drivers: mockDrivers(url.searchParams.get("metric") ?? "cost_usd") }));
on("GET", /^\/api\/scenarios\/([^/]+)$/, (m) => {
  const s = store.scenarios.find((x) => x.id === decodeURIComponent(m[1]));
  return s ? json(s) : err(404, "scenario_not_found", "No saved scenario with this id.");
});
on("POST", /^\/api\/scenarios$/, (_m, { body, headers }) => {
  const b = body as { design_id: string; name: string; levers: Levers };
  const d = store.designs.find((x) => x.id === b.design_id);
  if (!d) return err(404, "design_not_found", "No trial design with this id.");
  const version = store.scenarios.filter((s) => s.design_id === b.design_id && s.name === b.name).length + 1;
  const s: SavedScenario = {
    id: uuid(),
    design_id: b.design_id,
    name: b.name,
    version,
    levers: b.levers,
    result: mockCompute(d, b.levers),
    parameter_set_version: "mock-1",
    author: actor(headers).user,
    status: "draft",
    created_at: new Date().toISOString(),
    approval_id: null,
  };
  store.scenarios.push(s);
  persist();
  return json(s, 201);
});
on("POST", /^\/api\/scenarios\/([^/]+)\/submit$/, (m, { headers }) => {
  const s = store.scenarios.find((x) => x.id === decodeURIComponent(m[1]));
  if (!s) return err(404, "scenario_not_found", "No saved scenario with this id.");
  if (s.status !== "draft") return err(409, "already_submitted", "This scenario version was already submitted.");
  const a: ApprovalRequest = {
    id: uuid(),
    record_type: "scenario",
    record_id: s.id,
    author: s.author || actor(headers).user,
    required_meanings: ["reviewed", "approved"],
    status: "pending",
    signatures: [],
  };
  store.approvals.push(a);
  s.status = "submitted";
  s.approval_id = a.id;
  persist();
  return json(a, 201);
});

on("GET", /^\/api\/params$/, () => json(MOCK_PARAMS));
on("GET", /^\/api\/approvals$/, () => json(store.approvals));
on("GET", /^\/api\/approvals\/([^/]+)$/, (m) => {
  const a = store.approvals.find((x) => x.id === decodeURIComponent(m[1]));
  return a ? json(a) : err(404, "approval_not_found", "No approval request with this id.");
});
on("POST", /^\/api\/approvals\/([^/]+)\/sign$/, (m, { body, headers }) => {
  const a = store.approvals.find((x) => x.id === decodeURIComponent(m[1]));
  if (!a) return err(404, "approval_not_found", "No approval request with this id.");
  const { meaning, pin } = body as { meaning: SignatureMeaning; pin: string };
  const me = actor(headers);
  if (pin !== MOCK_PIN) return err(401, "invalid_credentials", "Wrong PIN. Signing requires re-entering your PIN.");
  if (a.status !== "pending") return err(409, "not_pending", "This approval request is already closed.");
  if (me.user === a.author && (meaning === "reviewed" || meaning === "approved")) {
    return err(403, "self_approval_forbidden", "The author of a record cannot review or approve it.");
  }
  const next = a.required_meanings.find((x) => !a.signatures.some((s) => s.meaning === x));
  if (meaning !== next) return err(409, "out_of_order", `The next required signature is “${next}”.`);
  if ((meaning === "reviewed" && !["reviewer", "qa"].includes(me.role)) || (meaning === "approved" && me.role !== "qa")) {
    return err(403, "role_not_permitted", `Role “${me.role}” cannot sign “${meaning}”.`);
  }
  const sig: Signature = {
    id: uuid(),
    signer: me.user,
    role: me.role as Signature["role"],
    meaning,
    signed_at: new Date().toISOString(),
    record_type: a.record_type,
    record_id: a.record_id,
    record_hash: hex(),
  };
  a.signatures.push(sig);
  if (a.required_meanings.every((x) => a.signatures.some((s) => s.meaning === x))) {
    a.status = "approved";
    const s = store.scenarios.find((x) => x.id === a.record_id);
    if (s) s.status = "approved";
  }
  persist();
  return json(a);
});

on("GET", /^\/api\/science\/results$/, () =>
  err(501, "not_ready", "Mock API does not serve science results: they must come from the real reproduction (science/out/results.json)."),
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
    return err(501, "not_ready", `Mock API has no handler for ${method} ${url.pathname}.`);
  };
}

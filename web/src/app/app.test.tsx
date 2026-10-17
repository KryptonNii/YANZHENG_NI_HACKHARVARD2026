import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { SciencePage } from "@/features/scenario/SciencePage";
import { ApiError, api, onApiError, request } from "./api/client";
import { normalizeApproval, normalizeDrivers, normalizeSavedScenario, normalizeScenarioResult, normalizeScience } from "./api/normalize";
import { ExternalPages } from "./externalPages";
import { formatRange, formatSignedValue, formatValue, splitValue } from "./format";
import { getIdentity, identityHeaders, setIdentity } from "./identity";
import { IdentitySwitcher } from "./IdentitySwitcher";
import { ToastProvider } from "./toast";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
  setIdentity("alex.author");
});

describe("demo identity switcher", () => {
  it("is labelled as demo identities and sends X-User / X-Role on every request", async () => {
    const fetchSpy = vi.spyOn(window, "fetch").mockResolvedValue(jsonResponse({ ok: true }));
    render(<IdentitySwitcher />);
    expect(screen.getByLabelText(/demo\s*identities/i)).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByTestId("identity-switcher"), "sam.qa");
    expect(getIdentity().user).toBe("sam.qa");
    expect(identityHeaders()).toEqual({ "X-User": "sam.qa", "X-Role": "qa" });

    await request("GET", "/health");
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-User"]).toBe("sam.qa");
    expect((init.headers as Record<string, string>)["X-Role"]).toBe("qa");
  });
});

describe("API client errors", () => {
  it("turns the §5 error shape into an ApiError with the plain-English message and notifies listeners", async () => {
    vi.spyOn(window, "fetch").mockResolvedValue(
      jsonResponse({ error: "self_approval_forbidden", message: "The author cannot approve.", details: {} }, 403),
    );
    const seen: ApiError[] = [];
    const off = onApiError((e) => seen.push(e));
    await expect(request("POST", "/approvals/x/sign", { body: {} })).rejects.toMatchObject({
      status: 403,
      code: "self_approval_forbidden",
      message: "The author cannot approve.",
    });
    expect(seen[0]?.message).toBe("The author cannot approve.");
    off();
  });

  it("does not notify listeners for silent calls and reports network failures plainly", async () => {
    vi.spyOn(window, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const seen: ApiError[] = [];
    const off = onApiError((e) => seen.push(e));
    await expect(request("GET", "/designs", { silent: true })).rejects.toMatchObject({ code: "network_error" });
    expect(seen).toHaveLength(0);
    off();
  });

  it("reads the parameter library from A5's `parameters` envelope", async () => {
    vi.spyOn(window, "fetch").mockResolvedValue(
      jsonResponse({ ok: true, parameters: [{ id: "a.b", label: "A", value_low: 1, value_mid: 2, value_high: 3, unit: "x" }] }),
    );
    const ps = await api.params();
    expect(ps.map((p) => p.id)).toEqual(["a.b"]);
  });
});

describe("formatting never turns unknown into zero", () => {
  it("prints unknown for NaN / null values", () => {
    expect(formatValue(Number.NaN, "usd")).toBe("unknown");
    expect(formatValue(null as unknown as number, "hours")).toBe("unknown");
    expect(formatRange({ p10: Number.NaN, p50: 1, p90: 2, unit: "usd" })).toBe("unknown");
    expect(splitValue(Number.NaN, "kg_co2e").num).toBe("unknown");
  });

  it("formats carbon in tonnes, money compactly and percent deltas in percentage points", () => {
    expect(formatValue(263_000, "kg_co2e")).toBe("263 t CO₂e");
    expect(formatValue(450, "kg_co2e")).toBe("450 kg CO₂e");
    expect(formatValue(10_300_000, "usd")).toBe("$10.3M");
    expect(formatRange({ p10: 198_000, p50: 263_000, p90: 356_000, unit: "kg_co2e" })).toBe("198 – 356 t CO₂e");
    expect(formatSignedValue(-18.2, "percent")).toBe("−18 pp");
    expect(formatSignedValue(-1_240_000, "usd")).toBe("−$1.24M");
  });
});

describe("normalisers", () => {
  it("reads A5 scenario summaries (metrics, no levers) without inventing levers", () => {
    const s = normalizeSavedScenario({
      id: "s1",
      lineage_id: "s1",
      version: 2,
      name: "B",
      design_id: "d1",
      design_version: 1,
      status: "submitted",
      author: "alex.author",
      created_at: "2026-10-17T00:00:00Z",
      parameter_set_version: "p1",
      record_hash: "ab",
      metrics: { cost_usd: { p10: 1, p50: 2, p90: 3, unit: "usd" } },
    });
    expect(s.levers).toBeNull();
    expect(s.metrics.cost_usd?.p50).toBe(2);
    expect(s.status).toBe("submitted");
  });

  it("extracts the approval embedded in a submitted scenario", () => {
    const s = normalizeSavedScenario({
      id: "s1",
      status: "submitted",
      approval: { id: "a1", record_type: "scenario", record_id: "s1", author: "alex.author", required_meanings: ["reviewed", "approved"], status: "pending", signatures: [] },
    });
    expect(s.approval?.id).toBe("a1");
    expect(s.approval_id).toBe("a1");
    expect(() => normalizeApproval({ nope: true })).toThrow();
  });

  it("keeps the top five drivers with labels", () => {
    const d = normalizeDrivers({ drivers: Array.from({ length: 7 }, (_, i) => ({ parameter_id: `p${i}`, share: 0.1, label: `P${i}` })) });
    expect(d).toHaveLength(5);
    expect(d[0].label).toBe("P0");
  });

  it("accepts a legacy science total keyed by trial", () => {
    const r = normalizeScience({ trials: { CASPS: { published_total_kg: 1000, ours_total: { p10: 800, p50: 950, p90: 1200, unit: "kg_co2e" }, modules: [] } } });
    expect(r.trials[0].name).toBe("CASPS");
    expect(r.trials[0].checks[0].id).toBe("engine_library");
    expect(r.trials[0].checks[0].total?.ours?.p50).toBe(950);
    expect(r.trials[0].published.total_kg).toBe(1000);
  });

  it("keeps A10 checks, gap explanations, findings and tonne-labelled industry totals", () => {
    const r = normalizeScience({
      simulated: false,
      data_label: "Real published data",
      paper: { url: "https://bmjopen.bmj.com/content/14/1/e075755" },
      thresholds_pct: { match: 1, close: 10 },
      engine: { available: true, reason: null },
      trials: [
        {
          id: "casps",
          name: "CASPS",
          published: { total_kg: 71938.8, modules: { samples: 1000 } },
          summary: ["Reproduces to +0.01%.", "Engine total is inside the range."],
          findings: [{ id: "casps-f1", severity: "large", summary: "Centrifuge watts treated as kilowatts.", detail: "About 1000×.", lines: ["L1"], effect_kg: -811.7 }],
          checks: [
            {
              id: "engine_library",
              title: "Engine + library",
              description: "Rebuilt design.",
              available: true,
              total: { module: "total", label: "Total", published_kg: 71938.8, ours: { p10: 56718, p50: 75734, p90: 103307, unit: "kg_co2e" }, diff_pct: 5.28, published_within_range: true, status: "close", explanation: "Inside the range." },
              modules: [
                { module: "laboratory", label: "Laboratory", published_kg: 12000, ours: { p10: 100, p50: 200, p90: 300, unit: "kg_co2e" }, diff_pct: -98.4, status: "gap", published_within_range: false, explanation: "Freezer storage is not in the engine the same way." },
              ],
            },
          ],
        },
      ],
      industry_band: {
        low_t: 1437,
        high_t: 2498,
        trials_t: [1437, 1632, 2498],
        demo_trials: [
          { design_id: "boreas", title: "BOREAS: a COPD study", available: true, within_band: false, total_t: { p10: 954, p50: 1360, p90: 1930, unit: "kg_co2e" } },
        ],
      },
    });
    expect(r.trials[0].checks[0].modules[0].explanation).toMatch(/Freezer/);
    expect(r.trials[0].checks[0].modules[0].status).toBe("gap");
    expect(r.trials[0].findings[0].effect_kg).toBe(-811.7);
    expect(r.industry_band?.demo_trials[0].total_t?.p50).toBe(1360);
    expect(r.industry_band?.demo_trials[0].total_t?.unit).toBe("kg_co2e");
    expect(r.simulated).toBe(false);
  });

  it("normalises the generated science/out/results.json when it is present", () => {
    const path = resolve(import.meta.dirname, "../../../science/out/results.json");
    if (!existsSync(path)) return;
    const source = JSON.parse(readFileSync(path, "utf8")) as { industry_band: { demo_trials: Array<{ title: string; total_t: { p50: number; unit: string }; within_band: boolean }> } };
    const r = normalizeScience(source);
    const casps = r.trials.find((t) => t.id === "casps");
    const engine = casps?.checks.find((c) => c.id === "engine_library");
    expect(casps?.summary).toHaveLength(2);
    expect(casps?.findings.length).toBeGreaterThan(0);
    expect(engine?.modules.some((m) => m.status === "gap" && m.explanation)).toBe(true);
    const notus = r.industry_band?.demo_trials.find((t) => t.title.startsWith("NOTUS"));
    const sourceNotus = source.industry_band.demo_trials.find((t) => t.title.startsWith("NOTUS"));
    expect(sourceNotus).toBeDefined();
    expect(notus?.within_band).toBe(sourceNotus?.within_band);
    expect(notus?.total_t?.p50).toBe(sourceNotus?.total_t.p50);
    expect(notus?.total_t?.unit).toBe("t_co2e");
  });
});

const SCIENCE_FIXTURE = {
  simulated: false,
  data_label: "Real published data, not simulated.",
  paper: { url: "https://bmjopen.bmj.com/content/14/1/e075755" },
  parameter_set_version: "p-set",
  seed: 7,
  draws: 2000,
  thresholds_pct: { match: 1, close: 10 },
  engine: { available: true, reason: null },
  trials: [
    {
      id: "casps",
      name: "CASPS",
      registry_id: "ISRCTN63733470",
      phase: "Phase 2",
      patients: 47,
      sites: 12,
      countries: ["GB"],
      published: { total_kg: 71938.8, modules: {} },
      summary: ["The paper's arithmetic reproduces to +0.01%.", "The engine total sits inside P10–P90."],
      findings: [{ id: "casps-f1", severity: "large", summary: "Centrifuge watts treated as kilowatts.", detail: "About 1000×.", effect_kg: -811.7, lines: [] }],
      checks: [
        {
          id: "method",
          title: "Method check: the paper's own arithmetic",
          description: "Adds up the paper's own lines.",
          available: true,
          total: { module: "total", label: "Total", published_kg: 71938.8, ours: { p10: 71943, p50: 71943, p90: 71943, unit: "kg_co2e" }, diff_pct: 0.01, status: "match", published_within_range: false },
          modules: [],
        },
        {
          id: "engine_library",
          title: "Engine check: TrialPilot engine + library",
          description: "Rebuilt design through the simulator engine.",
          available: true,
          total: { module: "total", label: "Total", published_kg: 71938.8, ours: { p10: 56718, p50: 75734, p90: 103307, unit: "kg_co2e" }, diff_pct: 5.28, status: "close", published_within_range: true, explanation: "Published total is inside the range." },
          modules: [
            { module: "laboratory", label: "Laboratory", published_kg: 12000, ours: { p10: 100, p50: 200, p90: 300, unit: "kg_co2e" }, diff_pct: -98.4, status: "gap", explanation: "Freezer storage is not in the engine the same way." },
          ],
        },
      ],
    },
  ],
  industry_band: {
    low_t: 1437,
    high_t: 2498,
    trials_t: [1437, 1632, 2498],
    note: "Different method, includes drug manufacture.",
    source: "Mackillop 2023",
    demo_trials: [
      { design_id: "notus", title: "NOTUS: a COPD study", registry_id: "NCT04456673", available: true, within_band: true, total_t: { p10: 1117, p50: 1578, p90: 2241, unit: "kg_co2e" } },
    ],
  },
};

describe("compute response extensions", () => {
  it("accepts forecast and supply when the imported contract does not list them", () => {
    const r = normalizeScenarioResult({
      design_id: "d1",
      warnings: ["ok"],
      modules: [],
      forecast: {
        months_to_full_enrollment: { p10: 8, p50: 10, p90: 14, unit: "months" },
        milestone_dates: { full_enrollment: { p10: 8, p50: 10, p90: 14, unit: "months" } },
        enrollment_curve: [[0, 0, 0, 0], [10, 80, 100, 120]],
        warnings: ["extra"],
      },
      supply: {
        kits_needed: { p10: 10, p50: 20, p90: 30, unit: "kits" },
        kits_produced: { p10: 12, p50: 22, p90: 34, unit: "kits" },
        kits_wasted: { p10: 1, p50: 2, p90: 4, unit: "kits" },
        waste_share: { p10: 5, p50: 9, p90: 12, unit: "percent" },
        shipments: { p10: 4, p50: 6, p90: 9, unit: "count" },
        stockout_probability: 0.06,
        kits_expired: 3,
      },
    });
    expect(r.forecast?.months_to_full_enrollment?.p50).toBe(10);
    expect(r.forecast?.enrollment_curve).toEqual([
      [0, 0, 0, 0],
      [10, 80, 100, 120],
    ]);
    expect(r.supply?.kits_produced?.p50).toBe(22);
    expect(r.supply?.shipments?.unit).toBe("count");
    expect(r.supply?.stockout_probability).toBe(0.06);
  });
});

describe("lazily loaded command and compliance routes", () => {
  // Transform the feature modules up front so each case times the routing, not a cold import.
  // The lazy() factories still run; they just get the cached module.
  beforeAll(async () => {
    await import("@/features/command");
    await import("@/features/compliance");
  }, 30_000);

  it.each([
    ["/approvals", "approvals", "approvals-page"],
    ["/audit", "audit", "audit-page"],
    ["/validation", "validation", "validation-page"],
    ["/command/demo-40", "command/:trialId", "command-page"],
  ] as const)("renders %s from its feature module", async (path, route, testId) => {
    vi.spyOn(window, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.startsWith("/api/ops/")) return jsonResponse({ error: "not_simulated", message: "No simulated feed yet.", details: {} }, 409);
      if (url.startsWith("/api/audit/verify")) return jsonResponse({ ok: true, first_bad_seq: null, checked: 0 });
      return jsonResponse({ items: [], total: 0 });
    });
    const Page = {
      approvals: ExternalPages.Approvals,
      audit: ExternalPages.Audit,
      validation: ExternalPages.Validation,
      "command/:trialId": ExternalPages.Command,
    }[route];
    render(
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={<Page />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>,
    );
    expect(await screen.findByTestId(testId, {}, { timeout: 4000 })).toBeInTheDocument();
  });
});

describe("science page", () => {
  it("renders the engine check, the gap explanation, and industry totals as tonnes", async () => {
    vi.spyOn(window, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/science/results")) return jsonResponse(SCIENCE_FIXTURE);
      return jsonResponse({ error: "not_found", message: "missing" }, 404);
    });
    render(<SciencePage />);
    const card = await screen.findByTestId("science-card");
    expect(within(card).getByRole("heading", { name: "CASPS" })).toBeInTheDocument();
    expect(within(card).getByText(/Freezer storage is not in the engine/)).toBeInTheDocument();
    expect(within(card).getByText("Centrifuge watts treated as kilowatts.")).toBeInTheDocument();
    expect(within(card).getByText("Gap")).toBeInTheDocument();
    expect(screen.getByText("1,578 t")).toBeInTheDocument();
    expect(screen.getByText("Inside the band")).toBeInTheDocument();
    expect(screen.getByTestId("science-band-unit")).toHaveTextContent("kg_co2e");
    expect(screen.queryByText(/1,578 kg/)).not.toBeInTheDocument();
    expect(screen.queryByText("1.578 t")).not.toBeInTheDocument();
    expect(screen.queryByText("1,578,000 t")).not.toBeInTheDocument();

    await userEvent.click(within(card).getByRole("radio", { name: "Method" }));
    expect(within(card).getByRole("heading", { name: /paper's own arithmetic/i })).toBeInTheDocument();
    expect(within(card).queryByText(/Freezer storage/)).not.toBeInTheDocument();
  });
});

describe("toast-free identity default", () => {
  it("defaults to the author when nothing is stored", () => {
    act(() => setIdentity("alex.author"));
    expect(getIdentity().role).toBe("author");
  });
});

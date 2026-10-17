import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Levers, ProcedureEndpointRole } from "@/app/contracts";
import { api } from "@/app/api/client";
import { DEFAULT_LEVERS } from "@/app/api/normalize";
import { MOCK_DESIGN } from "@/app/api/mock/data";
import { mockCompute } from "@/app/api/mock/engine";
import { ToastProvider } from "@/app/toast";
import { NextLever, type LeverRecommendation, type NextLeverData } from "./components/NextLever";
import { ScenarioPage } from "./ScenarioPage";

const samplingNote = "Advice estimates use seed 7 and 200 draws with common random numbers; the formal scenario uses 2000 draws.";
const samplingLine = "Ranking uses seed 7 and 200 draws. The formal scenario results use their own draw count (2,000), so they can differ.";
const stressLabel = "Enrollment 30% slower than your current selection";
const stressReason = "Pressure scenario under an assumed slower enrollment rate. It is an assumption, not a recommendation.";
const removalNote = (code: string) =>
  `Not clinical approval: removing ${code} still requires manual protocol review of safety, eligibility and treatment needs.`;
const range = (p50: number, unit: "usd" | "hours" | "months") => ({ p10: p50 - 2, p50, p90: p50 + 3, unit });
const metrics = (cost: number, hours: number, months = 0) =>
  ({ cost_usd: range(cost, "usd"), site_staff_hours: range(hours, "hours"), duration_months: range(months, "months") });
const props = { designId: "design-1", designVersion: 1, currentLevers: DEFAULT_LEVERS };

function recommendation(
  id: string, label: string, levers: Partial<Levers>, cost: number, hours: number,
): LeverRecommendation {
  return {
    id, label, kind: "lever", levers, delta: metrics(cost, hours),
    reason: "The model estimates lower operating costs within the constraints.", stockout_probability: 0.025, procedure: null,
  };
}

function removal(
  code: string, removed: string[], roles: ProcedureEndpointRole[] = ["not_linked"],
  overrides: Partial<LeverRecommendation> = {},
): LeverRecommendation {
  return {
    ...recommendation("remove_procedure:" + code, "Remove " + code, { removed_procedures: removed }, -99999, -999),
    kind: "procedure_removal", procedure: { code, label: code, endpoint_roles: roles }, ...overrides,
  };
}

function fixture(currentLevers = DEFAULT_LEVERS): NextLeverData {
  return {
    design_id: "design-1", design_version: 1, design_hash: "hash-1", parameter_set_version: "params-1",
    seed: 7, draws: 200, scenario_draws: 2000, current_levers: currentLevers, sampling_note: samplingNote,
    delta_method: "Per-draw candidate minus your current selection (the baseline), using common random numbers.",
    baseline: metrics(20000, 500, 12),
    recommendations: [
      recommendation("on_demand_supply", "On-demand drug supply", { drug_supply_strategy: "on_demand" }, -2000, 0),
      recommendation("remote_monitoring", "50% remote monitoring", { remote_monitoring_share: 0.5 }, -1000, -50),
      recommendation("local_labs", "50% local laboratory testing", { local_lab_share: 0.5 }, -1000, -10),
    ],
    policy: { max_duration_increase_months: 0, max_stockout_probability: 0.05, max_recommendations: 3,
      note: "Require lower median cost and no median delay." },
    rejected: [],
    stress_scenarios: [{
      id: "slower_enrollment", label: stressLabel, tag: "assumption",
      levers: { enrollment_rate_multiplier: 0.7 }, delta: metrics(1500, 40, 3), stockout_probability: 0.04, reason: stressReason,
    }],
    blocked: [
      { code: "primary_scan", endpoint_roles: ["supports_primary"], reason: "Supports a primary endpoint; removal is excluded from advice." },
      { code: "secondary_test", endpoint_roles: ["supports_secondary"], reason: "Supports a secondary endpoint; removal is excluded from advice." },
      { code: "unknown_test", endpoint_roles: ["unknown"], reason: "Endpoint linkage is unknown; removal is excluded from advice." },
      { code: "mixed_test", endpoint_roles: ["not_linked", "supports_primary"],
        reason: "Its not_linked occurrences do not override the linked or unknown ones." },
    ],
    warnings: [],
  };
}

const response = (data: NextLeverData) => new Response(JSON.stringify(data), { status: 200 });
const queryOf = (url: string) => new URL(url, "http://localhost").searchParams;

function mockFetch(data = fixture()) {
  const fetcher = vi.fn().mockImplementation(() => Promise.resolve(response(data)));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("NextLever", () => {
  it("shows one not_linked removal as not clinical approval and filters every contradictory removal", async () => {
    const current = { ...DEFAULT_LEVERS, removed_procedures: ["diary"] };
    const data = fixture(current);
    data.recommendations = [
      removal("primary_scan", ["diary", "primary_scan"], ["supports_primary"]),
      removal("secondary_test", ["diary", "secondary_test"], ["supports_secondary"]),
      removal("unknown_test", ["diary", "unknown_test"], ["unknown"]),
      removal("mixed_test", ["diary", "mixed_test"]),
      removal("unlisted_primary", ["diary", "unlisted_primary"], ["supports_primary"]),
      removal("unlisted_mixed", ["diary", "unlisted_mixed"], ["not_linked", "unknown"]),
      removal("unlisted", ["diary", "unlisted"], ["not_linked"], { procedure: null }),
      removal("other_code", ["diary", "other_code"], ["not_linked"], { procedure: { code: "ecg", label: "ECG", endpoint_roles: ["not_linked"] } }),
      removal("no_roles", ["diary", "no_roles"], []),
      removal("as_lever", ["diary", "as_lever"], ["not_linked"], { kind: "lever" }),
      removal("two_codes", ["diary", "two_codes", "ecg"]),
      removal("dropping", ["dropping"]),
      removal("cleared", []),
      removal("combined", [], ["not_linked"], { levers: { removed_procedures: ["diary", "combined"], remote_monitoring_share: 0.5 } }),
      removal("no_patch", [], ["not_linked"], { levers: { local_lab_share: 0.5 } }),
      removal("ecg", ["diary", "ecg"]),
      ...data.recommendations,
    ];
    data.rejected = [{
      id: "remove_procedure:photo", label: "Remove photo", kind: "procedure_removal", levers: { removed_procedures: ["diary", "photo"] },
      reason: "Met the model constraints but ranked below the top 3 by cost P50 change relative to the current selection.",
      delta: metrics(-10, -1), procedure: { code: "photo", label: "Photo", endpoint_roles: ["not_linked"] },
    }];
    const preview = vi.fn();
    const fetcher = mockFetch(data);
    render(<NextLever {...props} currentLevers={current} onPreview={preview} />);
    const blocked = await screen.findByRole("list", { name: "Blocked procedures" });
    expect(blocked).toHaveTextContent("primary_scan: Supports a primary endpoint");
    expect(blocked).toHaveTextContent("unknown_test: Endpoint linkage is unknown");
    expect(blocked).toHaveTextContent("mixed_test: Its not_linked occurrences do not override");
    const ranked = screen.getByRole("list", { name: "Recommended levers" });
    const items = within(ranked).getAllByRole("listitem");
    expect(items.map((item) => within(item).getByRole("heading").textContent)).toEqual([
      "Remove ecg", "On-demand drug supply", "50% remote monitoring",
    ]);
    expect(items[0]).toHaveTextContent(removalNote("ecg"));
    expect(items[0]).toHaveTextContent("Preview changes: remove procedure ecg.");
    expect(items[1]).not.toHaveTextContent("Not clinical approval");
    expect(screen.getByRole("list", { name: "Rejected changes" })).toHaveTextContent(removalNote("photo"));
    await userEvent.click(within(items[0]).getByRole("button", { name: "Preview this change" }));
    expect(preview).toHaveBeenCalledWith({ removed_procedures: ["diary", "ecg"] });
    const query = queryOf(fetcher.mock.calls[0][0]);
    expect(query.get("design_id")).toBe("design-1");
    expect(query.get("design_version")).toBe("1");
    expect(JSON.parse(query.get("current_levers")!)).toEqual(current);
  });

  it("never recommends slower enrollment, even combined with another lever", async () => {
    const data = fixture();
    data.recommendations.unshift(
      recommendation("slower_enrollment", "Slower enrollment", { enrollment_rate_multiplier: 0.7 }, -5000, -100),
      recommendation("combo", "Remote monitoring at slower enrollment",
        { remote_monitoring_share: 0.5, enrollment_rate_multiplier: 0.7 }, -4000, -100),
    );
    mockFetch(data);
    render(<NextLever {...props} />);
    const list = await screen.findByRole("list", { name: "Recommended levers" });
    expect(within(list).getAllByRole("heading").map((heading) => heading.textContent)).toEqual([
      "On-demand drug supply", "50% remote monitoring", "50% local laboratory testing",
    ]);
    expect(list).not.toHaveTextContent(/enrollment/i);
  });

  it("shows slower enrollment only as an assumption stress test, without preview or saving wording", async () => {
    mockFetch();
    render(<NextLever {...props} onPreview={vi.fn()} />);
    const stress = await screen.findByRole("list", { name: "Stress scenarios" });
    expect(screen.getByRole("heading", { name: "Stress test (assumption)" })).toBeVisible();
    const item = within(stress).getByRole("listitem");
    expect(within(item).getByRole("heading")).toHaveTextContent(stressLabel);
    expect(within(item).getByText("assumption")).toBeVisible();
    expect(item).toHaveTextContent(stressReason);
    expect(item).toHaveTextContent("Assumed enrollment rate: 70% of plan.");
    const table = within(item).getByRole("table", { name: `${stressLabel}: changes from current scenario` });
    const cost = within(table).getByRole("row", { name: /Cost \(USD\)/ });
    expect(within(cost).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["+1,498", "+1,500", "+1,503"]);
    expect(item).toHaveTextContent("Modeled stockout probability: 4%.");
    expect(within(item).queryByRole("button")).not.toBeInTheDocument();
    expect(item.textContent).not.toMatch(/sav(e|ing)|reduc/i);
    const ranked = screen.getByRole("list", { name: "Recommended levers" });
    expect(ranked).not.toHaveTextContent(stressLabel);
    expect(ranked.contains(stress)).toBe(false);
    expect(screen.getAllByRole("button", { name: "Preview this change" })).toHaveLength(3);
  });

  it("shows an unestimated stress scenario as Not estimated rather than zero", async () => {
    const data = fixture();
    data.stress_scenarios[0] = { ...data.stress_scenarios[0], delta: null, stockout_probability: null,
      reason: "The forecast has no database-lock date for this assumption, so its change is not estimated." };
    mockFetch(data);
    render(<NextLever {...props} />);
    const item = within(await screen.findByRole("list", { name: "Stress scenarios" })).getByRole("listitem");
    expect(item).toHaveTextContent("Changes from current scenario: Not estimated.");
    expect(item).toHaveTextContent("Modeled stockout probability: Not estimated.");
    expect(within(item).queryByRole("table")).not.toBeInTheDocument();
    expect(within(item).getByText("assumption")).toBeVisible();
  });

  it("describes added countries as assumptions, not registry sites", async () => {
    const data = fixture();
    data.recommendations = [recommendation("added_countries", "Add 2 assumed countries", { added_country_count: 2 }, -300, -5)];
    mockFetch(data);
    render(<NextLever {...props} />);
    const list = await screen.findByRole("list", { name: "Recommended levers" });
    expect(list).toHaveTextContent("Preview changes: 2 assumed added countries (assumptions, not registry sites).");
  });

  it("states the ranking baseline, seed and draws separately from the formal scenario draws", async () => {
    mockFetch();
    render(<NextLever {...props} />);
    expect(await screen.findByText(samplingLine)).toBeVisible();
    expect(screen.getByText(samplingNote)).toBeVisible();
    expect(screen.getByText(/Ranked relative to your current scenario \(the baseline\)/))
      .toHaveTextContent("by median cost change, then site staff hours");
  });

  it("names the formal scenario draw count from the response rather than a fixed 2,000", async () => {
    const data = fixture();
    data.scenario_draws = 5000;
    mockFetch(data);
    render(<NextLever {...props} />);
    expect(await screen.findByText(/own draw count \(5,000\), so they can differ/)).toBeVisible();
    expect(screen.queryByText(/\(2,000\)/)).not.toBeInTheDocument();
  });

  it("retains the ranked metrics and gives understandable changes instead of raw patches", async () => {
    mockFetch();
    render(<NextLever {...props} />);
    const list = await screen.findByRole("list", { name: "Recommended levers" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((item) => within(item).getByRole("heading").textContent)).toEqual([
      "On-demand drug supply", "50% remote monitoring", "50% local laboratory testing",
    ]);
    const cost = within(items[0]).getByRole("row", { name: /Cost \(USD\)/ });
    expect(within(cost).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["-2,002", "-2,000", "-1,997"]);
    expect(items[0]).toHaveTextContent("Preview changes: on-demand drug supply.");
    expect(items[0]).not.toHaveTextContent("drug_supply_strategy");
    expect(within(items[0]).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Metric change", "P10", "P50", "P90",
    ]);
  });

  it("does not preview array patches that clear or drop existing choices", async () => {
    const current = { ...DEFAULT_LEVERS, removed_procedures: ["ecg", "diary"], home_visit_numbers: [1, 2],
      remote_visit_numbers: [3], excluded_site_ids: ["s1"] };
    const data = fixture(current);
    data.recommendations = [
      recommendation("clear", "Clear removals", { removed_procedures: [] }, -1000, -10),
      recommendation("subset", "Drop a removal", { removed_procedures: ["ecg"] }, -1000, -10),
      recommendation("home", "Drop a home visit", { home_visit_numbers: [1, 4] }, -1000, -10),
      recommendation("remote", "Drop telehealth", { remote_visit_numbers: [] }, -1000, -10),
      recommendation("site", "Drop an exclusion", { excluded_site_ids: ["s2"] }, -1000, -10),
      recommendation("preserve", "Keep prior choices and add visit 4", { home_visit_numbers: [1, 2, 4] }, -500, -10),
    ];
    const preview = vi.fn();
    mockFetch(data);
    render(<NextLever {...props} currentLevers={current} onPreview={preview} />);
    const list = await screen.findByRole("list", { name: "Recommended levers" });
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
    expect(list).toHaveTextContent("Keep prior choices and add visit 4");
    await userEvent.click(screen.getByRole("button", { name: "Preview this change" }));
    expect(preview).toHaveBeenCalledWith({ home_visit_numbers: [1, 2, 4] });
  });

  it("explains sampling, model constraints and estimated stockout risk", async () => {
    mockFetch();
    render(<NextLever {...props} />);
    expect(await screen.findByText(samplingLine)).toBeVisible();
    expect(screen.getByText(/Maximum duration P50 increase/)).toHaveTextContent("0 months");
    expect(screen.getByText(/Maximum duration P50 increase/)).toHaveTextContent("5%");
    expect(screen.getByText(/do not establish clinical safety/)).toBeVisible();
    expect(screen.getAllByText("Modeled stockout probability: 2.5%.")).toHaveLength(3);
    expect(screen.getByText(/negative values are reductions/)).toHaveTextContent("your current scenario");
  });

  it("keeps unknown risk and deltas distinct from zero", async () => {
    const data = fixture();
    data.recommendations[0].delta.duration_months = { p10: null, p50: null, p90: null, unit: "months" };
    data.recommendations[0].stockout_probability = null;
    mockFetch(data);
    render(<NextLever {...props} />);
    const table = await screen.findByRole("table", { name: "On-demand drug supply: changes from current scenario" });
    expect(within(table).getAllByText("Not estimated")).toHaveLength(3);
    expect(screen.getByText("Modeled stockout probability: Not estimated.")).toBeVisible();
  });

  it("shows why no change qualifies, including missing evidence, without a preview action", async () => {
    const data = fixture();
    data.recommendations = [];
    data.rejected = [
      { id: "schedule", label: "Remote monitoring", kind: "lever", levers: {}, procedure: null,
        reason: "A reviewed visit schedule is required; the current schedule is assumed.", delta: null },
      { id: "cost", label: "Local labs", kind: "lever", levers: { local_lab_share: 0.5 }, procedure: null,
        reason: "No median cost improvement.", delta: data.baseline },
      { id: "risk", label: "On-demand supply", kind: "lever", levers: { drug_supply_strategy: "on_demand" }, procedure: null,
        reason: "Modeled stockout probability exceeds the limit.", delta: data.baseline },
    ];
    data.stress_scenarios = [];
    mockFetch(data);
    render(<NextLever {...props} onPreview={vi.fn()} />);
    expect(await screen.findByText(/No recommendation meets the model constraints/)).toBeVisible();
    expect(screen.getByRole("list", { name: "Rejected changes" })).toHaveTextContent("reviewed visit schedule is required");
    expect(screen.getByRole("list", { name: "Rejected changes" })).toHaveTextContent("No median cost improvement");
    expect(screen.getByRole("list", { name: "Rejected changes" })).toHaveTextContent("stockout probability exceeds");
    expect(screen.queryByRole("list", { name: "Recommended levers" })).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Stress scenarios" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Preview this change" })).not.toBeInTheDocument();
  });

  it("clears displayed advice immediately and debounces changes to the complete current levers", async () => {
    const fetcher = mockFetch();
    const view = render(<NextLever {...props} />);
    await screen.findByRole("list", { name: "Recommended levers" });
    vi.useFakeTimers();
    const changed = { ...DEFAULT_LEVERS, remote_monitoring_share: 0.4, excluded_site_ids: ["s2"], home_visit_numbers: [2] };
    fetcher.mockResolvedValueOnce(response(fixture(changed)));
    view.rerender(<NextLever {...props} currentLevers={{ ...changed, remote_monitoring_share: 0.2 }} />);
    expect(screen.queryByRole("list", { name: "Recommended levers" })).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(100); });
    view.rerender(<NextLever {...props} currentLevers={changed} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(249); });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(JSON.parse(queryOf(fetcher.mock.calls[1][0]).get("current_levers")!)).toEqual(changed);
    expect(screen.getByRole("list", { name: "Recommended levers" })).toBeVisible();
  });

  it("aborts and ignores a late result for earlier choices on the same design version", async () => {
    let finishOld!: (value: Response) => void;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { finishOld = resolve; }));
    vi.stubGlobal("fetch", fetcher);
    const view = render(<NextLever {...props} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const changed = { ...DEFAULT_LEVERS, local_lab_share: 0.4 };
    const newer = fixture(changed);
    newer.recommendations = [recommendation("new", "Advice for current local labs", { remote_monitoring_share: 0.5 }, -500, -20)];
    fetcher.mockResolvedValueOnce(response(newer));
    view.rerender(<NextLever {...props} currentLevers={changed} />);
    expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
    await screen.findByRole("heading", { name: "Advice for current local labs" });
    await act(async () => { finishOld(response(fixture())); });
    expect(screen.queryByRole("heading", { name: "On-demand drug supply" })).not.toBeInTheDocument();
  });

  it("clears advice and ignores late results after a design version switch", async () => {
    let finishOld!: (value: Response) => void;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { finishOld = resolve; }));
    vi.stubGlobal("fetch", fetcher);
    const view = render(<NextLever {...props} />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    const newer = fixture();
    newer.design_version = 2;
    newer.recommendations = [recommendation("new", "New version monitoring", { remote_monitoring_share: 0.5 }, -500, -20)];
    fetcher.mockResolvedValueOnce(response(newer));
    view.rerender(<NextLever {...props} designVersion={2} />);
    await screen.findByRole("heading", { name: "New version monitoring" });
    await act(async () => { finishOld(response(fixture())); });
    expect(screen.queryByRole("heading", { name: "On-demand drug supply" })).not.toBeInTheDocument();
    expect(queryOf(fetcher.mock.calls[1][0]).get("design_version")).toBe("2");
    view.rerender(<NextLever {...props} designVersion={3} />);
    expect(screen.queryByRole("list", { name: "Recommended levers" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Comparing");
  });

  it("accepts identical levers despite object-key and selection order differences", async () => {
    const current = { ...DEFAULT_LEVERS, excluded_site_ids: ["s2", "s1"] };
    const { excluded_site_ids, ...otherSelections } = current;
    const data = fixture({ excluded_site_ids: [...excluded_site_ids].reverse(), ...otherSelections });
    const fetcher = mockFetch(data);
    const view = render(<NextLever {...props} currentLevers={current} />);
    await screen.findByRole("list", { name: "Recommended levers" });
    view.rerender(<NextLever {...props} currentLevers={data.current_levers} />);
    expect(screen.getByRole("list", { name: "Recommended levers" })).toBeVisible();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("rejects advice computed against different current choices", async () => {
    mockFetch(fixture({ ...DEFAULT_LEVERS, remote_monitoring_share: 0.5 }));
    render(<NextLever {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("does not match the current scenario choices");
    expect(screen.queryByRole("list", { name: "Recommended levers" })).not.toBeInTheDocument();
  });

  it("shows API errors and retries the identical pinned request", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
      error: "engine_not_ready", message: "The comparison engine is unavailable.", details: {},
    }), { status: 501 })).mockResolvedValueOnce(response(fixture()));
    vi.stubGlobal("fetch", fetcher);
    render(<NextLever {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The comparison engine is unavailable.");
    await userEvent.click(screen.getByRole("button", { name: "Retry advice" }));
    expect(await screen.findByText(samplingNote)).toBeVisible();
    expect(fetcher.mock.calls[0][0]).toBe(fetcher.mock.calls[1][0]);
  });

  it("rejects a response for a different design version", async () => {
    const data = fixture();
    data.design_version = 9;
    mockFetch(data);
    render(<NextLever {...props} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("does not match the saved design version");
    expect(screen.queryByRole("list", { name: "Recommended levers" })).not.toBeInTheDocument();
  });

  it("does not fetch without a valid saved version", () => {
    const fetcher = mockFetch();
    render(<NextLever {...props} designVersion={0} />);
    expect(screen.getByRole("alert")).toHaveTextContent("design_version_required");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("previews through ScenarioPage, preserves other choices and recalculates without saving", async () => {
    vi.spyOn(api, "getDesign").mockResolvedValue({ design: MOCK_DESIGN, version: 1, etag: "mock-hash-1" });
    vi.spyOn(api, "listScenarios").mockResolvedValue([]);
    const compute = vi.spyOn(api, "compute").mockImplementation(async (_id, levers) => mockCompute(MOCK_DESIGN, levers));
    const save = vi.spyOn(api, "saveScenario");
    const saveDesign = vi.spyOn(api, "saveDesign");
    const fetcher = vi.fn().mockImplementation(async (url: string) => {
      if (!url.startsWith("/api/scenarios/advice?")) {
        return new Response(JSON.stringify({ error: "not_available", message: "Peer data unavailable in this test." }), { status: 404 });
      }
      const current = JSON.parse(queryOf(url).get("current_levers")!) as Levers;
      const data = fixture(current);
      data.design_id = MOCK_DESIGN.id;
      data.recommendations = [recommendation("remote", "Preview remote monitoring", { remote_monitoring_share: 0.5 }, -500, -20)];
      return response(data);
    });
    vi.stubGlobal("fetch", fetcher);
    render(<ToastProvider><MemoryRouter initialEntries={["/scenario/" + MOCK_DESIGN.id]}>
      <Routes><Route path="/scenario/:designId" element={<ScenarioPage />} /></Routes>
    </MemoryRouter></ToastProvider>);
    await screen.findByTestId("design-version");
    await userEvent.click(screen.getByRole("radio", { name: "On-demand resupply" }));
    fireEvent.change(screen.getByTestId("lever-local-labs"), { target: { value: "30" } });
    const procedure = screen.getByTestId("procedure-questionnaire");
    await userEvent.click(within(procedure).getByRole("checkbox"));
    await screen.findByRole("button", { name: "Preview this change" });
    const previous = compute.mock.calls.at(-1)![1];
    expect(previous).toMatchObject({ drug_supply_strategy: "on_demand", local_lab_share: 0.3, removed_procedures: ["questionnaire"] });
    await userEvent.click(screen.getByRole("button", { name: "Preview this change" }));
    await waitFor(() => expect(compute.mock.calls.at(-1)![1]).toEqual({ ...previous, remote_monitoring_share: 0.5 }));
    expect(screen.getByRole("radio", { name: "On-demand resupply" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("lever-local-labs")).toHaveValue("30");
    expect(within(procedure).getByRole("checkbox")).toBeChecked();
    expect(save).not.toHaveBeenCalled();
    expect(saveDesign).not.toHaveBeenCalled();
    await waitFor(() => {
      const adviceCalls = fetcher.mock.calls.filter(([url]) => url.startsWith("/api/scenarios/advice?"));
      expect(JSON.parse(queryOf(adviceCalls.at(-1)![0]).get("current_levers")!).remote_monitoring_share).toBe(0.5);
    });
  });
});

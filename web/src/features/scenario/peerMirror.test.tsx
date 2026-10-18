import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PeerMirror, type PeerMirrorData, type PeerRow } from "./components/PeerMirror";

function fixture(): PeerMirrorData {
  const row: PeerRow = {
    metric: "primary_outcomes", label: "Primary outcomes", own_count: 1,
    cohort_n: 2, available_n: 2, phase: "PHASE3", condition_group: "copd",
    source_file: "NCT03930732.json", peer_source_files: ["NCT04456673.json", "NCT04535986.json"],
    status: "insufficient_peers", peer_median: 1, percentile: null, comparison: "same",
    question: "Does this record list more or fewer primary outcomes than the cached peers in this phase and condition?",
    note: "2 matched cached peers; 2 report this metric. At least 5 are required for a percentile.",
  };
  return {
    design_id: "saved-design", design_version: 1, design_hash: "hash-v1", registry_id: "NCT03930732",
    phase: "PHASE3", condition_group: "copd", cohort_n: 2, source_file: "NCT03930732.json",
    peer_source_files: row.peer_source_files,
    own_counts: { primary_outcomes: 1, total_outcomes: 17, inclusion_criteria: 8,
      exclusion_criteria: 11, eligibility_criteria: 19, countries: 24, sites: 275, enrollment_target: null },
    enrollment_reported: 939, enrollment_type: "ACTUAL", rows: [row],
    methods: {
      eligibility: "Split eligibilityCriteria with splitlines(), trim each line, discard empty lines and section headings; count remaining lines including sub-bullets.",
      cohort: "Same phase and normalized condition; exclude the record itself.",
    },
    interpretation: "What might explain these differences? Complexity can have scientific reasons.",
    available_procedures: [
      { code: "blood_draw", labels: ["Blood draw"], occurrences: 2, visit_numbers: [1, 2] },
      { code: "ecg", labels: ["ECG"], occurrences: 1, visit_numbers: [1] },
    ],
    cost_comparison: {
      design_id: "saved-design", design_version: 1, design_hash: "hash-v1", removed_procedures: [],
      baseline: { cost_usd: { p10: 100, p50: 120, p90: 150, unit: "usd" },
        site_staff_hours: { p10: 10, p50: 12, p90: 15, unit: "hours" } },
      counterfactual: { cost_usd: { p10: 100, p50: 120, p90: 150, unit: "usd" },
        site_staff_hours: { p10: 10, p50: 12, p90: 15, unit: "hours" } },
      delta: { cost_usd: { p10: 0, p50: 0, p90: 0, unit: "usd" },
        site_staff_hours: { p10: 0, p50: 0, p90: 0, unit: "hours" } },
      delta_method: "Existing engine per-draw counterfactual minus baseline, using common random numbers.",
      parameter_set_version: "params-1", seed: 7, draws: 100, warnings: [],
    },
    cost_reason: null,
  };
}

const response = (data: PeerMirrorData) => new Response(JSON.stringify(data), { status: 200 });

function mockFetch(data = fixture()) {
  const fetcher = vi.fn().mockResolvedValue(response(data));
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

afterEach(() => vi.unstubAllGlobals());

describe("PeerMirror", () => {
  it("requests the pinned saved version and shows sparse-cohort counts with file provenance", async () => {
    const data = fixture();
    data.rows[0].percentile = 99; // Even an inconsistent response cannot bypass the small-n guard.
    const fetcher = mockFetch(data);
    render(<PeerMirror designId="saved-design" designVersion={1} />);
    const row = await screen.findByTestId("peer-primary_outcomes");
    expect(fetcher).toHaveBeenCalledWith("/api/designs/saved-design/peers?version=1", expect.objectContaining({ method: "GET" }));
    expect(within(row).getAllByRole("cell")[0]).toHaveTextContent("1");
    expect(row).toHaveTextContent("Insufficient sample");
    expect(within(row).getByRole("cell", { name: "2 / 2" })).toBeInTheDocument();
    expect(within(row).queryByText(data.rows[0].question)).not.toBeInTheDocument();
    await userEvent.click(within(row).getByText("Source & method"));
    expect(row).toHaveTextContent("cohort_n: 2; available_n: 2; phase: PHASE3; condition_group: copd");
    expect(row).toHaveTextContent("NCT03930732.json");
    expect(row).toHaveTextContent("NCT04456673.json, NCT04535986.json");
    expect(screen.queryByText(/Percentile/)).not.toBeInTheDocument();
    expect(screen.getByText(/splitlines\(\)/)).toBeInTheDocument();
    expect(screen.getByText("Actual enrollment: 939")).toBeInTheDocument();
  });

  it("shows a neutral percentile only for a sufficient cohort", async () => {
    const data = fixture();
    data.cohort_n = 5;
    Object.assign(data.rows[0], { cohort_n: 5, available_n: 5, status: "ok", percentile: 50 });
    mockFetch(data);
    render(<PeerMirror designId="saved-design" designVersion={1} />);
    expect(await screen.findByText("Percentile 50")).toBeInTheDocument();
    expect(screen.getByText("Same as median")).toBeInTheDocument();
    expect(screen.getByTestId("peer-mirror").textContent).not.toMatch(/sponsor ranking|leaderboard|best sponsor|worst sponsor|better percentile|worse percentile/i);
    await userEvent.click(screen.getByText("Source & methodology"));
    expect(screen.getByText(/Descriptive benchmark/)).toHaveTextContent("complexity can have scientific reasons");
  });

  it.each([
    { cohort: 4, rowCohort: 5, available: 5 },
    { cohort: 5, rowCohort: 4, available: 5 },
    { cohort: 5, rowCohort: 5, available: 4 },
  ])("suppresses an inconsistent ok percentile when counts are $cohort/$rowCohort/$available", async ({ cohort, rowCohort, available }) => {
    const data = fixture();
    data.cohort_n = cohort;
    Object.assign(data.rows[0], { cohort_n: rowCohort, available_n: available, status: "ok", percentile: 99 });
    mockFetch(data);
    render(<PeerMirror designId="saved-design" designVersion={1} />);
    const row = await screen.findByTestId("peer-primary_outcomes");
    expect(row).toHaveTextContent("Insufficient sample");
    expect(screen.queryByText(/Percentile/)).not.toBeInTheDocument();
  });

  it("preserves a calculated zero percentile and zero P50 differences", async () => {
    const data = fixture();
    data.cohort_n = 5;
    Object.assign(data.rows[0], { cohort_n: 5, available_n: 5, status: "ok", percentile: 0 });
    mockFetch(data);
    render(<PeerMirror designId="saved-design" designVersion={1} />);
    expect(await screen.findByText("Percentile 0")).toBeInTheDocument();
    expect(screen.getByTestId("cost_usd-p50-difference")).toHaveTextContent(/^0$/);
    expect(screen.getByTestId("site_staff_hours-p50-difference")).toHaveTextContent(/^0$/);
  });

  it("selects procedure codes and displays server-engine ranges and per-draw deltas without local arithmetic", async () => {
    const fetcher = mockFetch();
    render(<PeerMirror designId="saved-design" designVersion={1} />);
    await screen.findByTestId("peer-costs");
    const updated = fixture();
    const costs = updated.cost_comparison!;
    costs.removed_procedures = ["blood_draw"];
    costs.counterfactual.cost_usd = { p10: 80, p50: 90, p90: 110, unit: "usd" };
    costs.counterfactual.site_staff_hours = { p10: 7, p50: 8, p90: 9, unit: "hours" };
    // Deliberately different from subtraction of marginal percentiles.
    costs.delta.cost_usd = { p10: -45, p50: -32, p90: -18, unit: "usd" };
    costs.delta.site_staff_hours = { p10: -7, p50: -5, p90: -2, unit: "hours" };
    fetcher.mockResolvedValueOnce(response(updated));
    await userEvent.click(screen.getByRole("checkbox", { name: /blood_draw:/ }));
    await waitFor(() => expect(fetcher).toHaveBeenLastCalledWith(
      "/api/designs/saved-design/peers?version=1&removed_procedures=blood_draw",
      expect.objectContaining({ method: "GET" }),
    ));
    await waitFor(() => expect(screen.getByTestId("cost_usd-delta")).toHaveTextContent("-32"));
    expect(screen.getByRole("heading", { name: "Procedure impact forecast" })).toBeInTheDocument();
    await userEvent.click(screen.getByText("Forecast detail"));
    expect(screen.getByTestId("cost_usd-p50-difference")).toHaveTextContent(/^-32$/);
    expect(screen.getByTestId("site_staff_hours-p50-difference")).toHaveTextContent(/^-5$/);
    for (const [testId, values] of [
      ["cost_usd-baseline", ["100", "120", "150"]],
      ["cost_usd-counterfactual", ["80", "90", "110"]],
      ["cost_usd-delta", ["-45", "-32", "-18"]],
      ["site_staff_hours-delta", ["-7", "-5", "-2"]],
    ] as const) {
      expect(within(screen.getByTestId(testId)).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([...values]);
    }
    expect(within(screen.getByTestId("peer-costs")).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(["Metric / scenario", "P10", "P50", "P90"]);
    expect(fetcher.mock.calls.every((call) => call[1].method === "GET")).toBe(true);
  });

  it("renders a null cost reason without inventing zero estimates for missing schedules", async () => {
    const data = fixture();
    data.available_procedures = [];
    data.cost_comparison = null;
    data.cost_reason = "No saved visit schedule with procedures is available; costs were not computed.";
    mockFetch(data);
    render(<PeerMirror designId="saved-design" designVersion={1} />);
    expect(await screen.findByText(data.cost_reason)).toBeInTheDocument();
    expect(screen.queryByTestId("peer-costs")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.getByTestId("cost_usd-p50-difference")).toHaveTextContent("Not calculated");
    expect(screen.getByTestId("site_staff_hours-p50-difference")).toHaveTextContent("Not calculated");
  });

  it.each([null, undefined])("does not infer a missing P50 delta (%s) from marginal medians", async (missing) => {
    const data = fixture();
    data.cost_comparison!.counterfactual.cost_usd.p50 = 90;
    data.cost_comparison!.counterfactual.site_staff_hours.p50 = 8;
    Object.assign(data.cost_comparison!.delta.cost_usd, { p50: missing });
    Object.assign(data.cost_comparison!.delta.site_staff_hours, { p50: missing });
    mockFetch(data);
    render(<PeerMirror designId="saved-design" designVersion={1} />);
    await screen.findByTestId("peer-costs");
    await userEvent.click(screen.getByText("Forecast detail"));
    expect(screen.getByTestId("cost_usd-p50-difference")).toHaveTextContent("Not calculated");
    expect(screen.getByTestId("site_staff_hours-p50-difference")).toHaveTextContent("Not calculated");
    expect(within(screen.getByTestId("cost_usd-delta")).getAllByRole("cell")[1]).toHaveTextContent("Not calculated");
    expect(within(screen.getByTestId("site_staff_hours-delta")).getAllByRole("cell")[1]).toHaveTextContent("Not calculated");
  });

  it("hides the previous cost result while a new selection is pending", async () => {
    const fetcher = mockFetch();
    render(<PeerMirror designId="saved-design" designVersion={1} />);
    await screen.findByTestId("peer-costs");
    fetcher.mockImplementationOnce(() => new Promise(() => {}));
    await userEvent.click(screen.getByRole("checkbox", { name: /ecg:/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Loading");
    expect(screen.queryByTestId("peer-costs")).not.toBeInTheDocument();
    expect(screen.getByTestId("cost_usd-p50-difference")).toHaveTextContent("Not calculated");
    expect(screen.getByTestId("site_staff_hours-p50-difference")).toHaveTextContent("Not calculated");
  });

  it("clears procedure selection and loaded results when the saved version changes", async () => {
    const fetcher = mockFetch();
    const view = render(<PeerMirror designId="saved-design" designVersion={1} />);
    await screen.findByTestId("peer-costs");
    fetcher.mockResolvedValueOnce(response(fixture()));
    await userEvent.click(screen.getByRole("checkbox", { name: /ecg:/ }));
    await screen.findByTestId("peer-costs");
    const newer = fixture();
    newer.design_version = 2;
    newer.cost_comparison!.design_version = 2;
    fetcher.mockResolvedValueOnce(response(newer));
    view.rerender(<PeerMirror designId="saved-design" designVersion={2} />);
    expect(screen.queryByTestId("peer-costs")).not.toBeInTheDocument();
    await screen.findByTestId("peer-costs");
    expect(screen.getByRole("checkbox", { name: /ecg:/ })).not.toBeChecked();
    expect(fetcher).toHaveBeenLastCalledWith("/api/designs/saved-design/peers?version=2", expect.anything());
  });

  it("ignores a late response for a previous design version", async () => {
    let finishOld!: (value: Response) => void;
    const fetcher = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { finishOld = resolve; }));
    vi.stubGlobal("fetch", fetcher);
    const view = render(<PeerMirror designId="saved-design" designVersion={1} />);
    const newer = fixture();
    newer.design_version = 2;
    newer.cost_comparison = null;
    newer.cost_reason = "Version 2 has no schedule.";
    fetcher.mockResolvedValueOnce(response(newer));
    view.rerender(<PeerMirror designId="saved-design" designVersion={2} />);
    await screen.findByText(newer.cost_reason);
    await act(async () => { finishOld(response(fixture())); });
    expect(screen.getByText(newer.cost_reason)).toBeInTheDocument();
    expect(screen.queryByTestId("peer-costs")).not.toBeInTheDocument();
  });

  it("displays the API error envelope and retries the same pinned request", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
      error: "design_version_required", message: "Send version: the saved design version on screen.", details: {},
    }), { status: 422 })).mockResolvedValueOnce(response(fixture()));
    vi.stubGlobal("fetch", fetcher);
    render(<PeerMirror designId="saved-design" designVersion={1} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Send version");
    await userEvent.click(screen.getByRole("button", { name: "Retry comparison" }));
    await screen.findByTestId("peer-primary_outcomes");
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      "/api/designs/saved-design/peers?version=1", "/api/designs/saved-design/peers?version=1",
    ]);
  });

  it("does not fetch or retain results for an invalid version", () => {
    const fetcher = mockFetch();
    render(<PeerMirror designId="saved-design" designVersion={0} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Save a design version");
    expect(fetcher).not.toHaveBeenCalled();
  });
});

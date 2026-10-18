/**
 * Scenario simulator behaviour against the in-browser mock API (the same fetch path the real
 * API uses). Requirement tags follow A7's URS ids where they exist (see handoffs/A8.md).
 */
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { Procedure, Visit } from "@/app/contracts";
import type { ApprovalView, ExtractionCandidate } from "@/app/api/types";
import { ApiError, api } from "@/app/api/client";
import { installMockApi, resetMockStore } from "@/app/api/mock";
import { MOCK_DESIGN, MOCK_PARAMS } from "@/app/api/mock/data";
import { mockCompute } from "@/app/api/mock/engine";
import { DEFAULT_LEVERS } from "@/app/api/normalize";
import { setIdentity } from "@/app/identity";
import { setLanguage } from "@/app/i18n";
import { formatValue } from "@/app/format";
import { ToastProvider } from "@/app/toast";
import { ApprovalPanel } from "./components/ApprovalPanel";
import { ForecastChart } from "./components/ForecastChart";
import { LeversPanel } from "./components/LeversPanel";
import { ProtocolReview } from "./components/ProtocolReview";
import { nctError, normalizeNct } from "./demoTrials";
import { resetParamLibrary } from "./hooks/useParamLibrary";
import { ImportPage } from "./ImportPage";
import { groupProcedures } from "./procedureGroups";
import { ScenarioPage } from "./ScenarioPage";

const DESIGN = "mock-design-0001";

function renderAt(path: string) {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={<ImportPage />} />
          <Route path="/scenario/:designId" element={<ScenarioPage />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  );
}

beforeAll(() => {
  installMockApi();
});

beforeEach(() => {
  resetMockStore();
  resetParamLibrary();
  setIdentity("alex.author");
});

async function waitForCards() {
  await waitFor(() => expect(screen.getByTestId("metric-cost_usd-value")).toBeInTheDocument(), { timeout: 4000 });
  await waitFor(() => expect(screen.getByTestId("metric-cost_usd-delta")).toBeInTheDocument(), { timeout: 4000 });
}

describe("NCT id validation", () => {
  it("accepts NCT + 8 digits and explains what is wrong otherwise", () => {
    expect(nctError("nct01234567")).toBeNull();
    expect(normalizeNct(" nct01234567 ")).toBe("NCT01234567");
    expect(nctError("")).toMatch(/Enter/);
    expect(nctError("ISRCTN123")).toMatch(/start with/);
    expect(nctError("NCT123")).toMatch(/8 digits/);
  });
});

describe("scenario simulator", () => {
  it("shows five metric cards with P50, a P10–P90 range and a baseline delta", async () => {
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    for (const key of ["cost_usd", "site_staff_hours", "patient_travel_hours", "duration_months", "co2e_kg"]) {
      const card = screen.getByTestId(`metric-${key}`);
      expect(within(card).getByText(/P10–P90 range/i)).toBeInTheDocument();
    }
    expect(screen.getByTestId("metric-cost_usd-delta")).toHaveTextContent(/No change vs baseline/);
    expect(screen.getByText(/MOCK ENGINE/)).toBeInTheDocument();
  });

  it("recomputes after a lever change and updates the cards with signed, worded deltas", async () => {
    const computeSpy = vi.spyOn(api, "compute");
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    const before = screen.getByTestId("metric-cost_usd-value").textContent;

    await userEvent.click(screen.getByRole("radio", { name: "On-demand resupply" }));

    await waitFor(
      () => expect(computeSpy.mock.calls.some(([, levers]) => levers.drug_supply_strategy === "on_demand")).toBe(true),
      { timeout: 4000 },
    );
    await waitFor(() => expect(screen.getByTestId("metric-cost_usd-value").textContent).not.toBe(before), { timeout: 4000 });
    const deltaText = screen.getByTestId("metric-cost_usd-delta").textContent ?? "";
    expect(deltaText).toMatch(/[−+]\d/); // a sign, not only a colour
    expect(deltaText).toMatch(/lower|higher/);
  });

  it("debounces rapid lever changes into one recompute", async () => {
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    const computeSpy = vi.spyOn(api, "compute");
    const slider = screen.getByTestId("lever-remote-monitoring");
    act(() => {
      for (const v of [10, 20, 30, 40, 50]) {
        slider.focus();
        // fire native input events like a dragged slider
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
        if (!setter) throw new Error("input value setter unavailable");
        setter.call(slider, String(v));
        slider.dispatchEvent(new Event("input", { bubbles: true }));
      }
    });
    await waitFor(() => expect(computeSpy).toHaveBeenCalled(), { timeout: 4000 });
    await new Promise((r) => setTimeout(r, 400));
    expect(computeSpy).toHaveBeenCalledTimes(1);
    expect(computeSpy.mock.calls[0][1].remote_monitoring_share).toBeCloseTo(0.5);
  });

  it("opens the provenance drawer with formula, inputs, parameters, sources, assumption tags and top drivers", async () => {
    const sourced = MOCK_PARAMS.map((p) =>
      p.id === "mock.cost.site_visit"
        ? { ...p, assumption: false, rationale: null, source_title: "Example cost survey", source_url: "https://example.org/cost-survey", source_year: 2024 }
        : p,
    );
    vi.spyOn(api, "params").mockResolvedValue(sourced);
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();

    await userEvent.click(screen.getByTestId("metric-cost_usd-value"));
    const drawer = await screen.findByTestId("provenance-drawer");
    expect(within(drawer).getAllByTestId("provenance-formula").length).toBeGreaterThan(0);
    expect(within(drawer).getByText("cost.patient_visits.mock")).toBeInTheDocument();

    await waitFor(() => expect(within(drawer).getAllByTestId("provenance-param").length).toBeGreaterThan(0));
    const link = within(drawer).getByRole("link", { name: "Example cost survey" });
    expect(link).toHaveAttribute("href", "https://example.org/cost-survey");
    expect(within(drawer).getByText(/\(2024\)/)).toBeInTheDocument();
    expect(within(drawer).getAllByText("To confirm").length).toBeGreaterThan(0);
    expect(within(drawer).getAllByText(/Rationale:/).length).toBeGreaterThan(0);

    await waitFor(() => expect(within(drawer).getByTestId("provenance-drivers")).toBeInTheDocument());
    expect(within(drawer).getByTestId("provenance-drivers").querySelectorAll("li")).toHaveLength(5);
  });

  it("blocks self-approval with a plain message, then reviewer and QA signatures approve the scenario", async () => {
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    await userEvent.click(screen.getByRole("radio", { name: "On-demand resupply" }));

    await waitFor(() => expect(screen.getByTestId("save-scenario")).toBeEnabled());
    await userEvent.click(screen.getByTestId("save-scenario"));
    const name = screen.getByTestId("save-name");
    await userEvent.clear(name);
    await userEvent.type(name, "Scenario B");
    await userEvent.click(screen.getByTestId("save-confirm"));

    const submit = await screen.findByTestId("submit-approval", {}, { timeout: 4000 });
    await userEvent.click(submit);
    await screen.findByTestId("approval-panel", {}, { timeout: 4000 });

    // the author tries to sign
    await userEvent.type(screen.getByTestId("sign-pin"), "1111");
    await userEvent.click(screen.getByTestId("sign-button"));
    expect(await screen.findByTestId("sign-error")).toHaveTextContent(/^Authors can't approve their own work\.$/);

    act(() => setIdentity("riley.reviewer"));
    await userEvent.type(screen.getByTestId("sign-pin"), "2222");
    await userEvent.click(screen.getByTestId("sign-button"));
    await waitFor(() => expect(screen.getByTestId("signature-list")).toHaveTextContent(/reviewed by Riley/i));

    act(() => setIdentity("sam.qa"));
    await userEvent.type(screen.getByTestId("sign-pin"), "3333");
    await userEvent.click(screen.getByTestId("sign-button"));
    await waitFor(() => expect(screen.getByTestId("approval-status")).toHaveTextContent("Approved"));
    expect(screen.getByTestId("signature-list")).toHaveTextContent(/approved by Sam/i);
  });

  it("shows the same wrong-PIN copy as the Approvals page", async () => {
    const approval: ApprovalView = {
      id: "ap-1", record_type: "scenario", record_id: "sc-1", record_hash: "ab".repeat(32), author: "alex.author",
      required_meanings: ["reviewed", "approved"], status: "pending", created_at: "2026-10-16T12:00:00Z", title: "Scenario B",
      signatures: [], next_meaning: "reviewed",
    };
    vi.spyOn(api, "sign").mockRejectedValueOnce(new ApiError(401, "invalid_credential", "Unknown user or wrong PIN."));
    act(() => setIdentity("riley.reviewer"));
    render(<ApprovalPanel approval={approval} onChange={vi.fn()} />);
    await userEvent.type(screen.getByTestId("sign-pin"), "9999");
    await userEvent.click(screen.getByTestId("sign-button"));
    expect(await screen.findByTestId("sign-error")).toHaveTextContent(/^Wrong PIN — the signature was not recorded\.$/);
  });
});

describe("lever summary and default save name", () => {
  const summary = () => screen.getByText("Impact forecast · vs baseline").parentElement as HTMLElement;
  async function defaultSaveName() {
    await waitFor(() => expect(screen.getByTestId("save-scenario")).toBeEnabled(), { timeout: 4000 });
    await userEvent.click(screen.getByTestId("save-scenario"));
    return screen.getByTestId("save-name");
  }

  it("labels and names untouched levers Baseline", async () => {
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    expect(within(summary()).getByText("Baseline")).toBeInTheDocument();
    expect(await defaultSaveName()).toHaveValue("Baseline");
  });

  it("labels and names a scenario that only changes enrollment speed", async () => {
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    fireEvent.change(screen.getByTestId("lever-enrollment-rate"), { target: { value: "120" } });
    expect(within(summary()).getByText("120% enrollment speed")).toBeInTheDocument();
    expect(within(summary()).queryByText("Baseline")).not.toBeInTheDocument();
    try {
      act(() => setLanguage("zh"));
      expect(screen.getByText("120% 入组速度")).toBeInTheDocument();
    } finally {
      act(() => setLanguage("en"));
    }
    expect(await defaultSaveName()).toHaveValue("Scenario — 120% enrollment speed");
  });

  it("labels and names a scenario that only adds countries, in both languages", async () => {
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    fireEvent.change(screen.getByTestId("lever-added-countries"), { target: { value: "2" } });
    expect(within(summary()).getByText("2 planned added countries")).toBeInTheDocument();
    expect(within(summary()).queryByText("Baseline")).not.toBeInTheDocument();
    try {
      act(() => setLanguage("zh"));
      expect(screen.getByText("规划新增 2 个国家")).toBeInTheDocument();
    } finally {
      act(() => setLanguage("en"));
    }
    expect(await defaultSaveName()).toHaveValue("Scenario — 2 planned added countries");
  });
});

describe("import page", () => {
  it.each([false, true])("uses live refresh unless the API is explicitly offline (offline=%s)", async (offline) => {
    vi.spyOn(api, "health").mockResolvedValue({ status: "ok", offline });
    const registry = vi.spyOn(api, "importCtgov");
    const protocol = vi.spyOn(api, "importProtocol");
    try {
      renderAt("/");
      await screen.findByTestId("demo-chips");
      expect(screen.getByText("Trial library")).toBeInTheDocument();
      await userEvent.type(screen.getByTestId("nct-input"), "NCT01234567");
      await userEvent.click(screen.getByTestId("nct-submit"));
      await screen.findByTestId("trial-card", {}, { timeout: 4000 });
      expect(registry).toHaveBeenCalledWith("NCT01234567", { silent: true, refresh: !offline });
      expect(screen.getByTestId("extract-registry")).toHaveTextContent("Extract registry protocol");
      if (!offline) expect(screen.getByTestId("extract-registry")).not.toHaveTextContent("cached extraction");

      await userEvent.click(screen.getByTestId("extract-registry"));
      await screen.findByTestId("protocol-review", {}, { timeout: 4000 });
      expect(protocol).toHaveBeenLastCalledWith({ nctId: MOCK_DESIGN.registry_id, refresh: !offline }, DESIGN, { silent: true });

      const file = new File(["protocol"], "trial.pdf", { type: "application/pdf" });
      await userEvent.upload(screen.getByTestId("protocol-file"), file);
      await waitFor(() => expect(protocol).toHaveBeenLastCalledWith({ file, refresh: !offline }, DESIGN, { silent: true }));
      await screen.findByTestId("protocol-review", {}, { timeout: 4000 });
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("validates the NCT id inline and shows the trial card with the missing & assumed list after import", async () => {
    renderAt("/");
    await userEvent.type(screen.getByTestId("nct-input"), "NCT123");
    await userEvent.click(screen.getByTestId("nct-submit"));
    expect(screen.getByRole("alert")).toHaveTextContent(/8 digits/);

    await userEvent.clear(screen.getByTestId("nct-input"));
    await userEvent.type(screen.getByTestId("nct-input"), "NCT01234567");
    await userEvent.click(screen.getByTestId("nct-submit"));
    const card = await screen.findByTestId("trial-card", {}, { timeout: 4000 });
    expect(card).toHaveTextContent("MOCK — Fictional");
    expect(screen.getByTestId("missing-assumed")).toHaveTextContent(/Visits/);
    expect(screen.getByTestId("missing-assumed")).toHaveTextContent(/to confirm/i);
    expect(screen.getByTestId("missing-assumed")).toHaveTextContent(/actual number enrolled/i);
    expect(screen.getByTestId("missing-count")).toHaveTextContent("1");
    expect(screen.getByTestId("import-design-version")).toHaveTextContent("design v1");
  });

  it("saves a trial that is not already stored, then opens it in the simulator", async () => {
    const save = vi.spyOn(api, "saveDesign");
    renderAt("/");
    await userEvent.type(screen.getByTestId("nct-input"), "NCT04456673");
    await userEvent.click(screen.getByTestId("nct-submit"));
    expect(await screen.findByTestId("trial-card", {}, { timeout: 4000 })).toHaveTextContent("Imported NCT04456673");
    expect(save).toHaveBeenCalled();
    expect(screen.getByTestId("import-design-version")).toHaveTextContent("design v1");

    await userEvent.click(screen.getByTestId("open-simulator"));
    expect(await screen.findByTestId("design-version", {}, { timeout: 4000 })).toHaveTextContent("design v1");
    expect(screen.queryByText(/was not found/i)).not.toBeInTheDocument();
    await waitForCards();
  });

  it("refuses to overwrite a design that changed, and keeps the schedule on screen", async () => {
    renderAt("/");
    await userEvent.type(screen.getByTestId("nct-input"), "NCT01234567");
    await userEvent.click(screen.getByTestId("nct-submit"));
    const card = await screen.findByTestId("trial-card", {}, { timeout: 4000 });
    expect(card).toHaveTextContent("480 patients");

    const current = await api.getDesign(DESIGN);
    await api.saveDesign({ ...current.design, enrollment_target: 50 }, { ifMatch: current.etag ?? undefined });

    await userEvent.click(screen.getByRole("button", { name: "Edit facts" }));
    const enrollment = screen.getByLabelText("Enrollment target");
    await userEvent.clear(enrollment);
    await userEvent.type(enrollment, "200");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByTestId("design-conflict")).toHaveTextContent(/design v2/);
    expect(screen.getByTestId("trial-card")).toHaveTextContent("480 patients");
    expect(screen.getByTestId("trial-card")).not.toHaveTextContent("50 patients");
  });

  it("disables Save changes for an empty enrollment, then stores the edit as a new design version", async () => {
    renderAt("/");
    await userEvent.type(screen.getByTestId("nct-input"), "NCT01234567");
    await userEvent.click(screen.getByTestId("nct-submit"));
    await screen.findByTestId("trial-card", {}, { timeout: 4000 });
    expect(screen.getByTestId("stored-design-banner")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Edit facts" }));
    const enrollment = screen.getByLabelText("Enrollment target");
    await userEvent.clear(enrollment);
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    await userEvent.type(enrollment, "0");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    await userEvent.clear(enrollment);
    await userEvent.type(enrollment, "200");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(screen.getByTestId("trial-card")).toHaveTextContent("200 patients"));
    expect(screen.getByTestId("import-design-version")).toHaveTextContent("design v2");
    expect(screen.queryByTestId("stored-design-banner")).not.toBeInTheDocument();
  });

  it("shows a malformed import or extraction message without an 'Error:' prefix", async () => {
    vi.spyOn(api, "importCtgov").mockRejectedValueOnce(new Error("The registry response has no design."));
    renderAt("/");
    await userEvent.type(screen.getByTestId("nct-input"), "NCT01234567");
    await userEvent.click(screen.getByTestId("nct-submit"));
    expect((await screen.findByTestId("import-error")).textContent).toBe("The registry response has no design.");
    await userEvent.click(screen.getByTestId("nct-submit"));
    await screen.findByTestId("trial-card", {}, { timeout: 4000 });
    expect(screen.queryByTestId("import-error")).not.toBeInTheDocument();

    const message = "The protocol response contains an invalid visit, week or procedure.";
    vi.spyOn(api, "importProtocol").mockRejectedValueOnce(new Error(message));
    await userEvent.click(screen.getByTestId("extract-registry"));
    expect((await screen.findByText(/invalid visit, week or procedure/)).textContent).toBe(message);
    expect(screen.getByTestId("extract-registry")).toBeEnabled();
  });

  it("does not save an empty week as 0, and logs rows accepted without opening them", async () => {
    const log = vi.spyOn(api, "logProtocolReview");
    renderAt("/");
    await userEvent.type(screen.getByTestId("nct-input"), "NCT01234567");
    await userEvent.click(screen.getByTestId("nct-submit"));
    await screen.findByTestId("trial-card", {}, { timeout: 4000 });
    await userEvent.click(screen.getByTestId("extract-registry"));
    const review = await screen.findByTestId("protocol-review", {}, { timeout: 4000 });

    await userEvent.click(within(review).getByRole("button", { name: "Edit visit 1" }));
    await userEvent.clear(within(review).getByLabelText("Visit 1 week"));
    expect(within(review).getByRole("button", { name: "Done" })).toBeDisabled();
    expect(review).toHaveTextContent("Enter a valid week.");

    await userEvent.click(within(review).getByRole("button", { name: "Accept remaining" }));
    await userEvent.click(screen.getByTestId("apply-extraction"));
    await waitFor(() => expect(screen.queryByTestId("protocol-review")).not.toBeInTheDocument(), { timeout: 4000 });
    await waitFor(() => expect(log).toHaveBeenCalled());
    expect(log.mock.calls[0][0].bulk_accepted).toBeGreaterThan(0);
    expect(screen.getByTestId("missing-assumed")).not.toHaveTextContent(/Visit schedule is NOT/i);
    expect(screen.getByTestId("missing-assumed")).toHaveTextContent(/actual number enrolled/i);
    expect(screen.getByTestId("missing-count")).toHaveTextContent("0");
  });

  it("loads demo chips after the API becomes reachable", async () => {
    let up = false;
    vi.spyOn(api, "health").mockImplementation(async () => {
      if (!up) throw new ApiError(0, "network_error", "Can't reach the TrialPilot API. Check that the server is running.");
      return { status: "ok", offline: true };
    });
    vi.spyOn(api, "listDesigns").mockResolvedValue([]);
    vi.spyOn(api, "cachedStudies").mockResolvedValue([
      {
        nct_id: "NCT04456673",
        title: "NOTUS",
        acronym: "NOTUS",
        phase: "Phase 3",
        drug_type: "biologic",
        sites: 29,
        sponsor: "Sanofi",
        protocol_extraction_cached: true,
      },
    ]);
    vi.useFakeTimers();
    try {
      renderAt("/");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.queryByText("NCT04456673")).not.toBeInTheDocument();
      up = true;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(screen.getByText("NCT04456673")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
      vi.restoreAllMocks();
    }
  });
});

describe("procedure groups", () => {
  it("keeps every label under one code, with occurrence and visit counts", () => {
    const visits: Visit[] = [
      {
        number: 1,
        label: "A",
        week: 0,
        can_be_remote: false,
        procedures: [
          { ...endpointProcedure("Review electronic diary"), site_minutes: 5 },
          { ...endpointProcedure("SGRQ"), site_minutes: 5 },
        ],
      },
      {
        number: 2,
        label: "B",
        week: 4,
        can_be_remote: true,
        procedures: [{ ...endpointProcedure("EQ-5D-5L"), site_minutes: 5 }],
      },
    ];
    const [row] = groupProcedures(visits);
    expect(row.meaning).toBe("Questionnaire / patient-reported outcome / diary review");
    expect(row.labels).toEqual(["EQ-5D-5L", "Review electronic diary", "SGRQ"]);
    expect(row.occurrences).toBe(3);
    expect(row.visits).toBe(2);
  });

  it("shows the vocabulary meaning, the protocol label, and both counts on the lever", async () => {
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    const row = screen.getByTestId("procedure-questionnaire");
    expect(row).toHaveTextContent("Questionnaire / patient-reported outcome / diary review");
    expect(row).toHaveTextContent("Patient questionnaire");
    expect(row).toHaveTextContent("11 times");
    expect(row).toHaveTextContent("at 11 visits");
    const spiro = screen.getByTestId("procedure-spirometry");
    expect(spiro).toHaveTextContent("Spirometry");
    expect(spiro).toHaveTextContent("4 times");
    expect(spiro).toHaveTextContent("at 4 visits");
  });
});

function endpointProcedure(label: string, patch: Partial<Procedure> = {}): Procedure {
  return {
    code: "questionnaire", label, site_minutes: 5, ships_sample: false, sample_temp: null,
    endpoint_role: "unknown", endpoint_note: "", link_basis: "unmatched", ...patch,
  };
}

describe("procedure endpoint roles", () => {
  const candidate = (procedures: Procedure[]): ExtractionCandidate => ({
    visit: { number: 1, week: 12, label: "Week 12", can_be_remote: false, procedures },
    source_page: 1, quote: "Week 12 assessments", confidence: 1,
  });

  it("edits one assessment within a shared code, records human provenance, and counts the row as edited", async () => {
    const apply = vi.fn();
    const original = candidate([
      endpointProcedure("SGRQ", { endpoint_role: "supports_primary", endpoint_note: "primaryOutcomes: SGRQ — Week 12", link_basis: "outcome_title" }),
      endpointProcedure("EQ-5D-5L"),
    ]);
    render(<ProtocolReview candidates={[original]} warnings={[]} canApply applying={false} onApply={apply} />);
    expect(screen.getByText("Supports primary outcome")).toBeInTheDocument();
    expect(screen.getByText("To confirm")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Edit visit 1" }));
    await userEvent.selectOptions(screen.getByLabelText("Visit 1 SGRQ endpoint role"), "supports_secondary");
    expect(screen.getByLabelText("Visit 1 SGRQ endpoint note")).toHaveValue("");
    await userEvent.type(screen.getByLabelText("Visit 1 SGRQ endpoint note"), "Confirmed against protocol.");
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await userEvent.click(screen.getByTestId("apply-extraction"));
    const [visits, stats] = apply.mock.calls[0];
    expect(visits[0].procedures).toHaveLength(2);
    expect(visits[0].procedures[0]).toMatchObject({ endpoint_role: "supports_secondary", endpoint_note: "Confirmed against protocol.", link_basis: "human" });
    expect(visits[0].procedures[1]).toEqual(original.visit.procedures[1]);
    expect(stats).toEqual({ accepted: 0, edited: 1, rejected: 0, bulk_accepted: 0 });
    expect(original.visit.procedures[0].link_basis).toBe("outcome_title");
  });

  it("saves a note-only human decision without changing an unknown role", async () => {
    const apply = vi.fn();
    render(<ProtocolReview candidates={[candidate([endpointProcedure("Diary")])]} warnings={[]} canApply applying={false} onApply={apply} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit visit 1" }));
    await userEvent.type(screen.getByLabelText("Visit 1 Diary endpoint note"), "Link still needs confirmation.");
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await userEvent.click(screen.getByTestId("apply-extraction"));
    expect(apply.mock.calls[0][0][0].procedures[0]).toMatchObject({ endpoint_role: "unknown", link_basis: "human", endpoint_note: "Link still needs confirmation." });
    expect(apply.mock.calls[0][1].edited).toBe(1);
  });

  it("accepts legacy candidates as unknown without inventing a human decision", async () => {
    const apply = vi.fn();
    // Deliberately simulate pre-field persisted JSON; the API supplies defaults, old mocks do not.
    const legacy = { code: "ecg", label: "ECG", site_minutes: 20, ships_sample: false, sample_temp: null } as Procedure;
    render(<ProtocolReview candidates={[candidate([legacy])]} warnings={[]} canApply applying={false} onApply={apply} />);
    expect(screen.getByText("To confirm")).toBeInTheDocument();
    expect(screen.getByText("Unmatched")).toBeInTheDocument();
    expect(screen.queryByText(/optional|non.core/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept remaining" }));
    await userEvent.click(screen.getByTestId("apply-extraction"));
    expect(apply.mock.calls[0][0][0].procedures[0]).toEqual(legacy);
    expect(apply.mock.calls[0][1]).toEqual({ accepted: 1, edited: 0, rejected: 0, bulk_accepted: 1 });
  });

  it("removes only the clicked assessment when two share a code", async () => {
    const apply = vi.fn();
    const eq5d = endpointProcedure("EQ-5D-5L");
    render(<ProtocolReview candidates={[candidate([endpointProcedure("SGRQ"), eq5d])]} warnings={[]} canApply applying={false} onApply={apply} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit visit 1" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove SGRQ" }));
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await userEvent.click(screen.getByTestId("apply-extraction"));
    const [visits, stats] = apply.mock.calls[0];
    expect(visits[0].procedures).toEqual([eq5d]);
    expect(stats.edited).toBe(1);
  });

  it("keeps counting an edited row as edited after Accept", async () => {
    const apply = vi.fn();
    render(<ProtocolReview candidates={[candidate([endpointProcedure("SGRQ")])]} warnings={[]} canApply applying={false} onApply={apply} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit visit 1" }));
    await userEvent.type(screen.getByLabelText("Visit 1 label"), " (V5)");
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await userEvent.click(screen.getByRole("button", { name: "Accept visit 1" }));
    expect(screen.getByText("✎ Edited")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("apply-extraction"));
    expect(apply.mock.calls[0][0][0].label).toBe("Week 12 (V5)");
    expect(apply.mock.calls[0][1]).toEqual({ accepted: 0, edited: 1, rejected: 0, bulk_accepted: 0 });
  });

  it("still counts an unedited row as accepted after Reject then Accept", async () => {
    const apply = vi.fn();
    render(<ProtocolReview candidates={[candidate([endpointProcedure("SGRQ")])]} warnings={[]} canApply applying={false} onApply={apply} />);
    await userEvent.click(screen.getByRole("button", { name: "Reject visit 1" }));
    await userEvent.click(screen.getByRole("button", { name: "Accept visit 1" }));
    expect(screen.getByText("✓ Accepted")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("apply-extraction"));
    expect(apply.mock.calls[0][1]).toEqual({ accepted: 1, edited: 0, rejected: 0, bulk_accepted: 0 });
  });

  it("shows distinct roles in a shared-code removal row and leaves removal under the existing lever", async () => {
    const change = vi.fn();
    const design = { ...MOCK_DESIGN, visits: [candidate([
      endpointProcedure("Primary score", { endpoint_role: "supports_primary", link_basis: "outcome_title" }),
      endpointProcedure("Secondary score", { endpoint_role: "supports_secondary", link_basis: "outcome_title" }),
      endpointProcedure("Diary", { endpoint_role: "not_linked", link_basis: "human" }),
      endpointProcedure("Unreviewed score"),
    ]).visit] };
    const { rerender } = render(<LeversPanel design={design} levers={DEFAULT_LEVERS} onChange={change} />);
    const row = screen.getByTestId("procedure-questionnaire");
    expect(row).toHaveTextContent("Primary score: Supports primary outcome");
    expect(row).toHaveTextContent("Secondary score: Supports secondary outcome");
    expect(row).toHaveTextContent("Diary: Not linked to a registry outcome");
    expect(row).toHaveTextContent("Unreviewed score: To confirm");
    expect(within(row).queryByRole("status")).not.toBeInTheDocument();
    expect(within(row).getByRole("checkbox")).not.toBeChecked();
    await userEvent.click(within(row).getByRole("checkbox"));
    expect(change).toHaveBeenLastCalledWith({ ...DEFAULT_LEVERS, removed_procedures: ["questionnaire"] });
    rerender(<LeversPanel design={design} levers={change.mock.calls[0][0]} onChange={change} />);
    expect(within(row).getByRole("checkbox")).toBeChecked();
    expect(row).toHaveTextContent("This procedure is tied to a primary outcome.");
    expect(row).toHaveTextContent("No primary or secondary outcome in the registry record matches this procedure.");
    expect(within(row).getAllByRole("status")).toHaveLength(2);
    await userEvent.click(within(row).getByRole("checkbox"));
    expect(change).toHaveBeenLastCalledWith(DEFAULT_LEVERS);
    rerender(<LeversPanel design={design} levers={DEFAULT_LEVERS} onChange={change} />);
    expect(within(row).queryByRole("status")).not.toBeInTheDocument();
  });

  it("keeps unknown removal neutral and recomputes cost, staff hours and carbon through the existing scenario API", async () => {
    const compute = vi.spyOn(api, "compute");
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    const row = screen.getByTestId("procedure-questionnaire");
    expect(row).toHaveTextContent("Patient questionnaire: To confirm");
    const beforeHours = screen.getByTestId("metric-site_staff_hours-value").textContent;
    const expected = mockCompute(MOCK_DESIGN, { ...DEFAULT_LEVERS, removed_procedures: ["questionnaire"] });
    await userEvent.click(within(row).getByRole("checkbox"));
    await waitFor(() => expect(compute.mock.calls.some(([, levers]) => levers.removed_procedures.includes("questionnaire"))).toBe(true), { timeout: 4000 });
    await waitFor(() => expect(screen.getByTestId("metric-site_staff_hours-value").textContent).not.toBe(beforeHours), { timeout: 4000 });
    for (const key of ["cost_usd", "site_staff_hours", "co2e_kg"] as const) {
      expect(screen.getByTestId(`metric-${key}-value`)).toHaveAccessibleName(expect.stringContaining(`median ${formatValue(expected[key].p50, expected[key].unit)}`));
    }
    expect(within(row).queryByRole("status")).not.toBeInTheDocument();
    expect(row).not.toHaveTextContent(/optional|non.core/i);
  });
});

describe("pinned design version and missing forecast", () => {
  it("sends the loaded design version with every compute", async () => {
    const computeSpy = vi.spyOn(api, "compute");
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    expect(screen.getByTestId("design-version")).toHaveTextContent("design v1");
    expect(computeSpy.mock.calls.every((call) => call[2]?.designVersion === 1)).toBe(true);
  });

  it("explains a missing forecast instead of drawing a curve from duration", () => {
    const result = { ...mockCompute(MOCK_DESIGN, DEFAULT_LEVERS), forecast: null, supply: null };
    render(<ForecastChart result={result} target={MOCK_DESIGN.enrollment_target} />);
    expect(screen.getByTestId("forecast-missing")).toHaveTextContent("Enrollment curve unavailable");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("labels a well-to-tank term and keeps an unknown input visible", async () => {
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    await userEvent.click(screen.getByTestId("metric-co2e_kg-value"));
    const drawer = await screen.findByTestId("provenance-drawer");
    expect(within(drawer).getByTestId("wtt-label")).toHaveTextContent("Well-to-tank");
    expect(drawer).toHaveTextContent(/unknown — mock library has no ef\.wtt factor/i);
    expect(drawer).toHaveTextContent("Parameter missing");
  });
});

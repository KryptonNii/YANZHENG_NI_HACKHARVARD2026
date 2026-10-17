/**
 * Scenario simulator behaviour against the in-browser mock API (the same fetch path the real
 * API uses). Requirement tags follow A7's URS ids where they exist (see handoffs/A8.md).
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/app/api/client";
import { installMockApi, resetMockStore } from "@/app/api/mock";
import { MOCK_PARAMS } from "@/app/api/mock/data";
import { setIdentity } from "@/app/identity";
import { ToastProvider } from "@/app/toast";
import { nctError, normalizeNct } from "./demoTrials";
import { resetParamLibrary } from "./hooks/useParamLibrary";
import { ImportPage } from "./ImportPage";
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
    expect(deltaText).toMatch(/lower than baseline|higher than baseline/);
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
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
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
    expect(within(drawer).getAllByText("Assumption").length).toBeGreaterThan(0);
    expect(within(drawer).getAllByText(/Rationale:/).length).toBeGreaterThan(0);

    await waitFor(() => expect(within(drawer).getByTestId("provenance-drivers")).toBeInTheDocument());
    expect(within(drawer).getByTestId("provenance-drivers").querySelectorAll("li")).toHaveLength(5);
  });

  it("blocks self-approval with a plain message, then reviewer and QA signatures approve the scenario", async () => {
    renderAt(`/scenario/${DESIGN}`);
    await waitForCards();
    await userEvent.click(screen.getByRole("radio", { name: "On-demand resupply" }));

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
    expect(await screen.findByTestId("sign-error")).toHaveTextContent("Authors can't approve their own work.");

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
});

describe("import page", () => {
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
    expect(screen.getByTestId("missing-assumed")).toHaveTextContent(/assumed/i);
  });
});

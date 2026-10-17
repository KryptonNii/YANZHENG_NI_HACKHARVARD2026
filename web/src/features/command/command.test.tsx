/**
 * Command center against a fetch stub of A6's envelopes.
 * // @req URS-011 URS-012 URS-013
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import CommandPage from "./index";

const ACTION = "Switch the site to on-demand (IRT-triggered) resupply and return excess kits to the depot";

const alert = {
  id: "alert-1",
  trial_id: "demo-40",
  site_id: "S14",
  kind: "drug_overstock",
  severity: "warning",
  detected_at: "2026-10-16T00:00:00Z",
  summary: "Site 14 drug overstock, kits projected to expire",
  est_impact: {
    cost_usd: { p10: 1000, p50: 2000, p90: 4000, unit: "usd" },
    co2e_kg: { p10: 10, p50: 20, p90: 40, unit: "kg_co2e" },
  },
  recommended_actions: [ACTION],
  status: "open",
};

const health = {
  trial_id: "demo-40",
  trial_title: "Demo 40-site trial",
  as_of: "2026-10-16T00:00:00Z",
  simulated: true,
  data_label: "Simulated feed",
  kpis: [
    {
      id: "enrollment",
      label: "Enrollment vs plan band",
      unit: "patients",
      value: 120,
      value_text: null,
      plan: { p10: 100, p50: 140, p90: 180, unit: "patients" },
      status: "watch",
    },
  ],
  countries: [],
  sites: [
    {
      site_id: "S14",
      name: "Site 14",
      city: "Boston",
      country: "US",
      status: "active",
      enrolled: 8,
      planned_to_date: { p10: 6, p50: 10, p90: 14, unit: "patients" },
      open_queries: 3,
      median_query_age_days: 9,
      drug_on_hand_kits: 40,
      drug_need_kits: { p10: 4, p50: 8, p90: 12, unit: "kits" },
    },
  ],
  study: {
    enrollment: { value: 120, target: 400, status: "watch" },
    open_queries: { value: 18, median_age_days: 11 },
    sites_status: { value: { active: 30, stalled: 2, never_enrolled: 1 } },
  },
  clock: {
    trial_id: "demo-40",
    run_id: "run",
    clock_day: 406,
    now: "2026-10-16T00:00:00Z",
    epoch: "2025-09-01T00:00:00Z",
    horizon_day: 700,
    speed_days_per_second: 0,
    seed: 42,
    scenario: "demo",
    simulated: true,
  },
  provenance: {},
  plan_notes: [],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("command center", () => {
  const interventions: unknown[] = [];

  beforeEach(() => {
    interventions.length = 0;
    class FakeEventSource {
      addEventListener() {}
      close() {}
    }
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.includes("/health") && method === "GET") return json(health);
        if (url.includes("/alerts") && method === "GET") return json({ items: [alert], simulated: true });
        if (url.includes("/interventions") && method === "POST") {
          const body = JSON.parse(String(init?.body)) as { action: string; owner: string };
          const created = {
            id: "iv-1",
            trial_id: "demo-40",
            alert_id: "alert-1",
            action: body.action,
            owner: body.owner,
            due_date: "2026-11-13T00:00:00Z",
            target_site_ids: ["S14"],
            metric: "kits_on_hand",
            started_at: null,
            status: "planned",
          };
          interventions.push(created);
          return json(created, 201);
        }
        if (url.includes("/interventions") && method === "GET") return json({ items: interventions, simulated: true });
        if (url.includes("/effects")) return json({ items: [], simulated: true });
        if (url.includes("/events")) return json({ items: [], total: 0, simulated: true });
        return json({ error: "not_found", message: url, details: {} }, 404);
      }),
    );
  });

  it("plans an intervention from an alert", async () => {
    render(
      <MemoryRouter initialEntries={["/command/demo-40"]}>
        <Routes>
          <Route path="/command/:trialId" element={<CommandPage />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText(/Site 14 drug overstock/)).toBeInTheDocument();
    expect(screen.getByText("Simulated feed")).toBeInTheDocument();
    expect(screen.getAllByText("not estimated").length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: "Plan intervention" }));
    await userEvent.click(screen.getByRole("button", { name: "Save intervention" }));

    await waitFor(() => expect(screen.getByTestId("intervention-list")).toHaveTextContent(/on-demand/i));
  });
});

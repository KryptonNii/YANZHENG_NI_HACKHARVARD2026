/**
 * Predicted outcome of each action, the prediction saved with the intervention, and its follow-up.
 * // @req URS-012
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Alert, Intervention } from "@/app/contracts";
import type { AlertOptions, EffectDetail, Expectation, Reconciliation } from "./api";
import { AlertsPanel } from "./AlertsPanel";
import { InterventionsPanel } from "./InterventionsPanel";

const ON_DEMAND = "Switch the site to on-demand (IRT-triggered) resupply and return excess kits to the depot";
const TRANSFER = "Transfer excess kits to the regional depot before they expire";
const FEASIBILITY = "Hold a feasibility call with the site to review its pre-screening log";

const range = (p10: number, p50: number, p90: number, unit: string) => ({ p10, p50, p90, unit });

const alert: Alert = {
  id: "alert-1",
  trial_id: "demo-40",
  site_id: "S14",
  kind: "drug_overstock",
  severity: "critical",
  detected_at: "2026-10-16T00:00:00Z",
  summary: "Site 14 drug overstock, kits projected to expire",
  est_impact: { cost_usd: range(49000, 105000, 187000, "usd") },
  recommended_actions: [ON_DEMAND, TRANSFER, FEASIBILITY],
  status: "open",
};

const options: AlertOptions = {
  alert_id: "alert-1",
  ranked_by: "net_usd P50 (cost avoided minus action cost)",
  model_label: "Planning model with assumed parameters. A prediction, not an observed result.",
  computed_at_day: 406,
  baseline: { delay_days: null, cost_usd: range(49000, 105000, 187000, "usd") as never, description: "Doing nothing" },
  best_net_positive: true,
  items: [
    {
      action: ON_DEMAND, code: "supply_on_demand", label: ON_DEMAND, quantified: true, rank: 1,
      delay_saved_days: null,
      cost_avoided_usd: range(36000, 80000, 147000, "usd"), action_cost_usd: range(4000, 7000, 11000, "usd"),
      net_usd: range(29000, 72000, 140000, "usd"),
      warnings: ["Little projected waste: the expected value is small."],
      reasoning: ["The site holds 120 kits."], assumptions: ["ops.effect.on_demand_waste_avoided_share: ASSUMPTION"],
    },
    {
      action: TRANSFER, code: "transfer_excess", label: TRANSFER, quantified: true, rank: 2,
      delay_saved_days: null,
      cost_avoided_usd: range(28000, 62000, 116000, "usd"), action_cost_usd: range(1000, 1900, 3000, "usd"),
      net_usd: range(26000, 60000, 114000, "usd"),
    },
    { action: FEASIBILITY, code: "feasibility_call", label: FEASIBILITY, quantified: false, reason: "No quantitative model for this action; it is listed but not ranked." },
  ],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("action options in the plan dialog", () => {
  const posted: Array<{ action: string }> = [];

  beforeEach(() => {
    posted.length = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        const method = init?.method ?? "GET";
        if (url.includes("/alerts/alert-1") && method === "GET") return json({ alert, options, simulated: true });
        if (url.includes("/interventions") && method === "POST") {
          posted.push(JSON.parse(String(init?.body)) as { action: string });
          return json({ id: "iv-1" }, 201);
        }
        return json({ error: "not_found", message: url, details: {} }, 404);
      }),
    );
  });

  it("ranks the quantified actions and lets a row choose the action", async () => {
    const user = userEvent.setup();
    render(<AlertsPanel trialId="demo-40" alerts={[alert]} owner="alex" onChanged={async () => undefined} />);
    await user.click(screen.getByRole("button", { name: /plan intervention/i }));

    const table = await screen.findByTestId("action-options");
    expect(within(table).getByText(/a prediction, not an observed result/i)).toBeInTheDocument();
    expect(within(table).getByTestId("option-baseline")).toHaveTextContent(/do nothing/i);
    const first = within(table).getByTestId("option-supply_on_demand");
    expect(first).toHaveTextContent("#1");
    expect(within(table).getByTestId("option-transfer_excess")).toHaveTextContent("#2");
    expect(first).toHaveTextContent(/little projected waste/i);
    expect(within(table).getByTestId("option-feasibility_call")).toHaveTextContent(/not ranked/i);

    await user.click(within(within(table).getByTestId("option-transfer_excess")).getByRole("button", { name: /#2/ }));
    expect(screen.getByRole("combobox")).toHaveValue(TRANSFER);
    await user.click(screen.getByRole("button", { name: /save intervention/i }));
    await waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].action).toBe(TRANSFER);
  });

  it("still plans an action when no prediction is available", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ alert, options: null, simulated: true })));
    const user = userEvent.setup();
    render(<AlertsPanel trialId="demo-40" alerts={[alert]} owner="alex" onChanged={async () => undefined} />);
    await user.click(screen.getByRole("button", { name: /plan intervention/i }));
    expect(await screen.findByRole("combobox")).toHaveValue(ON_DEMAND);
    expect(screen.queryByTestId("action-options")).not.toBeInTheDocument();
  });
});

const iv: Intervention = {
  id: "iv-1", trial_id: "demo-40", alert_id: "alert-1", action: ON_DEMAND, owner: "alex",
  due_date: "2026-11-13T00:00:00Z", target_site_ids: ["S14"], metric: "kits_on_hand",
  started_at: "2026-10-12T00:00:00Z", status: "in_progress",
};

const expectation: Expectation = {
  action: ON_DEMAND, code: "supply_on_demand", label: ON_DEMAND, quantified: true, alert_id: "alert-1",
  computed_at: "2026-10-12", frozen: true,
  delay_saved_days: null, cost_avoided_usd: range(36000, 80000, 147000, "usd"),
  action_cost_usd: range(4000, 7000, 11000, "usd"), net_usd: range(29000, 72000, 140000, "usd"),
};

function effectWith(reconciliation: Partial<Reconciliation>): EffectDetail {
  return {
    estimate: {
      intervention_id: "iv-1", method: "diff_in_diff", effect: range(-80, -75, -70, "kits") as never,
      treated_change: -80, control_change: -5, verdict: "likely_worked", explanation: "The change exceeds the controls.",
    },
    expectation,
    reconciliation: {
      verdict: "met", explanation: "The observed effect is real and consistent with the predicted range.",
      predicted: range(-62, -43, -25, "kits"), observed: { ...range(-87, -85, -83, "kits"), ci95: [-100, -75] },
      post_weeks: 12, needs_replan: false, replan_min_weeks: 6, metric_label: "Drug kits on hand", unit: "kits",
      basis: "Compared on drug kits on hand. The predicted days and dollars follow from the same model and are not observed separately.",
      alert_id: "alert-1", model_label: "Planning model with assumed parameters. A prediction, not an observed result.",
      share_of_effect_in_window: 0.9, ...reconciliation,
    },
  };
}

describe("prediction versus observation on an intervention", () => {
  const render1 = (effect: EffectDetail) =>
    render(<InterventionsPanel trialId="demo-40" interventions={[iv]} effects={[effect]} onChanged={async () => undefined} />);

  it("shows the saved prediction next to the observed effect and says what the comparison covers", () => {
    render1(effectWith({}));
    const card = screen.getByTestId("prediction-card");
    expect(card).toHaveTextContent("2026-10-12");
    expect(screen.getByTestId("reconcile-verdict")).toHaveTextContent(/as predicted/i);
    expect(screen.getByTestId("reconcile-detail")).toHaveTextContent(/predicted −43 \(−62 – −25\)/);
    expect(screen.getByTestId("reconcile-detail")).toHaveTextContent(/observed −85 \(95% interval −100 – −75\)/);
    expect(card).toHaveTextContent(/not observed separately/i);
    expect(screen.queryByTestId("replan-banner")).not.toBeInTheDocument();
  });

  it("asks the user to re-plan when the action fell short", () => {
    render1(effectWith({ verdict: "not_met", needs_replan: true, post_weeks: 8, explanation: "The observed interval rules out the predicted effect." }));
    expect(screen.getByTestId("reconcile-verdict")).toHaveTextContent(/below prediction/i);
    expect(screen.getByTestId("replan-banner")).toHaveTextContent(/below its predicted effect after 8 weeks/i);
    expect(screen.getByTestId("replan-banner")).toHaveTextContent(/reopened/i);
  });

  it("says when there is not enough data to compare yet", () => {
    render1(effectWith({ verdict: "insufficient_data", predicted: null, observed: null, post_weeks: 0, explanation: "Too early: 1 complete week(s) of data after the start." }));
    expect(screen.getByTestId("reconcile-verdict")).toHaveTextContent(/not enough data yet/i);
    expect(screen.getByTestId("reconcile-detail")).toHaveTextContent(/too early/i);
  });

  it("shows no prediction card for an action without a saved prediction", () => {
    render1({ ...effectWith({}), expectation: null, reconciliation: null });
    expect(screen.queryByTestId("prediction-card")).not.toBeInTheDocument();
  });
});

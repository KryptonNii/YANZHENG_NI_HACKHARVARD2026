import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import truth from "../../../../data/fixtures/ops/ground_truth.json";
import design from "../../../../data/fixtures/ops/demo_trial_40_sites.json";
import { LockRecoveryStory } from "./LockRecoveryStory";
import { daysBetween, initialReplay, lockDate, lockEvidence, lockStory, replayForecast, replayReducer } from "./lockStory";

const answer = truth.command_lock_recovery;
const labels: Record<string, string> = {
  likely_worked: "Likely worked", inconclusive: "Inconclusive", likely_coincidence: "Likely coincidence",
};

describe("database-lock recovery replay", () => {
  it("shows the slip, then actionable interventions, then two judgments matching withheld ground truth", async () => {
    const user = userEvent.setup();
    render(<LockRecoveryStory />);
    const sequence = within(screen.getByRole("list", { name: "Replay steps" })).getAllByRole("listitem");
    expect(sequence.map((item) => item.textContent)).toEqual([
      "1.Lock risk", "2.Interventions", "3.Effect review",
    ]);
    expect(sequence[0]).toHaveAttribute("aria-current", "step");
    expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.slipped_p50));
    expect(screen.getByTestId("story-lock-shift")).toHaveTextContent(`${answer.slip_beyond_band_days} days beyond`);
    expect(screen.queryByTestId("story-comparison")).not.toBeInTheDocument();
    expect(screen.queryByTestId("story-verdict")).not.toBeInTheDocument();
    expect(screen.getByTestId("story-forecast-note")).toHaveTextContent("scenario assumptions");

    await user.click(screen.getByRole("button", { name: "Review interventions" }));
    expect(sequence[1]).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("button", { name: "Read follow-up evidence" })).toBeDisabled();
    for (const action of lockStory.actions) {
      const card = screen.getByTestId(`story-intervention-${action.id}`);
      expect(card).toHaveTextContent(`Owner: ${action.owner}`);
      await user.click(within(card).getByRole("button", { name: action.button_label }));
      expect(within(card).getByTestId("story-verdict")).toHaveAttribute("data-verdict", answer.early_verdict);
      expect(within(card).getByTestId("story-verdict")).toHaveTextContent(labels[answer.early_verdict]);
      expect(within(card).queryByRole("table")).not.toBeInTheDocument();
      expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.slipped_p50));
    }
    await user.click(screen.getByRole("button", { name: "Read follow-up evidence" }));
    expect(sequence[2]).toHaveAttribute("aria-current", "step");
    expect(screen.getByTestId("story-comparison")).toHaveClass("md:grid-cols-2");
    expect(screen.getAllByTestId("story-verdict")).toHaveLength(2);
    for (const id of answer.intervention_ids) {
      const expected = truth.interventions.find((iv) => iv.id === id)!;
      const card = screen.getByTestId(`story-intervention-${id}`);
      expect(within(card).getByTestId("story-verdict")).toHaveAttribute("data-verdict", expected.expected_verdict);
      expect(within(card).getByTestId("story-verdict")).toHaveTextContent(labels[expected.expected_verdict]);
      expect(within(card).getByRole("table")).toHaveTextContent("Matched controls");
      expect(card).toHaveTextContent("95% interval");
    }
    expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.recovered_p50));
    expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent("Back inside planned range");
    expect(screen.getByTestId("story-lock-shift")).toHaveTextContent(`${answer.recovery_days} days recovered`);
    expect(screen.getByTestId(`story-intervention-${answer.coincidence_intervention_id}`)).toHaveTextContent("northern winter ends");
    expect(screen.getByRole("button", { name: "Read follow-up evidence" })).toBeDisabled();
  });

  it("does not recover lock when only the coincidental SMS intervention is executed", async () => {
    const user = userEvent.setup();
    render(<LockRecoveryStory />);
    await user.click(screen.getByRole("button", { name: "Review interventions" }));
    await user.click(screen.getByRole("button", { name: "Run SMS programme" }));
    await user.click(screen.getByRole("button", { name: "Read follow-up evidence" }));
    const sms = screen.getByTestId(`story-intervention-${answer.coincidence_intervention_id}`);
    expect(sms).toHaveTextContent("Likely coincidence");
    expect(within(sms).getByRole("row", { name: "Treated 18.7% 8.4%" })).toBeInTheDocument();
    expect(within(sms).getByRole("row", { name: "Matched controls 19.4% 8.5%" })).toBeInTheDocument();
    expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.slipped_p50));
    expect(within(screen.getByTestId(`story-intervention-${answer.recovery_intervention_id}`)).queryByTestId("story-verdict")).not.toBeInTheDocument();

    // Starting the other action after a result still requires its own follow-up.
    await user.click(screen.getByRole("button", { name: "Run eCRF training" }));
    expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.slipped_p50));
    expect(screen.getByTestId(`story-intervention-${answer.recovery_intervention_id}`)).toHaveTextContent("Inconclusive");
    await user.click(screen.getByRole("button", { name: "Read follow-up evidence" }));
    expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.recovered_p50));
  });

  it("recovers with training alone after evidence, and resets without leaking judgments", async () => {
    const user = userEvent.setup();
    render(<LockRecoveryStory />);
    await user.click(screen.getByRole("button", { name: "Review interventions" }));
    await user.click(screen.getByRole("button", { name: "Run eCRF training" }));
    expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.slipped_p50));
    await user.click(screen.getByRole("button", { name: "Read follow-up evidence" }));
    expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.recovered_p50));
    await user.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.slipped_p50));
    expect(screen.queryByTestId("story-verdict")).not.toBeInTheDocument();
    expect(screen.queryByTestId("story-comparison")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review interventions" }));
    expect(screen.getByRole("button", { name: "Run eCRF training" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Read follow-up evidence" })).toBeDisabled();
  });

  it("keeps the answer key separate from measured effects and preserves the original 40-site cases", () => {
    expect(design.sites).toHaveLength(40);
    expect(lockEvidence.site_count).toBe(design.sites.length);
    expect(lockEvidence.simulated).toBe(true);
    expect(lockStory.simulated).toBe(true);
    expect(truth.simulated).toBe(true);
    expect(lockEvidence.data_label).toBe("Simulated feed");
    expect(lockStory.data_label).toBe("Simulated feed");
    expect(lockEvidence.seed).toBe(truth.seed);
    expect(lockEvidence.cases.map((c) => c.truth_id)).toEqual(answer.intervention_ids);
    expect(lockStory.plan).toEqual(answer.plan_band);
    expect(lockStory.recovery_intervention_id).toBe(answer.recovery_intervention_id);
    expect(daysBetween(lockStory.plan.p90, lockStory.slipped.p50)).toBe(answer.slip_beyond_band_days);
    expect(daysBetween(lockStory.recovered.p50, lockStory.slipped.p50)).toBe(answer.recovery_days);
    expect(lockStory.slipped.p10 > lockStory.plan.p90).toBe(true);
    expect(lockStory.recovered.p10 >= lockStory.plan.p10 && lockStory.recovered.p90 <= lockStory.plan.p90).toBe(true);

    for (const item of lockEvidence.cases) {
      const expected = truth.interventions.find((iv) => iv.id === item.truth_id)!;
      expect(item.intervention.target_site_ids).toEqual(expected.target_site_ids);
      expect(item.intervention.started_at?.slice(0, 10)).toBe(expected.start_date);
      expect(item.intervention.metric).toBe(expected.metric);
      expect(item.early.estimate.verdict).toBe(answer.early_verdict);
      expect(item.follow_up.estimate.verdict).toBe(expected.expected_verdict);
      const values = item.follow_up.values!;
      expect(values.treated_post!).toBeLessThan(values.treated_pre!);
      expect(values.did).toBeCloseTo((values.treated_post! - values.treated_pre!) - (values.control_post! - values.control_pre!), 8);
      expect(item.follow_up.control_units!.every((id) => !item.intervention.target_site_ids.includes(id))).toBe(true);
      if (expected.true_effect === "works") expect(item.follow_up.ci95![1]).toBeLessThan(0);
      else {
        expect(item.follow_up.ci95![0]).toBeLessThan(0);
        expect(item.follow_up.ci95![1]).toBeGreaterThan(0);
        expect(values.control_post!).toBeLessThan(values.control_pre!);
      }
    }
  });

  it("blocks out-of-order and duplicate actions without changing the lock forecast", () => {
    expect(replayReducer(initialReplay, { type: "start", id: "I1" })).toBe(initialReplay);
    expect(replayReducer(initialReplay, { type: "observe" })).toBe(initialReplay);
    const reviewed = replayReducer(initialReplay, { type: "review" });
    expect(replayReducer(reviewed, { type: "start", id: "unknown" })).toBe(reviewed);
    const started = replayReducer(reviewed, { type: "start", id: "I1" });
    expect(replayReducer(started, { type: "start", id: "I1" })).toBe(started);
    expect(replayForecast(started)).toBe(lockStory.slipped);
  });

  it("keeps an inconclusive follow-up inconclusive instead of substituting the expected success", async () => {
    const user = userEvent.setup();
    const training = lockEvidence.cases.find((item) => item.truth_id === answer.recovery_intervention_id)!;
    const original = training.follow_up;
    training.follow_up = training.early;
    try {
      render(<LockRecoveryStory />);
      await user.click(screen.getByRole("button", { name: "Review interventions" }));
      await user.click(screen.getByRole("button", { name: "Run eCRF training" }));
      await user.click(screen.getByRole("button", { name: "Read follow-up evidence" }));
      expect(screen.getByTestId("story-verdict")).toHaveTextContent("Inconclusive");
      expect(screen.getByTestId("story-lock-forecast")).toHaveTextContent(lockDate(answer.slipped_p50));
      expect(screen.queryByText(/clearing the bottleneck brings lock back/)).not.toBeInTheDocument();
      expect(screen.queryByText(/supports bringing lock back into range/)).not.toBeInTheDocument();
    } finally {
      training.follow_up = original;
    }
  });
});

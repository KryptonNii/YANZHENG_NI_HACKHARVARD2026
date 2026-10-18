import { expect, test } from "@playwright/test";
import truth from "../../../../data/fixtures/ops/ground_truth.json" with { type: "json" };

// Keep the existing sticky app navigation from covering offscreen portions of
// element screenshots; interactions above still use the unmodified page.
const screenshotStyle = "header.sticky { position: static !important; }";

test("plays the lock story and renders the two ground-truth judgments side by side", async ({ page }, info) => {
  await page.goto("/command/demo-40");
  await expect(page.getByTestId("simulated-badge")).toHaveText("Simulated");
  const story = page.getByTestId("lock-recovery-story");
  await expect(story).toHaveAttribute("data-simulated", "true");
  await expect(story.getByTestId("story-lock-shift")).toContainText("21 days beyond");
  await expect(story.getByTestId("story-comparison")).toHaveCount(0);
  await story.screenshot({ path: info.outputPath("01-lock-slip.png"), style: screenshotStyle });
  await story.getByRole("button", { name: "Review interventions" }).click();
  await expect(story.getByRole("button", { name: "Read follow-up evidence" })).toBeDisabled();
  await story.getByRole("button", { name: "Run eCRF training" }).click();
  await story.getByRole("button", { name: "Run SMS programme" }).click();
  await expect(story.getByTestId("story-verdict")).toHaveText(["Inconclusive", "Inconclusive"]);
  await story.getByRole("button", { name: "Read follow-up evidence" }).click();
  for (const id of truth.command_lock_recovery.intervention_ids) {
    const expected = truth.interventions.find((iv) => iv.id === id)!;
    await expect(story.getByTestId(`story-intervention-${id}`).getByTestId("story-verdict"))
      .toHaveAttribute("data-verdict", expected.expected_verdict);
  }
  await expect(story.getByTestId("story-lock-forecast")).toContainText("16 Nov 2028");
  await expect(story.getByTestId("story-lock-shift")).toContainText(`${truth.command_lock_recovery.recovery_days} days recovered`);
  const training = await story.getByTestId("story-intervention-I1").boundingBox();
  const sms = await story.getByTestId("story-intervention-I4").boundingBox();
  expect(training).not.toBeNull();
  expect(sms).not.toBeNull();
  expect(Math.abs(training!.y - sms!.y)).toBeLessThan(2);
  expect(sms!.x).toBeGreaterThan(training!.x);
  await story.screenshot({ path: info.outputPath("02-lock-recovered.png"), style: screenshotStyle });
});

test("keeps the SMS-only result delayed and the replay usable on a narrow screen", async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/command/demo-40");
  const story = page.getByTestId("lock-recovery-story");
  await story.getByRole("button", { name: "Review interventions" }).click();
  await story.getByRole("button", { name: "Run SMS programme" }).click();
  await story.getByRole("button", { name: "Read follow-up evidence" }).click();
  await expect(story.getByTestId("story-lock-forecast")).toContainText("14 Dec 2028");
  await expect(story.getByTestId("story-intervention-I4")).toContainText("Likely coincidence");
  expect(await story.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await story.screenshot({ path: info.outputPath("03-sms-only-mobile.png"), style: screenshotStyle });
  await story.getByRole("button", { name: "Reset" }).click();
  await expect(story.getByTestId("story-verdict")).toHaveCount(0);
  await expect(story.getByRole("button", { name: "Review interventions" })).toBeVisible();
});

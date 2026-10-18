import { expect, test } from "@playwright/test";
import type { Levers, TrialDesign } from "../src/app/contracts";
import type { ScenarioResultX } from "../src/app/api/types";
import { formatMonths } from "../src/app/format";

type Advice = {
  design_id: string;
  design_version: number;
  current_levers: Levers;
  seed: number;
  draws: number;
  scenario_draws: number;
  policy: { max_duration_increase_months: number; max_stockout_probability: number };
  recommendations: {
    id: string; kind: "lever" | "procedure_removal"; label: string; levers: Partial<Levers>;
    stockout_probability: number | null; procedure: { code: string } | null;
    delta: { cost_usd: { p50: number }; duration_months: { p50: number } };
  }[];
  rejected: { label: string; reason: string }[];
  stress_scenarios: { id: string; tag: string; levers: Partial<Levers> }[];
  blocked: { code: string }[];
};

test("cached BOREAS: reviewed evidence, constrained advice and current-scenario preview", async ({ page }, info) => {
  test.skip(process.env.E2E_MOCK === "1", "Requires the real API and cached registry study");
  test.setTimeout(180_000);
  await page.addInitScript(() => localStorage.setItem("tp.identity", "alex.author"));
  await page.goto("/");
  await expect(page.getByTestId("status-badges")).toContainText("Offline mode");
  await expect(page.getByTestId("status-badges")).not.toContainText("Mock API");
  const imported = page.waitForResponse((r) => r.url().endsWith("/api/import/ctgov/NCT03930732") && r.ok());
  await page.getByTestId("demo-chips").getByRole("button", { name: /NCT03930732/ }).click();
  expect((await (await imported).json()).raw_cached).toBe(true);
  await expect(page.getByTestId("trial-card")).toBeVisible();

  const unreviewedResponse = page.waitForResponse((r) => r.url().includes("/api/scenarios/advice?") && r.ok());
  await page.getByTestId("open-simulator").click();
  const unreviewed = await (await unreviewedResponse).json() as Advice;
  expect(unreviewed.recommendations).toEqual([]);
  expect(unreviewed.rejected.some((item) => /schedule/i.test(item.reason))).toBe(true);

  // Confirm the cached protocol through the existing review flow in this throwaway database.
  // This is automated demo review, not a human clinical approval.
  await page.goto("/");
  await page.getByTestId("demo-chips").getByRole("button", { name: /NCT03930732/ }).click();
  await page.getByTestId("extract-registry").click();
  const review = page.getByTestId("protocol-review");
  await expect(review).toBeVisible({ timeout: 60_000 });
  await review.getByRole("button", { name: "Accept remaining" }).click();
  await page.getByTestId("apply-extraction").click();
  await expect(review).toBeHidden({ timeout: 60_000 });
  const baselineResponse = page.waitForResponse((r) => r.url().endsWith("/api/scenarios/compute") && r.ok());
  const adviceResponse = page.waitForResponse((r) => r.url().includes("/api/scenarios/advice?") && r.ok());
  await page.getByTestId("open-simulator").click();
  const baseline = await (await baselineResponse).json() as ScenarioResultX;
  const response = await adviceResponse;
  const advice = await response.json() as Advice;
  const designId = decodeURIComponent(new URL(page.url()).pathname.split("/").pop()!);
  await expect(page.getByTestId("design-version")).toHaveText(`design v${advice.design_version}`);
  expect(advice.design_id).toBe(designId);
  expect(new URL(response.url()).searchParams.get("design_version")).toBe(String(advice.design_version));
  const designResponse = await page.request.get(`/api/designs/${designId}?version=${advice.design_version}`);
  expect(designResponse.ok()).toBe(true);
  const design = await designResponse.json() as TrialDesign;
  expect(design.registry_id).toBe("NCT03930732");

  const nextLever = page.getByRole("region", { name: "Optimization recommendations" });
  await expect(nextLever).toBeVisible();
  expect(await page.getByTestId("peer-mirror").evaluate((node) =>
    node.nextElementSibling?.querySelector("h2")?.textContent)).toBe("Optimization recommendations");
  const top = advice.recommendations[0];
  const blockedCodes = new Set(advice.blocked.map((item) => item.code));
  const rolesByCode = new Map<string, Set<string>>();
  for (const p of design.visits.flatMap((visit) => visit.procedures)) {
    rolesByCode.set(p.code, (rolesByCode.get(p.code) ?? new Set()).add(p.endpoint_role));
  }
  for (const item of advice.recommendations) {
    expect(item.delta.cost_usd.p50).toBeLessThan(0);
    expect(item.delta.duration_months.p50).toBeLessThanOrEqual(advice.policy.max_duration_increase_months);
    expect(item.stockout_probability).not.toBeNull();
    expect(item.stockout_probability!).toBeLessThanOrEqual(advice.policy.max_stockout_probability);
    expect(item.levers.enrollment_rate_multiplier).toBeUndefined();
    if (item.kind !== "procedure_removal") {
      expect(item.levers.removed_procedures).toBeUndefined();
      continue;
    }
    // A removal candidate adds exactly one code whose every occurrence is not_linked.
    const added = (item.levers.removed_procedures ?? [])
      .filter((code) => !advice.current_levers.removed_procedures.includes(code));
    expect(Object.keys(item.levers)).toEqual(["removed_procedures"]);
    expect(added).toHaveLength(1);
    expect(item.procedure?.code).toBe(added[0]);
    expect([...rolesByCode.get(added[0]) ?? []]).toEqual(["not_linked"]);
    expect(blockedCodes.has(added[0])).toBe(false);
  }
  // One ranking stage at 200 draws; the formal scenario keeps the server default (2,000).
  expect(advice.seed).toBe(7);
  expect(advice.draws).toBe(200);
  expect(advice.scenario_draws).toBe(2000);
  await expect(nextLever).toContainText("200");
  await expect(nextLever).toContainText(/2,?000/);
  // Slower enrollment is only an assumption stress scenario, never a recommendation.
  const recommendedIds = new Set(advice.recommendations.map((item) => item.id));
  for (const stress of advice.stress_scenarios) {
    expect(stress.tag).toBe("assumption");
    expect(recommendedIds.has(stress.id)).toBe(false);
  }
  if (advice.stress_scenarios.length) await expect(nextLever).toContainText("Stress test");
  if (top) await expect(nextLever.getByRole("list", { name: "Recommended levers" })
    .getByRole("listitem").first().getByRole("heading")).toHaveText(top.label);

  const lock = page.getByTestId("forecast-chart").locator("dl > div").filter({ hasText: "Database lock" }).locator("dd");
  const baselineLock = baseline.forecast!.milestone_dates.database_lock.p50!;
  await expect(lock).toContainText(formatMonths(baselineLock));
  const notes = page.getByTestId("assumption-notes");
  await notes.locator("summary").click();
  const missingNotes = await notes.getByRole("listitem").filter({ hasText: "planning value; source confirmation required" }).allTextContents();
  expect(missingNotes.length).toBeGreaterThan(0);

  const slowerResponse = page.waitForResponse((r) => r.url().endsWith("/api/scenarios/compute") && r.ok()
    && r.request().postDataJSON().levers.enrollment_rate_multiplier === 0.7);
  await page.getByTestId("lever-enrollment-rate").fill("70");
  const slower = await (await slowerResponse).json() as ScenarioResultX;
  const slowerLock = slower.forecast!.milestone_dates.database_lock.p50!;
  expect(slowerLock).toBeGreaterThan(baselineLock);
  await expect(lock).toContainText(formatMonths(slowerLock));
  await expect(page.getByTestId("lever-enrollment-rate")).toHaveValue("70");
  for (const note of missingNotes) await expect(notes).toContainText(note);
  await expect(nextLever.getByText("Calculating recommendations…", { exact: true })).toBeHidden();
  await info.attach("70-percent-enrollment", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });

  const countryResponse = page.waitForResponse((r) => r.url().endsWith("/api/scenarios/compute") && r.ok()
    && r.request().postDataJSON().levers.added_country_count === 1);
  const currentAdviceResponse = page.waitForResponse((r) => {
    if (!r.url().includes("/api/scenarios/advice?") || !r.ok()) return false;
    const current = JSON.parse(new URL(r.url()).searchParams.get("current_levers") ?? "{}");
    return current.added_country_count === 1 && current.enrollment_rate_multiplier === 0.7;
  });
  await page.getByTestId("lever-added-countries").fill("1");
  const country = await (await countryResponse).json() as ScenarioResultX;
  const warning = "Added countries are assumptions, not registry sites.";
  expect(country.warnings).toContain(warning);
  expect(country.warnings.some((text) => /Each added country assumes one site/.test(text))).toBe(true);
  await expect(notes.getByText(warning, { exact: true })).toBeVisible();
  for (const note of missingNotes) await expect(notes).toContainText(note);
  const currentAdvice = await (await currentAdviceResponse).json() as Advice;
  expect(currentAdvice.current_levers.added_country_count).toBe(1);
  expect(currentAdvice.current_levers.enrollment_rate_multiplier).toBe(0.7);
  await expect(nextLever.getByText("Calculating recommendations…", { exact: true })).toBeHidden();
  await info.attach("current-scenario-advice", { body: await nextLever.screenshot(), contentType: "image/png" });
  const currentTop = currentAdvice.recommendations[0];
  if (currentTop) {
    const computedPreview = page.waitForResponse((r) => r.url().endsWith("/api/scenarios/compute") && r.ok()
      && Object.entries(currentTop.levers).every(([key, value]) =>
        JSON.stringify(r.request().postDataJSON().levers[key]) === JSON.stringify(value)));
    await nextLever.getByRole("list", { name: "Recommended levers" }).getByRole("listitem").first()
      .getByRole("button", { name: "Preview" }).click();
    const preview = await (await computedPreview).json() as ScenarioResultX;
    expect(preview.levers.enrollment_rate_multiplier).toBe(0.7);
    if (!("added_country_count" in currentTop.levers)) expect(preview.levers.added_country_count).toBe(1);
  } else {
    // A real model may abstain; it must explain why rather than fabricate a top candidate.
    expect(currentAdvice.rejected.length).toBeGreaterThan(0);
    await expect(nextLever).toContainText(currentAdvice.rejected[0].reason);
  }
  await expect(nextLever.getByText("Calculating recommendations…", { exact: true })).toBeHidden();
  await info.attach("assumed-country-and-advice", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  const evidence = {
    registry_id: design.registry_id, design_id: designId, design_version: advice.design_version,
    baseline_database_lock_p50: baselineLock, enrollment_70_database_lock_p50: slowerLock,
    retained_assumption_notes: missingNotes, added_country_warning: warning,
    unreviewed_rejections: unreviewed.rejected,
    top_recommendation: top ?? null, current_top_recommendation: currentTop ?? null,
    current_levers: currentAdvice.current_levers, policy: currentAdvice.policy,
    rejected: currentAdvice.rejected, blocked_procedures: advice.blocked,
    stress_scenarios: currentAdvice.stress_scenarios,
  };
  console.log(JSON.stringify(evidence, null, 2));
  await info.attach("real-api-evidence", { body: JSON.stringify(evidence, null, 2), contentType: "application/json" });
});

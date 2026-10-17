/**
 * Command center against the real API (A6 simulated feed).
 * // @req URS-011 URS-012 URS-013
 */
import { expect, test } from "@playwright/test";

const MOCK = process.env.E2E_MOCK === "1";

test.describe("command center", () => {
  test.skip(MOCK, "The in-browser mock does not serve the operations feed");

  // @req URS-011 URS-012 URS-013
  test("runs weekly observations, alert to intervention, clock advance and effect against the real API", async ({ page }, info) => {
    test.setTimeout(240_000);
    await page.goto("/command/demo-40");
    await page.getByTestId("identity-switcher").selectOption("alex.author");
    await page.getByTestId("start-simulation").click();
    await expect(page.getByTestId("advance-1-week")).toBeEnabled({ timeout: 90_000 });
    await expect(page.getByTestId("simulated-badge")).toContainText("Simulated feed");
    const clock = page.getByTestId("sim-clock");
    const before = (await clock.textContent()) ?? "";
    await page.getByTestId("advance-1-week").click();
    await expect(clock).not.toHaveText(before, { timeout: 90_000 });
    await expect(page.getByTestId("alert-drug_overstock").first()).toBeVisible({ timeout: 90_000 });
    await expect(page.getByTestId("effect-verdict").first()).toBeVisible({ timeout: 90_000 });
    const healthResponse = await page.request.get("/api/ops/demo-40/health");
    expect(healthResponse.ok()).toBeTruthy();
    const health = await healthResponse.json();
    const site = health.sites.find((s: { site_id: string }) => s.site_id === "S14");
    const weekly = site.weekly_enrollment;
    expect(weekly.actual_cumulative.length).toBe(Math.floor(health.clock.clock_day / 7));
    await expect(page.getByTestId("site-S14").getByTestId("weekly-enrollment")).toHaveAccessibleName(new RegExp(`last cumulative ${weekly.actual_cumulative.at(-1)};`));
    await page.getByRole("tab", { name: /^countries$/i }).click();
    await expect(page.getByTestId("weekly-enrollment").first()).toBeVisible();
    await page.getByRole("tab", { name: /^sites$/i }).click();

    const alert = page.getByTestId("alert-drug_overstock").first();
    await alert.getByRole("button", { name: "Acknowledge", exact: true }).click();
    await expect(alert).toContainText("acknowledged");
    await alert.getByRole("button", { name: "Plan intervention", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toContainText("Owner alex.author");
    const createdResponse = page.waitForResponse((r) => r.url().endsWith("/interventions") && r.request().method() === "POST");
    await dialog.getByRole("button", { name: "Save intervention", exact: true }).click();
    const created = await (await createdResponse).json();
    const intervention = page.getByTestId(`intervention-${created.id}`);
    await expect(intervention).toContainText("planned");
    await intervention.getByRole("button", { name: "Start intervention", exact: true }).click();
    await expect(intervention).toContainText("in progress", { timeout: 90_000 });
    await expect(page.getByTestId("advance-1-week")).toBeEnabled();
    await page.getByRole("button", { name: "Advance 6 weeks", exact: true }).click();
    await expect(page.getByTestId("advance-1-week")).toBeEnabled({ timeout: 90_000 });
    await expect(intervention.getByTestId("effect-verdict")).toBeVisible();
    const effectResponse = await page.request.get(`/api/ops/demo-40/effects/${created.id}`);
    expect(effectResponse.ok()).toBeTruthy();
    const effect = await effectResponse.json();
    await expect(intervention).toContainText(effect.estimate.explanation);
    const auditResponse = await page.request.get("/api/audit?limit=1000");
    const audit = await auditResponse.json();
    expect(audit.items.some((e: { actor: string; action: string }) => e.actor === "alex.author" && e.action.includes("intervention"))).toBeTruthy();
    const completedResponse = await page.request.get("/api/ops/demo-40/health");
    const completed = await completedResponse.json();
    const partialResponse = await page.request.post("/api/ops/demo-40/clock", { headers: { "X-User": "alex.author", "X-Role": "author" }, data: { advance_days: 3 } });
    expect(partialResponse.ok()).toBeTruthy();
    const partial = await (await page.request.get("/api/ops/demo-40/health")).json();
    expect(partial.sites[0].weekly_enrollment.actual_cumulative).toEqual(completed.sites[0].weekly_enrollment.actual_cumulative);
    expect(partial.sites.some((s: { enrolled: number; weekly_enrollment: { actual_cumulative: number[] } }) => s.enrolled > s.weekly_enrollment.actual_cumulative.at(-1)!)).toBeTruthy();
    await page.reload();
    await expect(page.getByTestId("advance-1-week")).toBeEnabled({ timeout: 90_000 });
    await expect(page.getByTestId("drilldown")).toContainText("Current totals include the open week");
    const screenshot = info.outputPath("command-complete.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    await info.attach("command-complete", { path: screenshot, contentType: "image/png" });
  });
});

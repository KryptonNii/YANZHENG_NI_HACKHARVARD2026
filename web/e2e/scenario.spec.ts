/**
 * A8 end-to-end: import → levers → provenance → save → submit → self-approval blocked →
 * reviewer + QA sign → approved. Runs against the real API by default (see playwright.config.ts)
 * or the labelled mock API with E2E_MOCK=1. Requirement ids are A7's (validation/requirements.yaml).
 *
 * Screenshots: every test attaches them to its report; with E2E_SCREENSHOTS=1 they are also written
 * to e2e/scenario-screenshots/ (for the README/deck).
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

const MOCK = process.env.E2E_MOCK === "1";
// A7's demo PINs (api/trialpilot_api/compliance/roles.py; fictional users). The mock API uses the same.
const PIN = { "alex.author": "1111", "riley.reviewer": "2222", "sam.qa": "3333" } as const;

async function shot(page: Page, info: TestInfo, name: string) {
  const file = info.outputPath(`${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  await info.attach(name, { path: file, contentType: "image/png" });
  if (process.env.E2E_SCREENSHOTS === "1") {
    const dir = join(process.cwd(), "e2e", "scenario-screenshots");
    mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: join(dir, `${name}.png`), fullPage: true });
  }
}

async function actAs(page: Page, user: keyof typeof PIN) {
  await page.getByTestId("identity-switcher").selectOption(user);
}

/** Imports the first demo trial (A4's cached studies; the fictional study in mock mode). */
async function importDemoTrial(page: Page) {
  await page.goto("/");
  const chips = page.getByTestId("demo-chips");
  await expect(chips.getByRole("button").first()).toBeVisible();
  await chips.getByRole("button").first().click();
  await expect(page.getByTestId("trial-card")).toBeVisible();
}

async function waitForMetrics(page: Page) {
  await expect(page.getByTestId("metric-cost_usd-value")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("metric-cost_usd-delta")).toBeVisible({ timeout: 30_000 });
}

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try {
      localStorage.setItem("tp.identity", "alex.author");
    } catch {
      // ignore
    }
  });
});

// @req URS-001 URS-004 URS-006 URS-007 URS-010 URS-018 URS-019 URS-021 URS-022
test("hero flow: import, change levers, inspect provenance, save, submit, self-approval blocked, reviewer and QA approve", async ({ page }, info) => {
  await importDemoTrial(page);
  await expect(page.getByTestId("missing-assumed")).toContainText(/visits/i);
  await shot(page, info, "01-import");

  await page.getByTestId("open-simulator").click();
  await waitForMetrics(page);
  await expect(page.getByTestId("metric-cost_usd-delta")).toContainText("No change vs baseline");
  for (const key of ["cost_usd", "site_staff_hours", "patient_travel_hours", "duration_months", "co2e_kg"]) {
    await expect(page.getByTestId(`metric-${key}`)).toContainText("P10–P90");
  }
  await shot(page, info, "02-simulator-baseline");

  // §7 demo levers: 50 % remote monitoring, three visits at home, on-demand supply, drop one procedure
  await page.getByTestId("lever-remote-monitoring").fill("50");
  for (const n of [3, 4, 5]) {
    await page.getByRole("radiogroup", { name: new RegExp(`^Visit ${n} `) }).getByRole("radio", { name: "Home" }).click();
  }
  await page.getByRole("radio", { name: "On-demand resupply" }).click();
  await page.getByRole("group", { name: "Remove procedures" }).getByRole("checkbox").first().check();

  await expect(page.getByTestId("metric-cost_usd-delta")).not.toContainText("No change vs baseline", { timeout: 30_000 });
  await expect(page.getByTestId("metric-patient_travel_hours-delta")).toContainText(/lower than baseline/, { timeout: 30_000 });
  await expect(page.getByText("recomputing…")).toHaveCount(0, { timeout: 30_000 });
  await shot(page, info, "03-simulator-levers");

  // provenance drawer: formula, inputs, parameters with sources or assumption tags
  await page.getByTestId("metric-co2e_kg-value").click();
  const drawer = page.getByTestId("provenance-drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer.getByTestId("provenance-formula").first()).toBeVisible();
  await expect(drawer.getByTestId("provenance-param").first()).toBeVisible({ timeout: 20_000 });
  await expect(drawer.getByTestId("provenance-drivers")).toBeVisible({ timeout: 30_000 });
  await shot(page, info, "04-provenance-drawer");
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  // save → submit
  const name = `E2E scenario B ${Date.now()}`;
  await page.getByTestId("save-scenario").click();
  await page.getByTestId("save-name").fill(name);
  await page.getByTestId("save-confirm").click();
  await expect(page.getByTestId("versions-table")).toContainText(name, { timeout: 30_000 });
  await page.getByTestId("submit-approval").click();
  const panel = page.getByTestId("approval-panel");
  await expect(panel).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId("approval-status")).toContainText("Pending");

  // the author tries to sign their own scenario → blocked with a plain message
  await page.getByTestId("sign-pin").fill(PIN["alex.author"]);
  await page.getByTestId("sign-button").click();
  await expect(page.getByTestId("sign-error")).toContainText("Authors can't approve their own work.");
  await shot(page, info, "05-self-approval-blocked");

  // reviewer signs "reviewed"
  await actAs(page, "riley.reviewer");
  await page.getByTestId("sign-pin").fill(PIN["riley.reviewer"]);
  await page.getByTestId("sign-button").click();
  await expect(page.getByTestId("signature-list")).toContainText(/reviewed by Riley/i);

  // QA signs "approved"
  await actAs(page, "sam.qa");
  await page.getByTestId("sign-pin").fill(PIN["sam.qa"]);
  await page.getByTestId("sign-button").click();
  await expect(page.getByTestId("approval-status")).toContainText("Approved");
  await expect(page.getByTestId("signature-list")).toContainText(/approved by Sam/i);
  await expect(page.getByTestId("signature-list")).toContainText("UTC");
  await shot(page, info, "06-approved");
});

// @req URS-002
test("protocol extraction: candidates show page and quote, nothing applies until a person accepts rows", async ({ page }, info) => {
  await importDemoTrial(page);
  const registry = page.getByTestId("extract-registry");
  test.skip((await registry.count()) === 0, "the first demo trial has no registry protocol");
  await registry.click();
  const review = page.getByTestId("protocol-review");
  await expect(review).toBeVisible({ timeout: 60_000 });
  await expect(review).toContainText("AI draft");
  await expect(review.getByText(/p\. \d+/).first()).toBeVisible();
  await expect(page.getByTestId("apply-extraction")).toBeDisabled();
  await shot(page, info, "07-protocol-review");

  await review.getByRole("button", { name: "Accept all remaining" }).click();
  await expect(page.getByTestId("apply-extraction")).toBeEnabled();
  await page.getByTestId("apply-extraction").click();
  await expect(page.getByTestId("protocol-review")).toBeHidden({ timeout: 30_000 });
  await expect(page.getByTestId("missing-assumed")).not.toContainText(/^.*assumed\s*Visits/i);
});

// @req URS-001
test("import validates the ClinicalTrials.gov id before calling the API", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("nct-input").fill("NCT123");
  await page.getByTestId("nct-submit").click();
  await expect(page.getByRole("alert")).toContainText("8 digits");
  await expect(page.getByTestId("trial-card")).toHaveCount(0);
});

// @req URS-029
test("offline mode is visible in the header", async ({ page }) => {
  test.skip(MOCK, "the mock API does not run in offline mode");
  await page.goto("/");
  await expect(page.getByTestId("status-badges")).toContainText("Offline mode");
});

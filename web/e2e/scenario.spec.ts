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

/** Imports BOREAS (cached protocol extraction). Mock mode uses its fictional chip. */
async function importDemoTrial(page: Page) {
  await page.goto("/");
  const chips = page.getByTestId("demo-chips");
  const button = MOCK ? chips.getByRole("button").first() : chips.getByRole("button", { name: /NCT03930732/ });
  await expect(button).toBeVisible();
  await button.click();
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
  test.setTimeout(180_000);
  await importDemoTrial(page);
  const missing = page.getByTestId("missing-assumed");
  // Specs share one database. An earlier file may already have applied the cached protocol,
  // which removes the visit-schedule assumption this flow has to show.
  if (!(await missing.textContent())?.match(/visits/i)) {
    await page.getByTestId("reimport-registry").click();
  }
  await expect(missing).toContainText(/visits/i);
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
  await expect(page.getByTestId("metric-patient_travel_hours-delta")).toContainText(/\blower\b/, { timeout: 30_000 });
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
  test.setTimeout(180_000);
  await importDemoTrial(page);
  const registry = page.getByTestId("extract-registry");
  test.skip(MOCK, "The fictional mock has no registry protocol PDF");
  await expect(registry).toBeVisible();
  const list = page.getByTestId("missing-assumed");
  // Repeated runs may already have a confirmed schedule. Reset it only through the explicit action.
  if (!(await list.textContent())?.match(/Visit schedule is NOT/i)) {
    await page.getByTestId("reimport-registry").click();
  }
  await expect(list).toContainText(/Visit schedule is NOT/i);
  await expect(list).toContainText(/actual number enrolled/i);
  await expect(page.getByTestId("missing-count")).toHaveText(String(await list.locator("span", { hasText: /^to confirm$/i }).count()));

  await registry.click();
  const review = page.getByTestId("protocol-review");
  await expect(review).toBeVisible({ timeout: 60_000 });
  await expect(review).toContainText("Pending review");
  await expect(review.getByText(/p\. \d+/).first()).toBeVisible();
  await expect(page.getByTestId("apply-extraction")).toBeDisabled();
  await shot(page, info, "07-protocol-review");

  await review.getByRole("button", { name: /Edit visit/ }).first().click();
  await review.locator("input[aria-label$='week']").first().fill("");
  await expect(review.getByRole("button", { name: "Done" })).toBeDisabled();
  await expect(review).toContainText("Enter a valid week.");
  await shot(page, info, "11-protocol-empty-week");

  const logged = page.waitForRequest((req) => req.method() === "POST" && req.url().includes("/api/import/protocol/review"));
  await review.getByRole("button", { name: "Accept remaining" }).click();
  await expect(page.getByTestId("apply-extraction")).toBeEnabled();
  await page.getByTestId("apply-extraction").click();
  const body = (await logged).postDataJSON() as { bulk_accepted?: number };
  expect(body.bulk_accepted ?? 0).toBeGreaterThan(0);
  await expect(page.getByTestId("protocol-review")).toBeHidden({ timeout: 60_000 });
  await expect(list).not.toContainText(/Visit schedule is NOT/i);
  await expect(list).toContainText(/actual number enrolled/i);
  await expect(page.getByTestId("missing-count")).toHaveText(String(await list.locator("span", { hasText: /^to confirm$/i }).count()));
  await shot(page, info, "12-protocol-applied");
  const version = await page.getByTestId("import-design-version").innerText();
  const stored = await page.request.get(`/api/designs/${new URL(page.url()).searchParams.get("design")}`);
  expect(stored.ok()).toBeTruthy();
  const schedule = (await stored.json()).visits;
  await page.getByTestId("nct-input").fill("NCT03930732");
  await page.getByTestId("nct-submit").click();
  await expect(page.getByTestId("stored-design-banner")).toBeVisible();
  await expect(page.getByTestId("import-design-version")).toHaveText(version);
  const after = await page.request.get(`/api/designs/${new URL(page.url()).searchParams.get("design")}`);
  expect((await after.json()).visits).toEqual(schedule);
  await expect(page.getByTestId("missing-assumed")).not.toContainText(/Visit schedule is NOT/i);
});

// @req URS-001 URS-029
test("demo chips recover when the API becomes reachable", async ({ page }) => {
  test.skip(MOCK, "Transport recovery exercises the real API");
  await page.clock.install();
  await page.route("**/api/health", (route) => route.abort("connectionrefused"));
  await page.goto("/");
  await expect(page.getByTestId("status-badges")).toContainText("Connection unavailable");
  await expect(page.getByTestId("demo-chips")).toHaveCount(0);
  await page.unroute("**/api/health");
  await page.clock.fastForward(31_000);
  await expect(page.getByTestId("demo-chips").getByRole("button", { name: /NCT03930732/ })).toBeVisible();
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
  await expect(page.getByTestId("status-badges")).toContainText("Offline");
});

async function importNct(page: Page, nct: string) {
  await page.goto("/");
  await page.getByTestId("nct-input").fill(nct);
  await page.getByTestId("nct-submit").click();
  await expect(page.getByTestId("trial-card")).toBeVisible({ timeout: 60_000 });
}

/** Stores a new design version from the page, the way a second editor would. */
async function storeNextDesignVersion(page: Page, designId: string, enrollment: number) {
  const status = await page.evaluate(
    async ({ designId, enrollment }) => {
      const headers = { Accept: "application/json", "X-User": "alex.author", "X-Role": "author" };
      const current = await fetch(`/api/designs/${encodeURIComponent(designId)}`, { headers });
      const design = (await current.json()) as { enrollment_target: number };
      if (!current.ok) return current.status;
      const etag = current.headers.get("ETag");
      const saved = await fetch("/api/designs", {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json", ...(etag ? { "If-Match": etag } : {}) },
        body: JSON.stringify({ ...design, enrollment_target: enrollment }),
      });
      return saved.status;
    },
    { designId, enrollment },
  );
  expect(status === 200 || status === 201).toBe(true);
}

// @req URS-001 URS-004
test("an unseeded trial is saved before the simulator opens, and later edits stay on that version", async ({ page }, info) => {
  test.setTimeout(180_000);
  await importNct(page, "NCT04456673");
  await expect(page.getByText(/was not found/i)).toHaveCount(0);
  await expect(page.getByTestId("import-design-version")).toContainText(/design v\d+/);
  await shot(page, info, "08-unseeded-import");

  await page.getByTestId("open-simulator").click();
  await waitForMetrics(page);
  const versionText = await page.getByTestId("design-version").innerText();
  const version = Number(versionText.replace(/\D/g, ""));
  expect(version).toBeGreaterThan(0);
  const designId = decodeURIComponent(new URL(page.url()).pathname.split("/").pop() ?? "");
  expect(designId.length).toBeGreaterThan(0);

  const latest = await page.request.get(`/api/designs/${designId}`);
  const previousEnrollment = (await latest.json()).enrollment_target;
  await storeNextDesignVersion(page, designId, previousEnrollment === 100 ? 101 : 100);
  const changed = await page.request.get(`/api/designs/${designId}`);
  const nextVersion = Number(changed.headers()["x-design-version"]);
  expect(nextVersion).toBeGreaterThan(version);
  await expect(page.getByTestId("design-version")).toHaveText(versionText);

  const computes: number[] = [];
  page.on("request", (req) => {
    if (req.method() !== "POST" || !req.url().includes("/api/scenarios/compute")) return;
    const body = req.postDataJSON() as { design_version?: number };
    if (typeof body.design_version === "number") computes.push(body.design_version);
  });
  const calculated = page.waitForResponse((res) => res.url().endsWith("/api/scenarios/compute") && res.request().postDataJSON().levers.drug_supply_strategy === "on_demand");
  await page.getByRole("radio", { name: "On-demand resupply" }).click();
  const calculatedResult = await (await calculated).json();
  await expect.poll(() => computes.at(-1), { timeout: 60_000 }).toBe(version);
  await expect(page.getByText("recomputing…")).toHaveCount(0, { timeout: 60_000 });
  await expect(page.getByTestId("design-version")).toHaveText(versionText);

  const cost = (await page.getByTestId("metric-cost_usd-value").innerText()).split("\n")[0].trim();
  const name = `Pinned v${version} ${Date.now()}`;
  await page.getByTestId("save-scenario").click();
  await page.getByTestId("save-name").fill(name);
  const stored = page.waitForResponse((res) => res.url().endsWith("/api/scenarios") && res.request().method() === "POST");
  await page.getByTestId("save-confirm").click();
  const saved = await (await stored).json();
  expect(saved.design_version).toBe(version);
  for (const key of ["cost_usd", "co2e_kg", "duration_months", "site_staff_hours", "patient_travel_hours", "drug_waste_share", "forecast", "supply"]) {
    expect(saved.result[key], `saved ${key} matches the exact computed response`).toEqual(calculatedResult[key]);
  }
  const table = page.getByTestId("versions-table");
  await expect(table).toContainText(name, { timeout: 60_000 });
  await expect(table).toContainText(`design v${version}`);
  await expect(table).toContainText(cost);
  await shot(page, info, "09-version-pinned");
  const headers = { "X-User": "alex.author", "X-Role": "author" };
  const reference = await page.request.post("/api/scenarios", { headers, data: { design_id: designId, design_version: version, name: "Pinned reference", levers: {} } });
  expect(reference.ok(), await reference.text()).toBeTruthy();
  const referenceId = (await reference.json()).id;
  await page.goto(`/compare?a=${referenceId}&b=${saved.id}`);
  await expect(page.getByTestId("compare-table")).toBeVisible();
  await expect(page.getByTestId("compare-table")).toContainText("P10–P90 of the difference");
  await shot(page, info, "14-compare-pinned");
  const later = await page.request.post("/api/scenarios", { headers, data: { design_id: designId, design_version: nextVersion, name: "Later design", levers: {} } });
  expect(later.ok(), await later.text()).toBeTruthy();
  await page.goto(`/compare?a=${referenceId}&b=${(await later.json()).id}`);
  await expect(page.getByText(/Different design versions.*P50 comparison only/)).toBeVisible();
  await expect(page.getByTestId("compare-table")).not.toContainText("P10–P90 of the difference");
});

// @req URS-001
test("editing trial facts reports a conflict after someone else stores a version", async ({ page }, info) => {
  test.skip(MOCK, "the conflict copy is the fictional mock trial; the real registry copy is the regression");
  await importNct(page, "NCT04535986");
  const card = page.getByTestId("trial-card");
  const shown = Number(((await card.innerText()).match(/enrollment\s*([\d,]+)\s*patients/i)?.[1] ?? "").replace(/,/g, ""));
  expect(shown).toBeGreaterThan(0);
  const designId = new URL(page.url()).searchParams.get("design");
  if (!designId) throw new Error("Import did not set the design URL");
  const next = shown === 222 ? 333 : 222;
  await storeNextDesignVersion(page, designId, next);

  await page.getByRole("button", { name: "Edit facts" }).click();
  await page.getByLabel("Duration (months)").fill("12");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByTestId("design-conflict")).toContainText(/design v/i);
  await expect(card).toContainText(`${shown.toLocaleString("en-US")} patients`);
  await expect(card).not.toContainText(`${next.toLocaleString("en-US")} patients`);
  await shot(page, info, "10-design-conflict");
});

// @req URS-010
test("science band prints the results-file unit, including t_co2e", async ({ page }, info) => {
  test.skip(MOCK, "the mock API does not serve science/out/results.json");
  await page.goto("/science");
  await expect(page.getByTestId("science-band-unit")).toContainText("t_co2e", { timeout: 30_000 });
  await expect(page.getByTestId("science-band-unit")).toContainText("Displayed unit: t");
  await expect(page.getByTestId("science-band-unit")).not.toContainText("kg_co2e");
  await shot(page, info, "13-science-t-co2e");
});

/**
 * Audit chain verification against the real API.
 * // @req URS-017
 */
import { expect, test } from "@playwright/test";

const MOCK = process.env.E2E_MOCK === "1";

test.describe("audit", () => {
  test.skip(MOCK, "Chain verification needs the compliance API");

  test("verify chain shows intact", async ({ page }) => {
    const started = await page.request.post("/api/ops/demo-40/simulate", {
      data: { seed: 42, speed: 0, scenario: "demo" },
      headers: { "X-User": "alex.author", "X-Role": "author", "Content-Type": "application/json" },
    });
    expect(started.ok(), await started.text()).toBeTruthy();

    await page.goto("/audit");
    await page.getByRole("button", { name: "Verify chain" }).click();
    await expect(page.getByTestId("chain-result")).toContainText(/Chain intact — \d+ entries/);
  });
});

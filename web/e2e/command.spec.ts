/**
 * Command center against the real API (A6 simulated feed).
 * // @req URS-011 URS-012 URS-013
 */
import { expect, test } from "@playwright/test";

const MOCK = process.env.E2E_MOCK === "1";

test.describe("command center", () => {
  test.skip(MOCK, "The in-browser mock does not serve the operations feed");

  test("shows a planted overstock alert after advancing time, then an effect verdict", async ({ page }) => {
    test.setTimeout(180_000);
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
  });
});

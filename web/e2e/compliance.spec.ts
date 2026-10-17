/**
 * Audit chain verification against the real API.
 * // @req URS-017
 */
import { expect, test } from "@playwright/test";
import { cpSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { isAbsolute, join, relative, resolve } from "node:path";
import { tmpdir } from "node:os";

const MOCK = process.env.E2E_MOCK === "1";

test.describe("audit", () => {
  test.skip(MOCK, "Chain verification needs the compliance API");

  // @req URS-017 URS-028
  test("verify chain shows intact", async ({ page }, info) => {
    const started = await page.request.post("/api/ops/demo-40/simulate", {
      data: { seed: 42, speed: 0, scenario: "demo" },
      headers: { "X-User": "alex.author", "X-Role": "author", "Content-Type": "application/json" },
    });
    expect(started.ok(), await started.text()).toBeTruthy();

    await page.goto("/audit");
    await page.getByRole("button", { name: "Verify chain" }).click();
    await expect(page.getByTestId("chain-result")).toContainText(/Chain intact — \d+ entries/);
    const exportEvent = page.waitForEvent("download");
    await page.getByRole("link", { name: "Export CSV", exact: true }).click();
    const csv = await exportEvent;
    expect(readFileSync((await csv.path())!, "utf8")).toContain("ops.simulate");
    const screenshot = info.outputPath("audit-intact.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    await info.attach("audit-intact", { path: screenshot, contentType: "image/png" });
  });

  // @req URS-018 URS-019 URS-021 URS-022 URS-023
  test("shared identities enforce self-approval, signing order and complete manifestations", async ({ page }, info) => {
    const headers = { "X-User": "alex.author", "X-Role": "author" };
    const imported = await page.request.post("/api/import/ctgov/NCT03930732", { headers });
    expect(imported.ok(), await imported.text()).toBeTruthy();
    const importedDesign = (await imported.json()).design;
    const existing = await page.request.get(`/api/designs/${importedDesign.id}`);
    if (existing.status() === 404) {
      const stored = await page.request.post("/api/designs", { headers, data: importedDesign });
      expect(stored.ok(), await stored.text()).toBeTruthy();
    } else expect(existing.ok()).toBeTruthy();
    const designsResponse = await page.request.get("/api/designs");
    expect(designsResponse.ok()).toBeTruthy();
    const designBody = await designsResponse.json();
    const designs = Array.isArray(designBody) ? designBody : designBody.items;
    expect(designs.length).toBeGreaterThan(0);
    const saved = await page.request.post("/api/scenarios", { headers, data: { design_id: designs[0].id, design_version: designs[0].version, name: `A9 approval ${Date.now()}`, levers: {} } });
    expect(saved.ok(), await saved.text()).toBeTruthy();
    const scenario = await saved.json();
    const submitted = await page.request.post(`/api/scenarios/${scenario.id}/submit`, { headers });
    expect(submitted.ok(), await submitted.text()).toBeTruthy();
    const id = (await submitted.json()).approval_id;
    const wrongOrder = await page.request.post(`/api/approvals/${id}/sign`, { headers: { "X-User": "sam.qa" }, data: { meaning: "approved", pin: "3333" } });
    expect(wrongOrder.status()).toBe(409);
    expect((await wrongOrder.json()).error).toBe("out_of_order");

    await page.goto("/approvals");
    await page.getByTestId("identity-switcher").selectOption("alex.author");
    const card = page.getByTestId(`approval-${id}`);
    await card.getByRole("button", { name: "Sign this record" }).click();
    let dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("button", { name: "Sign", exact: true })).toBeDisabled();
    await expect(dialog).toContainText(scenario.record_hash);
    await dialog.getByLabel("PIN", { exact: true }).fill("1111");
    const denied = page.waitForResponse((r) => r.url().endsWith(`/approvals/${id}/sign`));
    await dialog.getByRole("button", { name: "Sign", exact: true }).click();
    expect((await denied).status()).toBe(403);
    await expect(page.getByTestId("sign-error")).toContainText("Authors can't approve their own work.");
    await dialog.getByRole("button", { name: "Cancel" }).click();

    for (const [user, pin, meaning] of [["riley.reviewer", "2222", "reviewed"], ["sam.qa", "3333", "approved"]]) {
      await page.getByTestId("identity-switcher").selectOption(user);
      await expect(page.getByTestId("approvals-page")).toContainText(user === "sam.qa" ? "Signing as Sam" : "Signing as Riley");
      await card.getByRole("button", { name: "Sign this record" }).click();
      dialog = page.getByRole("dialog");
      await expect(dialog.getByLabel("Meaning", { exact: true })).toHaveValue(meaning);
      await dialog.getByLabel("PIN", { exact: true }).fill(pin);
      const signed = page.waitForResponse((r) => r.url().endsWith(`/approvals/${id}/sign`) && r.request().method() === "POST");
      await dialog.getByRole("button", { name: "Sign", exact: true }).click();
      expect((await signed).ok()).toBeTruthy();
      await expect(dialog).toBeHidden();
    }
    await page.getByRole("tab", { name: /^approved$/i }).click();
    await expect(card).toContainText("Riley Reviewer");
    await expect(card).toContainText("Sam QA");
    await expect(card).toContainText("UTC");
    await expect(card).toContainText(scenario.record_hash);
    const final = await (await page.request.get(`/api/approvals/${id}`)).json();
    expect(final.status).toBe("approved");
    expect(final.signatures.map((s: { meaning: string }) => s.meaning)).toEqual(["reviewed", "approved"]);
    for (const signature of final.signatures) {
      expect(signature).toMatchObject({ record_hash: scenario.record_hash, valid: true });
      for (const key of ["signer", "signer_name", "role", "meaning", "signed_at", "record_type", "record_id", "manifestation"]) expect(signature[key]).toBeTruthy();
    }
    const screenshot = info.outputPath("approvals-complete.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    await info.attach("approvals-complete", { path: screenshot, contentType: "image/png" });
  });

  // @req URS-025 URS-026 URS-027 URS-028 URS-032
  test("validation keeps package_not_built honest and downloads a real package when configured", async ({ page }, info) => {
    // For A9's full regression, reuse fresh servers with TP_VALIDATION_OUT=A9_VALIDATION_OUT.
    // The fixture is A7's unchanged measured package, copied only into a throwaway directory.
    const out = process.env.A9_VALIDATION_OUT;
    const source = process.env.A9_VALIDATION_SOURCE;
    await page.goto("/validation");
    const initial = await page.request.get("/api/validation/package");
    if (initial.status() === 404) {
      expect((await initial.json()).error).toBe("package_not_built");
      await expect(page.getByText("No validation package yet", { exact: true })).toBeVisible();
      await expect(page.getByTestId("draft-stamp")).toHaveCount(0);
    }
    if (out && source) {
      const target = resolve(out);
      const withinTemp = relative(resolve(tmpdir()), target);
      expect(withinTemp && !withinTemp.startsWith("..") && !isAbsolute(withinTemp), "A9 fixture output must be a subdirectory of the OS temp directory").toBeTruthy();
      expect(existsSync(join(source, "package_index.json"))).toBeTruthy();
      mkdirSync(target, { recursive: true });
      cpSync(source, join(target, "package"), { recursive: true });
      await page.getByRole("button", { name: "Refresh package" }).click();
    } else if (initial.status() === 404) {
      return; // Standard clean API run: no package exists; no fabricated fixture is displayed.
    }
    const response = await page.request.get("/api/validation/package");
    expect(response.ok()).toBeTruthy();
    const pkg = await response.json();
    await expect(page.getByTestId("draft-stamp")).toContainText("DRAFT");
    await expect(page.getByText("awaiting QA approval", { exact: true })).toBeVisible();
    await expect(page.getByTestId("execution-summary")).toContainText(`failed ${pkg.execution.counts.failed}`);
    for (const id of pkg.trace.flags.untested_requirements) await expect(page.getByTestId("untested-requirements")).toContainText(id);
    for (const id of pkg.trace.flags.failing_requirements) await expect(page.getByTestId(`trace-${id}`)).toContainText("fail");
    const md = page.getByRole("link", { name: "Download Validation plan Markdown", exact: true });
    const downloadEvent = page.waitForEvent("download");
    await md.click();
    const download = await downloadEvent;
    const downloadPath = await download.path();
    expect(downloadPath).toBeTruthy();
    const expectedMd = pkg.deliverables.find((d: { id: string }) => d.id === "D1");
    expect(createHash("sha256").update(readFileSync(downloadPath!)).digest("hex")).toBe(expectedMd.sha256);
    const manifestResponse = await page.request.get(`/api/validation/package/files/${pkg.execution.evidence_dir}/evidence_manifest.json`);
    expect(manifestResponse.ok()).toBeTruthy();
    const manifest = await manifestResponse.json();
    const attachments = page.getByTestId("evidence-attachments");
    await expect(attachments).toContainText(`(${manifest.files.length})`);
    await attachments.locator("summary").click();
    for (const suffix of [".png", ".zip"]) {
      const file = manifest.files.find((f: { path: string }) => f.path.endsWith(suffix));
      expect(file, `A7 package must include ${suffix} evidence`).toBeTruthy();
      const event = page.waitForEvent("download");
      await attachments.getByRole("link", { name: file.path, exact: true }).click();
      const artifact = await event;
      const path = await artifact.path();
      expect(createHash("sha256").update(readFileSync(path!)).digest("hex")).toBe(file.sha256);
    }
    const screenshot = info.outputPath("validation-package.png");
    await page.screenshot({ path: screenshot, fullPage: true });
    await info.attach("validation-package", { path: screenshot, contentType: "image/png" });
  });
});

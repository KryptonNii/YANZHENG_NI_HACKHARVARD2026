import { fileURLToPath } from "node:url";
import { defineConfig } from "@playwright/test";
import base from "../../../playwright.config";

// Keep story coverage in the command feature; reuse the real API/server setup.
const cwd = fileURLToPath(new URL("../../../", import.meta.url));
const servers = Array.isArray(base.webServer) ? base.webServer : base.webServer ? [base.webServer] : [];

export default defineConfig({
  ...base,
  testDir: ".",
  testMatch: "lockStory.browser.spec.ts",
  outputDir: "./test-results/lock-story",
  webServer: servers.map((server) => ({ ...server, cwd })),
});

import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests. Two modes:
 *  - default: the real FastAPI app (A5, with A2/A3/A4/A7 mounted) on a throwaway SQLite file in
 *    offline mode (DEMO_OFFLINE=1, cached fixtures) + the Vite dev server proxied to it;
 *  - E2E_MOCK=1: Vite only, with the in-browser mock API (fictional data, "Mock API" badge).
 * Specs carry `// @req URS-xxx` tags; `tpv execute --e2e` (A7) runs them as validation evidence.
 * Ports default to A8's test ports (web 5181, API 8008); override with E2E_WEB_PORT / E2E_API_PORT.
 * Browser: on Windows the installed Microsoft Edge (no download); elsewhere Playwright's Chromium
 * (`pnpm exec playwright install chromium`). Override with PW_CHANNEL (e.g. "chrome").
 */
const MOCK = process.env.E2E_MOCK === "1";
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5181);
const API_PORT = Number(process.env.E2E_API_PORT ?? 8008);
const CI = !!process.env.CI;
const channel = process.env.PW_CHANNEL ?? (process.platform === "win32" ? "msedge" : undefined);
const runDir = mkdtempSync(join(tmpdir(), "tp-e2e-"));

const web = {
  command: `pnpm exec vite --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
  url: `http://127.0.0.1:${WEB_PORT}`,
  reuseExistingServer: !CI,
  timeout: 60_000,
  env: {
    WEB_PORT: String(WEB_PORT),
    API_TARGET: `http://127.0.0.1:${API_PORT}`,
    ...(MOCK ? { VITE_MOCK_API: "1" } : {}),
  },
};

const apiServer = {
  command: `uv run --project ../api uvicorn trialpilot_api.main:app --host 127.0.0.1 --port ${API_PORT}`,
  url: `http://127.0.0.1:${API_PORT}/api/health`,
  reuseExistingServer: !CI,
  timeout: 120_000,
  env: {
    DEMO_OFFLINE: "1",
    TP_DB_PATH: join(runDir, "e2e.sqlite"),
    TP_VALIDATION_OUT: join(runDir, "validation-out"),
    TP_LOG_JSON: "0",
  },
};

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: CI ? 1 : 0,
  reporter: CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: MOCK ? "mock-api" : "real-api", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 }, channel } }],
  webServer: MOCK ? [web] : [apiServer, web],
});

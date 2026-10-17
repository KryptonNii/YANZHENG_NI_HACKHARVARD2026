/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server on 5173 with `/api` proxied to FastAPI on 8000 (§3). Agents testing in
// parallel override both: WEB_PORT=5181 API_TARGET=http://localhost:8008 pnpm dev.
// `vite --mode mock` (VITE_MOCK_API=1 in .env.mock) swaps the network for the in-browser
// mock backend in src/app/api/mock — every page then shows a "Mock API" badge.
const webPort = Number(process.env.WEB_PORT ?? 5173);
const apiTarget = process.env.API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: webPort,
    strictPort: true,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
  preview: {
    port: webPort,
    strictPort: true,
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
  build: { sourcemap: true, chunkSizeWarningLimit: 1200 },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/app/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});

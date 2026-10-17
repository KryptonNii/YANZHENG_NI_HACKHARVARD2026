import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "./app/styles.css";
import App from "./app/App";

async function start() {
  // Mock backend only when explicitly requested (pnpm dev:mock / E2E_MOCK=1). The header then
  // shows a "Mock API — fictional data" badge on every page.
  if (import.meta.env.VITE_MOCK_API === "1") {
    const { installMockApi } = await import("./app/api/mock");
    installMockApi();
  }
  const root = document.getElementById("root");
  if (!root) throw new Error("TrialPilot root element is missing");
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();

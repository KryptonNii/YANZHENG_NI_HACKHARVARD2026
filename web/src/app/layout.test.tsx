import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, beforeEach, expect, it } from "vitest";
import { AppRoutes } from "./App";
import { installMockApi, resetMockStore } from "./api/mock";
import { setLanguage } from "./i18n";
import { setLastDesignId } from "./lastDesign";
import { ToastProvider } from "./toast";

beforeAll(() => installMockApi());
beforeEach(() => {
  resetMockStore();
  localStorage.clear();
  setLanguage("en");
});

function commandHref(): string | null {
  render(<ToastProvider><MemoryRouter initialEntries={["/"]}><AppRoutes /></MemoryRouter></ToastProvider>);
  return screen.getByRole("link", { name: "Command center" }).getAttribute("href");
}

it("links the command center to the 40-site demo trial when no design was opened yet", () => {
  // "/command/demo" has no stored design, so its "Start simulation" fails with design_not_found.
  expect(commandHref()).toBe("/command/demo-40");
});

it("links the command center to the last opened design", () => {
  setLastDesignId("nct03930732");
  expect(commandHref()).toBe("/command/nct03930732");
});

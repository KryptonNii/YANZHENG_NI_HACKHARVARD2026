import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import { AppRoutes } from "./App";
import { api } from "./api/client";
import { installMockApi, resetMockStore } from "./api/mock";
import { setLanguage } from "./i18n";
import { ToastProvider } from "./toast";

beforeAll(() => installMockApi());
beforeEach(() => {
  resetMockStore();
  setLanguage("en");
});
afterEach(() => {
  act(() => setLanguage("en"));
  vi.restoreAllMocks();
});

function renderPage(path = "/") {
  return render(<ToastProvider><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></ToastProvider>);
}

it("switches the existing page without losing input and keeps Chinese across navigation", async () => {
  const user = userEvent.setup();
  renderPage();
  const input = screen.getByTestId("nct-input");
  await user.type(input, "NCT01234567");
  await user.click(screen.getByRole("button", { name: "切换到中文" }));

  expect(screen.getByTestId("nct-input")).toBe(input);
  expect(input).toHaveValue("NCT01234567");
  expect(document.documentElement.lang).toBe("zh-CN");
  expect(localStorage.getItem("tp.language")).toBe("zh");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toMatch(/[\u4e00-\u9fff]/);

  await user.click(screen.getByRole("link", { name: "关于" }));
  expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Switch to English" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Switch to English" }));
  expect(document.documentElement.lang).toBe("en");
  expect(screen.getByRole("link", { name: "About" })).toBeInTheDocument();
});

it("keeps computed values and avoids recomputing a scenario when switching languages", async () => {
  const user = userEvent.setup();
  const compute = vi.spyOn(api, "compute");
  renderPage("/scenario/mock-design-0001");
  const metric = await screen.findByTestId("metric-cost_usd-value", {}, { timeout: 4000 });
  await waitFor(() => expect(screen.getByTestId("metric-cost_usd-delta")).toBeInTheDocument());
  const value = metric.firstElementChild?.textContent;
  const range = metric.lastElementChild?.textContent;
  const calls = compute.mock.calls.length;
  await user.click(screen.getByRole("button", { name: "切换到中文" }));
  expect(screen.getByTestId("metric-cost_usd-value")).toBe(metric);
  expect(metric.firstElementChild?.textContent).toBe(value);
  expect(metric.lastElementChild?.textContent).toBe(range);
  expect(compute).toHaveBeenCalledTimes(calls);
});

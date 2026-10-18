import { useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/app/api/client";
import type { SavedScenario } from "@/app/api/types";
import { setIdentity } from "@/app/identity";
import { setLanguage } from "@/app/i18n";
import { ToastProvider } from "@/app/toast";
import { VersionsPanel } from "./components/VersionsPanel";

function scenario(id: string, name: string, author = "alex.author"): SavedScenario {
  return {
    id, name, author, lineage_id: id, version: 1, parent_id: null,
    design_id: "design-1", design_version: 1, status: "draft",
    created_at: "2026-10-17T12:00:00Z", parameter_set_version: "params-1",
    record_hash: null, metrics: {}, levers: null, result: null,
    approval_id: null, approval: null,
  };
}

function renderVersions(rows: SavedScenario[], selectedId: string | null = rows[0]?.id ?? null) {
  const onDelete = vi.fn();
  const onRefresh = vi.fn();
  vi.spyOn(api, "getScenario").mockImplementation(async (id) => {
    const row = rows.find((item) => item.id === id);
    if (!row) throw new Error("Scenario not found");
    return row;
  });

  function Harness() {
    const [scenarios, setScenarios] = useState(rows);
    const [selected, setSelected] = useState(selectedId);
    return (
      <VersionsPanel
        scenarios={scenarios}
        loading={false}
        selectedId={selected}
        onSelect={setSelected}
        onLoadLevers={vi.fn()}
        onRefresh={onRefresh}
        onDelete={(id) => {
          onDelete(id);
          setScenarios((current) => current.filter((item) => item.id !== id));
        }}
      />
    );
  }

  render(<ToastProvider><MemoryRouter><Harness /></MemoryRouter></ToastProvider>);
  return { onDelete, onRefresh };
}

beforeEach(() => {
  setLanguage("en");
  setIdentity("alex.author");
});

afterEach(() => vi.restoreAllMocks());

describe("saved scenario deletion", () => {
  it("requires confirmation and leaves the version untouched when cancelled", async () => {
    const row = scenario("scenario-1", "Remote visits");
    const remove = vi.spyOn(api, "deleteScenario").mockResolvedValue(undefined);
    const { onDelete, onRefresh } = renderVersions([row]);
    await screen.findByTestId("selected-scenario");

    await userEvent.click(screen.getByRole("button", { name: "Delete Remote visits v1" }));
    const dialog = screen.getByRole("dialog", { name: "Delete scenario version?" });
    expect(dialog).toHaveTextContent(/approval/i);
    expect(dialog).toHaveTextContent(/audit/i);
    expect(remove).not.toHaveBeenCalled();

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remote visits v1" })).toBeInTheDocument();
    expect(screen.getByTestId("selected-scenario")).toHaveTextContent("Remote visits");
    expect(remove).not.toHaveBeenCalled();
    expect(onDelete).not.toHaveBeenCalled();
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("removes the confirmed version from the list, selection and comparison", async () => {
    const first = scenario("scenario-1", "Remote visits");
    const second = scenario("scenario-2", "Local labs");
    const remove = vi.spyOn(api, "deleteScenario").mockResolvedValue(undefined);
    const { onDelete, onRefresh } = renderVersions([first, second]);
    await waitFor(() => expect(api.getScenario).toHaveBeenCalledWith(first.id, expect.anything()));
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Remote visits v1 for comparison" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Local labs v1 for comparison" }));
    expect(screen.getByTestId("compare-selected")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Delete Remote visits v1" }));
    const dialog = screen.getByRole("dialog", { name: "Delete scenario version?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(onDelete).toHaveBeenCalledWith(first.id));
    expect(remove).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledWith(first.id);
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remote visits v1" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("selected-scenario")).not.toBeInTheDocument();
    expect(screen.queryByTestId("compare-selected")).not.toBeInTheDocument();
    expect(screen.getByText("Compare 1/2")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Local labs v1 for comparison" })).toBeChecked();
  });

  it("keeps the version and confirmation available when deletion fails", async () => {
    const row = scenario("scenario-1", "Remote visits");
    const remove = vi.spyOn(api, "deleteScenario").mockRejectedValueOnce(new Error("Server unavailable"));
    const { onDelete, onRefresh } = renderVersions([row]);
    await userEvent.click(screen.getByRole("checkbox", { name: "Select Remote visits v1 for comparison" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete Remote visits v1" }));
    const dialog = screen.getByRole("dialog", { name: "Delete scenario version?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(remove).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Delete" })).toBeEnabled());
    expect(screen.getByRole("dialog", { name: "Delete scenario version?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remote visits v1" })).toBeInTheDocument();
    expect(screen.getByTestId("selected-scenario")).toHaveTextContent("Remote visits");
    expect(screen.getByRole("checkbox", { name: "Select Remote visits v1 for comparison" })).toBeChecked();
    expect(onDelete).not.toHaveBeenCalled();
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("disables deletion for another author's version", async () => {
    const own = scenario("scenario-1", "Remote visits");
    const other = scenario("scenario-2", "Local labs", "riley.reviewer");
    const remove = vi.spyOn(api, "deleteScenario").mockResolvedValue(undefined);
    renderVersions([own, other], null);

    expect(screen.getByRole("button", { name: "Delete Remote visits v1" })).toBeEnabled();
    const otherDelete = screen.getByRole("button", { name: "Delete Local labs v1" });
    expect(otherDelete).toBeDisabled();
    await userEvent.click(otherDelete);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(remove).not.toHaveBeenCalled();
  });
});

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, onApiError, request } from "./api/client";
import { normalizeApproval, normalizeDrivers, normalizeSavedScenario, normalizeScience } from "./api/normalize";
import { formatRange, formatSignedValue, formatValue, splitValue } from "./format";
import { getIdentity, identityHeaders, setIdentity } from "./identity";
import { IdentitySwitcher } from "./IdentitySwitcher";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
  setIdentity("alex.author");
});

describe("demo identity switcher", () => {
  it("is labelled as demo identities and sends X-User / X-Role on every request", async () => {
    const fetchSpy = vi.spyOn(window, "fetch").mockResolvedValue(jsonResponse({ ok: true }));
    render(<IdentitySwitcher />);
    expect(screen.getByLabelText(/demo\s*identities/i)).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByTestId("identity-switcher"), "sam.qa");
    expect(getIdentity().user).toBe("sam.qa");
    expect(identityHeaders()).toEqual({ "X-User": "sam.qa", "X-Role": "qa" });

    await request("GET", "/health");
    const init = fetchSpy.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-User"]).toBe("sam.qa");
    expect((init.headers as Record<string, string>)["X-Role"]).toBe("qa");
  });
});

describe("API client errors", () => {
  it("turns the §5 error shape into an ApiError with the plain-English message and notifies listeners", async () => {
    vi.spyOn(window, "fetch").mockResolvedValue(
      jsonResponse({ error: "self_approval_forbidden", message: "The author cannot approve.", details: {} }, 403),
    );
    const seen: ApiError[] = [];
    const off = onApiError((e) => seen.push(e));
    await expect(request("POST", "/approvals/x/sign", { body: {} })).rejects.toMatchObject({
      status: 403,
      code: "self_approval_forbidden",
      message: "The author cannot approve.",
    });
    expect(seen[0]?.message).toBe("The author cannot approve.");
    off();
  });

  it("does not notify listeners for silent calls and reports network failures plainly", async () => {
    vi.spyOn(window, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const seen: ApiError[] = [];
    const off = onApiError((e) => seen.push(e));
    await expect(request("GET", "/designs", { silent: true })).rejects.toMatchObject({ code: "network_error" });
    expect(seen).toHaveLength(0);
    off();
  });

  it("reads the parameter library from A5's `parameters` envelope", async () => {
    vi.spyOn(window, "fetch").mockResolvedValue(
      jsonResponse({ ok: true, parameters: [{ id: "a.b", label: "A", value_low: 1, value_mid: 2, value_high: 3, unit: "x" }] }),
    );
    const ps = await api.params();
    expect(ps.map((p) => p.id)).toEqual(["a.b"]);
  });
});

describe("formatting never turns unknown into zero", () => {
  it("prints unknown for NaN / null values", () => {
    expect(formatValue(Number.NaN, "usd")).toBe("unknown");
    expect(formatValue(null as unknown as number, "hours")).toBe("unknown");
    expect(formatRange({ p10: Number.NaN, p50: 1, p90: 2, unit: "usd" })).toBe("unknown");
    expect(splitValue(Number.NaN, "kg_co2e").num).toBe("unknown");
  });

  it("formats carbon in tonnes, money compactly and percent deltas in percentage points", () => {
    expect(formatValue(263_000, "kg_co2e")).toBe("263 t CO₂e");
    expect(formatValue(450, "kg_co2e")).toBe("450 kg CO₂e");
    expect(formatValue(10_300_000, "usd")).toBe("$10.3M");
    expect(formatRange({ p10: 198_000, p50: 263_000, p90: 356_000, unit: "kg_co2e" })).toBe("198 – 356 t CO₂e");
    expect(formatSignedValue(-18.2, "percent")).toBe("−18 pp");
    expect(formatSignedValue(-1_240_000, "usd")).toBe("−$1.24M");
  });
});

describe("normalisers", () => {
  it("reads A5 scenario summaries (metrics, no levers) without inventing levers", () => {
    const s = normalizeSavedScenario({
      id: "s1",
      lineage_id: "s1",
      version: 2,
      name: "B",
      design_id: "d1",
      design_version: 1,
      status: "submitted",
      author: "alex.author",
      created_at: "2026-10-17T00:00:00Z",
      parameter_set_version: "p1",
      record_hash: "ab",
      metrics: { cost_usd: { p10: 1, p50: 2, p90: 3, unit: "usd" } },
    });
    expect(s.levers).toBeNull();
    expect(s.metrics.cost_usd?.p50).toBe(2);
    expect(s.status).toBe("submitted");
  });

  it("extracts the approval embedded in a submitted scenario", () => {
    const s = normalizeSavedScenario({
      id: "s1",
      status: "submitted",
      approval: { id: "a1", record_type: "scenario", record_id: "s1", author: "alex.author", required_meanings: ["reviewed", "approved"], status: "pending", signatures: [] },
    });
    expect(s.approval?.id).toBe("a1");
    expect(s.approval_id).toBe("a1");
    expect(() => normalizeApproval({ nope: true })).toThrow();
  });

  it("keeps the top five drivers with labels", () => {
    const d = normalizeDrivers({ drivers: Array.from({ length: 7 }, (_, i) => ({ parameter_id: `p${i}`, share: 0.1, label: `P${i}` })) });
    expect(d).toHaveLength(5);
    expect(d[0].label).toBe("P0");
  });

  it("accepts science results keyed by trial", () => {
    const r = normalizeScience({ trials: { CASPS: { published_total_kg: 1000, ours_total: { p10: 800, p50: 950, p90: 1200, unit: "kg_co2e" }, modules: [] } } });
    expect(r.trials[0].name).toBe("CASPS");
    expect(r.trials[0].ours_total?.p50).toBe(950);
  });
});

describe("toast-free identity default", () => {
  it("defaults to the author when nothing is stored", () => {
    act(() => setIdentity("alex.author"));
    expect(getIdentity().role).toBe("author");
  });
});

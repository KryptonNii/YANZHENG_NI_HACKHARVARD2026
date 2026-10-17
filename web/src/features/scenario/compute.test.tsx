import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/app/api/client";
import { MOCK_DESIGN } from "@/app/api/mock/data";
import { mockCompute } from "@/app/api/mock/engine";
import { DEFAULT_LEVERS, normalizeExtraction, normalizeScenarioResult, normalizeDesignSummary } from "@/app/api/normalize";
import type { ScenarioResultX } from "@/app/api/types";
import { useScenarioCompute } from "./hooks/useScenarioCompute";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("compute response ordering", () => {
  it("discards a superseded request during the next debounce and never uses a previous design version", async () => {
    vi.useFakeTimers();
    const pending: Array<{ resolve: (value: ScenarioResultX) => void; signal?: AbortSignal }> = [];
    vi.spyOn(api, "compute").mockImplementation((_id, _levers, opts) => new Promise((resolve) => {
      pending.push({ resolve, signal: opts?.signal });
    }));
    const base = mockCompute(MOCK_DESIGN, DEFAULT_LEVERS);
    const { result, rerender } = renderHook(({ share, version }) => useScenarioCompute(MOCK_DESIGN.id, { ...DEFAULT_LEVERS, remote_monitoring_share: share }, true, version), {
      initialProps: { share: 0, version: 1 },
    });
    await act(async () => { pending[0].resolve(base); });
    expect(result.current.computing).toBe(false);
    rerender({ share: 0.5, version: 1 });
    expect(result.current.computing).toBe(true);
    await act(async () => { vi.advanceTimersByTime(150); });
    const old = pending.at(-1);
    expect(old).toBeDefined();
    rerender({ share: 0.8, version: 1 });
    expect(old?.signal?.aborted).toBe(true);
    await act(async () => { old?.resolve({ ...base, cost_usd: { p10: 1, p50: 2, p90: 3, unit: "usd" } }); });
    expect(result.current.current?.cost_usd.p50).not.toBe(2);
    expect(result.current.computing).toBe(true);
    rerender({ share: 0, version: 2 });
    expect(result.current.current).toBeNull();
    expect(result.current.baseline).toBeNull();
    await act(async () => { pending.at(-1)?.resolve(base); });
    expect(result.current.computing).toBe(false);
  });

  it("retries a failed calculation with unchanged levers", async () => {
    vi.useFakeTimers();
    const compute = vi.spyOn(api, "compute").mockRejectedValue(new Error("temporarily unavailable"));
    const { result } = renderHook(() => useScenarioCompute(MOCK_DESIGN.id, DEFAULT_LEVERS, true, 1));
    await act(async () => { vi.advanceTimersByTime(150); });
    expect(result.current.currentError).toBe("temporarily unavailable");
    compute.mockResolvedValue(mockCompute(MOCK_DESIGN, DEFAULT_LEVERS));
    await act(async () => { result.current.retry(); });
    expect(result.current.currentError).toBeNull();
    expect(result.current.current).not.toBeNull();
  });
});

describe("missing source values", () => {
  it("rejects a protocol with a missing week instead of inserting week zero", () => {
    expect(() => normalizeExtraction({ candidates: [{ visit: { ...MOCK_DESIGN.visits[0], week: null } }] })).toThrow(/Missing weeks/);
    expect(normalizeDesignSummary({ id: "incomplete" })?.enrollment_target).toBeNull();
  });

  it("retains an unknown forecast point as a gap between the known observations", () => {
    const result = normalizeScenarioResult({
      ...mockCompute(MOCK_DESIGN, DEFAULT_LEVERS),
      forecast: { enrollment_curve: [[0, 0, 0, 0], [1, null, null, null], [2, 1, 2, 3]] },
    });
    expect(result.forecast?.enrollment_curve).toEqual([[0, 0, 0, 0], [1, null, null, null], [2, 1, 2, 3]]);
  });
});

/**
 * The client's error contract: every ApiError it throws, including the ones it builds itself,
 * reaches the toast listeners once unless the call is `silent`. Saves rely on A5's If-Match check.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, onApiError } from "./client";
import { MOCK_DESIGN } from "./mock/data";
import { DEFAULT_LEVERS } from "./normalize";

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

let off: (() => void) | null = null;
function listen(): ApiError[] {
  const seen: ApiError[] = [];
  off = onApiError((e) => seen.push(e));
  return seen;
}

afterEach(() => {
  off?.();
  off = null;
  vi.restoreAllMocks();
});

describe("errors the client raises itself", () => {
  it("toasts a protocol apply reply without a design once, and not for silent calls", async () => {
    vi.spyOn(window, "fetch").mockImplementation(async () => jsonResponse({ applied_by: "x" }));
    const seen = listen();
    await expect(api.applyProtocol(MOCK_DESIGN, [], null)).rejects.toMatchObject({ status: 502, code: "protocol_design_missing" });
    expect(seen.map((e) => e.message)).toEqual(["The API did not return the reviewed design. Nothing was saved; retry applying the protocol."]);

    await expect(api.applyProtocol(MOCK_DESIGN, [], null, { silent: true })).rejects.toMatchObject({ code: "protocol_design_missing" });
    expect(seen).toHaveLength(1);
  });

  it("toasts a compute that does not confirm the pinned design version once", async () => {
    vi.spyOn(window, "fetch").mockImplementation(async () => jsonResponse({ design_id: "d1", modules: [] }, 200, { "X-Design-Version": "3" }));
    const seen = listen();
    await expect(api.compute("d1", DEFAULT_LEVERS, { designVersion: 2 })).rejects.toMatchObject({ status: 502, code: "compute_version_mismatch" });
    expect(seen.map((e) => e.code)).toEqual(["compute_version_mismatch"]);

    await expect(api.compute("d1", DEFAULT_LEVERS, { designVersion: 2, silent: true })).rejects.toMatchObject({ code: "compute_version_mismatch" });
    expect(seen).toHaveLength(1);
  });

  it("toasts a design read with a weak ETag once", async () => {
    vi.spyOn(window, "fetch").mockImplementation(async () => jsonResponse(MOCK_DESIGN, 200, { "X-Design-Version": "1", ETag: 'W/"abc"' }));
    const seen = listen();
    await expect(api.getDesign(MOCK_DESIGN.id)).rejects.toMatchObject({ status: 502, code: "design_version_missing" });
    expect(seen.map((e) => e.code)).toEqual(["design_version_missing"]);

    await expect(api.getDesign(MOCK_DESIGN.id, { silent: true })).rejects.toMatchObject({ code: "design_version_missing" });
    expect(seen).toHaveLength(1);
  });

  it("toasts a saved design without a version exactly once", async () => {
    vi.spyOn(window, "fetch").mockImplementation(async () => jsonResponse(MOCK_DESIGN, 201, { ETag: '"abc"' }));
    const seen = listen();
    await expect(api.saveDesign(MOCK_DESIGN)).rejects.toMatchObject({ status: 502, code: "design_version_missing" });
    expect(seen.map((e) => e.code)).toEqual(["design_version_missing"]);
  });
});

describe("saveDesign relies on A5's If-Match check", () => {
  it("sends one POST with If-Match and turns 409 design_changed into the plain conflict message", async () => {
    const fetchSpy = vi.spyOn(window, "fetch").mockImplementation(async () =>
      jsonResponse({ error: "design_changed", message: "Design 'x' is now version 3.", details: { version: 3, design_hash: "h3" } }, 409),
    );
    const seen = listen();
    const err = await api.saveDesign(MOCK_DESIGN, { ifMatch: "h1" }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({
      status: 409,
      code: "design_changed",
      message: "This design changed while you were editing — it is now design v3. Reload it before saving so a confirmed protocol schedule is not replaced.",
      details: { version: 3, design_hash: "h3" },
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/designs");
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["If-Match"]).toBe('"h1"');
    expect(seen).toEqual([err]);
  });

  it("stores a design with a current tag in one request", async () => {
    const fetchSpy = vi.spyOn(window, "fetch").mockImplementation(async () => jsonResponse(MOCK_DESIGN, 201, { "X-Design-Version": "2", ETag: '"h2"' }));
    await expect(api.saveDesign(MOCK_DESIGN, { ifMatch: "h2" })).resolves.toEqual({ design: MOCK_DESIGN, version: 2, etag: "h2" });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect((fetchSpy.mock.calls[0][1] as RequestInit).method).toBe("POST");
  });

  it("keeps other save errors unchanged and toasts them once", async () => {
    vi.spyOn(window, "fetch").mockImplementation(async () => jsonResponse({ error: "forbidden_role", message: "The viewer role cannot change data.", details: {} }, 403));
    const seen = listen();
    await expect(api.saveDesign(MOCK_DESIGN, { ifMatch: "h1" })).rejects.toMatchObject({ status: 403, code: "forbidden_role", message: "The viewer role cannot change data." });
    expect(seen.map((e) => e.code)).toEqual(["forbidden_role"]);

    await expect(api.saveDesign(MOCK_DESIGN, { ifMatch: "h1", silent: true })).rejects.toMatchObject({ code: "forbidden_role" });
    expect(seen).toHaveLength(1);
  });
});

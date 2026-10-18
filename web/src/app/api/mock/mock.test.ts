/**
 * The mock API follows A5's design store and A7's signing rules, so mock-mode demos cannot show
 * a flow the real API refuses.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { setIdentity } from "../../identity";
import { ApiError, api } from "../client";
import { DEFAULT_LEVERS } from "../normalize";
import { MOCK_DESIGN } from "./data";
import { installMockApi, resetMockStore } from ".";

beforeAll(() => {
  installMockApi();
});

beforeEach(() => {
  resetMockStore();
  setIdentity("alex.author");
});

afterEach(() => {
  vi.restoreAllMocks();
  setIdentity("alex.author");
});

async function submittedApprovalId(): Promise<string> {
  setIdentity("alex.author");
  const saved = await api.saveScenario({ design_id: MOCK_DESIGN.id, design_version: 1, name: "A", levers: DEFAULT_LEVERS }, { silent: true });
  const submitted = await api.submitScenario(saved.id, { silent: true });
  expect(submitted.approval_id).toBeTruthy();
  return submitted.approval_id as string;
}

describe("mock scenario deletion", () => {
  it("removes active access while preserving approval history and lineage numbering", async () => {
    const base = await api.saveScenario({ design_id: MOCK_DESIGN.id, design_version: 1, name: "A", levers: DEFAULT_LEVERS });
    const v2 = await api.newVersion(base.id, { name: "A2" });
    const submitted = await api.submitScenario(v2.id);
    const approvalId = submitted.approval_id as string;
    const before = await api.getApproval(approvalId);
    setIdentity("riley.reviewer");
    await expect(api.deleteScenario(v2.id, { silent: true })).rejects.toMatchObject({ status: 403, code: "not_author" });
    setIdentity("alex.author");
    await api.deleteScenario(v2.id);
    await api.deleteScenario(v2.id);
    await expect(api.getScenario(v2.id, { silent: true })).rejects.toMatchObject({ status: 404 });
    expect((await api.listScenarios()).map((s) => s.id)).toEqual([base.id]);
    expect(await api.getApproval(approvalId)).toEqual(before);
    expect((await api.newVersion(base.id, { name: "A3" })).version).toBe(3);
  });
});

describe("mock approvals", () => {
  it("lets one person sign only one step of a request (duplicate_signer)", async () => {
    const id = await submittedApprovalId();
    setIdentity("sam.qa");
    const reviewed = await api.sign(id, { meaning: "reviewed", pin: "3333" }, { silent: true });
    expect(reviewed.status).toBe("pending");

    await expect(api.sign(id, { meaning: "approved", pin: "3333" }, { silent: true })).rejects.toMatchObject({
      status: 403,
      code: "duplicate_signer",
      message: "One person can sign only one step of a request (segregation of duties).",
    });
    const after = await api.getApproval(id, { silent: true });
    expect(after.status).toBe("pending");
    expect(after.signatures.map((s) => `${s.signer}:${s.meaning}`)).toEqual(["sam.qa:reviewed"]);
  });

  it("answers request_closed for a closed request before checking the PIN", async () => {
    const id = await submittedApprovalId();
    setIdentity("riley.reviewer");
    await api.sign(id, { meaning: "reviewed", pin: "2222" }, { silent: true });
    setIdentity("sam.qa");
    const approved = await api.sign(id, { meaning: "approved", pin: "3333" }, { silent: true });
    expect(approved.status).toBe("approved");

    await expect(api.sign(id, { meaning: "approved", pin: "0000" }, { silent: true })).rejects.toMatchObject({ status: 409, code: "request_closed" });
  });

  it("still refuses an author's own review (self_approval_forbidden)", async () => {
    const id = await submittedApprovalId();
    await expect(api.sign(id, { meaning: "reviewed", pin: "1111" }, { silent: true })).rejects.toMatchObject({
      status: 403,
      code: "self_approval_forbidden",
    });
    await expect(api.sign(id, { meaning: "reviewed", pin: "9999" }, { silent: true })).rejects.toMatchObject({ status: 401, code: "invalid_credential" });
  });
});

describe("mock design store with If-Match", () => {
  it("saves with a stale tag only when nothing would change, and never pre-reads the design", async () => {
    const current = await api.getDesign(MOCK_DESIGN.id, { silent: true });
    expect(current).toMatchObject({ version: 1, etag: "mock-hash-1" });
    const v2 = await api.saveDesign({ ...current.design, enrollment_target: 50 }, { ifMatch: current.etag ?? undefined, silent: true });
    expect(v2.version).toBe(2);

    const fetchSpy = vi.spyOn(window, "fetch");
    // same content as the stored v2, stale tag: the store answers with v2 and writes nothing
    const same = await api.saveDesign({ ...current.design, enrollment_target: 50 }, { ifMatch: current.etag ?? undefined, silent: true });
    expect(same).toEqual({ design: v2.design, version: 2, etag: v2.etag });

    const err = await api.saveDesign({ ...current.design, enrollment_target: 60 }, { ifMatch: current.etag ?? undefined, silent: true }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, code: "design_changed", details: { version: 2 } });
    expect((err as ApiError).message).toMatch(/it is now design v2\. Reload it before saving/);
    const calls = fetchSpy.mock.calls.map(([url, init]) => `${(init as RequestInit | undefined)?.method ?? "GET"} ${String(url)}`);
    expect(calls).toEqual(["POST /api/designs", "POST /api/designs"]);
    expect((await api.getDesign(MOCK_DESIGN.id, { silent: true })).version).toBe(2);
  });
});

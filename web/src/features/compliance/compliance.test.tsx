/**
 * Approvals, audit chain and validation package.
 * // @req URS-017 URS-021 URS-032
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setIdentity } from "@/app/identity";
import { ApprovalsPage } from "./ApprovalsPage";
import { AuditPage } from "./AuditPage";
import { ValidationPage } from "./ValidationPage";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const approval = {
  id: "ap-1",
  record_type: "scenario",
  record_id: "sc-1",
  record_hash: "ab".repeat(32),
  author: "alex.author",
  author_name: "Alex Author",
  required_meanings: ["reviewed", "approved"],
  status: "pending",
  created_at: "2026-10-16T12:00:00.000Z",
  title: "Scenario B",
  signatures: [],
  next_meaning: "reviewed",
  record_changed: false,
};

function entry(seq: number) {
  return {
    seq,
    at: "2026-10-16T12:00:00.000Z",
    actor: "alex.author",
    role: "author",
    action: "ops.simulate",
    object_type: "ops_trial",
    object_id: "demo-40",
    before_hash: null,
    after_hash: null,
    reason: "start",
    prev_entry_hash: `prev-${seq}`,
    entry_hash: `entry-${seq}`,
  };
}

const validation = {
  generated_at: "2026-10-16T12:00:00.000Z",
  draft_stamp: "DRAFT — requires human review",
  deliverables: [
    { id: "D1", title: "Validation plan", status: "draft", draft_stamp: true, sha256: "abc123def4567890" },
    { id: "D7", title: "Validation summary report", status: "awaiting approval", draft_stamp: false },
  ],
  trace: {
    summary: { pass: 1, "no test": 1 },
    flags: { untested_requirements: ["URS-003"] },
    rows: [
      {
        id: "URS-003",
        text: "A requirement with no test yet",
        result: "no test",
        tests: [],
        evidence: [],
      },
      {
        id: "URS-011",
        text: "Simulated data is labelled",
        result: "pass",
        tests: [{ id: "test_label", outcome: "passed" }],
        evidence: [{ file: "e2e.playwright.json" }],
      },
    ],
  },
  defects: {
    planted: 6,
    detected: 4,
    note: "Unsigned experiment, not GxP evidence.",
    rows: [
      { id: "D-1", detected: true, stages: ["trace check"] },
      { id: "D-2", detected: false, stages: [] },
    ],
  },
  report: { status: "awaiting QA approval", record_id: "VSR-1" },
  audit_chain: { ok: true, checked: 3, first_bad_seq: null },
};

describe("approvals", () => {
  beforeEach(() => {
    setIdentity("alex.author");
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.endsWith("/sign")) {
          return json(
            { error: "self_approval_forbidden", message: "Authors can't review or approve their own work.", details: {} },
            403,
          );
        }
        if (url.includes("/approvals") && (init?.method ?? "GET") === "GET") return json({ items: [approval] });
        return json({ error: "not_found", message: url, details: {} }, 404);
      }),
    );
  });

  it("shows the self-approval message when the author signs", async () => {
    render(<ApprovalsPage />);
    expect(await screen.findByText("Scenario B")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign this record" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("PIN"), "1111");
    await userEvent.click(within(dialog).getByRole("button", { name: "Sign" }));
    expect(await screen.findByTestId("sign-error")).toHaveTextContent("Authors can't approve their own work.");
  });
});

describe("audit trail", () => {
  it("reports an intact chain and a broken chain", async () => {
    let intact = true;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/audit/verify")) {
          return intact
            ? json({ ok: true, first_bad_seq: null, checked: 3, head_hash: "abc", problem: null })
            : json({ ok: false, first_bad_seq: 4, checked: 4, head_hash: "abc", problem: "entry content does not match its entry_hash" });
        }
        if (url.includes("/audit")) return json({ items: [entry(3), entry(2), entry(1)], total: 3, limit: 25, offset: 0 });
        return json({ error: "not_found", message: url, details: {} }, 404);
      }),
    );

    render(<AuditPage />);
    expect(await screen.findAllByText("ops.simulate")).toHaveLength(3);
    await userEvent.click(screen.getByRole("button", { name: "Verify chain" }));
    expect(await screen.findByTestId("chain-result")).toHaveTextContent("Chain intact — 3 entries");

    intact = false;
    await userEvent.click(screen.getByRole("button", { name: "Verify chain" }));
    expect(await screen.findByTestId("chain-result")).toHaveTextContent("Broken at seq 4");
  });
});

describe("validation package", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => json(validation)));
  });

  it("shows the draft stamp and flags an untested requirement", async () => {
    render(<ValidationPage />);
    expect((await screen.findAllByText("DRAFT — requires human review")).length).toBeGreaterThan(0);
    expect(screen.getByTestId("untested-requirements")).toHaveTextContent("URS-003");
    expect(screen.getByTestId("trace-URS-003")).toHaveTextContent("no test");
    expect(screen.getByTestId("defect-summary")).toHaveTextContent("Detected 4 of 6");
    expect(screen.getByText("awaiting QA approval")).toBeInTheDocument();
  });
});

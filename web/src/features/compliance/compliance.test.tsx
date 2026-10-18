/**
 * Approvals, audit chain and validation package.
 * // @req URS-017 URS-021 URS-032
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/app/api/client";
import { setIdentity } from "@/app/identity";
import { ApprovalsPage } from "./ApprovalsPage";
import { AuditPage } from "./AuditPage";
import { ValidationPage } from "./ValidationPage";
import { packageFileUrl } from "./api";
import { signErrorMessage } from "./errors";

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

  it("clears the PIN and shows the new shared identity when the acting user changes", async () => {
    render(<ApprovalsPage />);
    await screen.findByText("Scenario B");
    await userEvent.click(screen.getByRole("button", { name: "Sign this record" }));
    await userEvent.type(screen.getByLabelText("PIN"), "1111");
    const { act } = await import("@testing-library/react");
    await act(async () => setIdentity("riley.reviewer"));
    expect(screen.getByLabelText("PIN")).toHaveValue("");
    expect(within(screen.getByRole("dialog")).getByText(/riley.reviewer/)).toBeInTheDocument();
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: /^Sign$/ })).toBeDisabled();
  });

  it("shows invalid signatures and prevents signing a changed record", async () => {
    const changed = { ...approval, record_changed: true, signatures: [{ id: "sig-1", signer: "riley.reviewer", signer_name: "Riley Reviewer", role: "reviewer", meaning: "reviewed", signed_at: "2026-10-16T12:00:00Z", record_hash: approval.record_hash, valid: false }] };
    vi.stubGlobal("fetch", vi.fn(async () => json({ items: [changed] })));
    render(<ApprovalsPage />);
    expect(await screen.findByText("invalid because record changed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign this record" })).toBeDisabled();
    expect(screen.getByText(/Record sha256/)).toHaveTextContent(approval.record_hash);
  });

  it("maps every sign error code to one plain sentence (shared with the scenario approval panel)", () => {
    const err = (code: string, message = "Server sentence.") => new ApiError(403, code, message);
    expect(signErrorMessage(err("self_approval_forbidden", "Authors can't review or approve their own work."))).toBe("Authors can't approve their own work.");
    expect(signErrorMessage(err("invalid_credential", "Unknown user or wrong PIN."))).toBe("Wrong PIN — the signature was not recorded.");
    for (const [code, fallback] of [
      ["out_of_order", "Signatures must follow the required order."],
      ["account_locked", "Signing is locked after too many wrong PINs."],
      ["role_not_permitted", "This role cannot sign that meaning."],
      ["record_changed", "The record changed after it was submitted."],
    ]) {
      expect(signErrorMessage(err(code))).toBe("Server sentence.");
      expect(signErrorMessage(err(code, ""))).toBe(fallback);
    }
    expect(signErrorMessage(err("unknown_code"))).toBe("Server sentence.");
    expect(signErrorMessage(new Error("Network down"))).toBe("Network down");
    expect(signErrorMessage("plain")).toBe("plain");
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

  it("loads the page again from Try again after a failed load", async () => {
    let calls = 0;
    const fetchMock = vi.fn(async () =>
      ++calls === 1
        ? json({ error: "internal_error", message: "Database unavailable", details: {} }, 500)
        : json({ items: [entry(2), entry(1)], total: 2, limit: 25, offset: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<AuditPage />);
    expect(await screen.findByText("Couldn't load the audit trail")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findAllByText("ops.simulate")).toHaveLength(2);
    expect(screen.queryByText("Couldn't load the audit trail")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("ignores a retry that answers after newer filters were applied", async () => {
    const replies: Array<(r: Response) => void> = [];
    const urls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        urls.push(String(input));
        return new Promise<Response>((resolve) => replies.push(resolve));
      }),
    );
    render(<AuditPage />);
    await waitFor(() => expect(replies).toHaveLength(1));
    replies[0](json({ error: "internal_error", message: "Database unavailable", details: {} }, 500));
    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    await waitFor(() => expect(replies).toHaveLength(2));
    await userEvent.type(screen.getByLabelText("Action"), "approval.sign");
    await userEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    await waitFor(() => expect(replies).toHaveLength(3));
    expect(urls[2]).toContain("action=approval.sign");
    replies[2](json({ items: [{ ...entry(2), action: "approval.sign" }], total: 1, limit: 25, offset: 0 }));
    expect(await screen.findByText("approval.sign")).toBeInTheDocument();
    await act(async () => {
      replies[1](json({ items: [entry(1)], total: 1, limit: 25, offset: 0 }));
      await new Promise((r) => setTimeout(r, 20));
    });
    expect(screen.queryByText("ops.simulate")).not.toBeInTheDocument();
    expect(screen.getByText("approval.sign")).toBeInTheDocument();
  });
});

describe("validation package", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => json(validation)));
  });

  it("shows the draft stamp and flags an untested requirement", async () => {
    render(<ValidationPage />);
    expect((await screen.findAllByText("Pending review")).length).toBeGreaterThan(0);
    expect(screen.getByTestId("untested-requirements")).toHaveTextContent("URS-003");
    expect(screen.getByTestId("trace-URS-003")).toHaveTextContent("no test");
    expect(screen.getByTestId("defect-summary")).toHaveTextContent("Detected 4 of 6");
    expect(screen.getByText("awaiting QA approval")).toBeInTheDocument();
  });

  it("shows the API message when the package is not built", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(
          {
            error: "package_not_built",
            message: "No validation package has been generated yet. Run `tpv package`.",
            details: { expected_path: "validation/out/package/package_index.json" },
          },
          404,
        ),
      ),
    );
    render(<ValidationPage />);
    expect(await screen.findByText("No validation package has been generated yet. Run `tpv package`.")).toBeInTheDocument();
    expect(screen.queryByText("DRAFT — requires human review")).not.toBeInTheDocument();
    expect(screen.queryByTestId("defect-summary")).not.toBeInTheDocument();
  });

  it("shows real execution failures, historical labels and deep downloadable attachments", async () => {
    const pkg = { ...validation, execution: { counts: { passed: 507, failed: 3, total: 510 }, evidence_dir: "evidence/RUN-1", integrity_problems: [] }, defects: { ...validation.defects, source: "validation/defects/LAST_RUN.json", head: "historical-commit" }, deliverables: [{ ...validation.deliverables[0], html: "plan.html", md: "plan.md" }] };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("evidence_manifest.json") ? json({ files: [{ path: "browser/attachments/trace.zip", sha256: "abc", bytes: 42 }] }) : json(pkg)));
    render(<ValidationPage />);
    expect(await screen.findByTestId("execution-summary")).toHaveTextContent("failed 3");
    expect(screen.getByText(/Historical run/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download Validation plan Markdown" })).toHaveAttribute("href", "/api/validation/package/files/plan.md");
    await userEvent.click(screen.getByText(/Evidence files and attachments/));
    expect(await screen.findByRole("link", { name: "browser/attachments/trace.zip" })).toHaveAttribute("href", "/api/validation/package/files/evidence/RUN-1/browser/attachments/trace.zip");
  });

  it("keeps unrelated 404 errors visible and rejects unsafe package paths", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ error: "not_found", message: "Unknown endpoint" }, 404)));
    render(<ValidationPage />);
    expect(await screen.findByText("Couldn't load the validation package")).toBeInTheDocument();
    expect(screen.queryByText("No validation package yet")).not.toBeInTheDocument();
    for (const path of ["../secrets", "/absolute", "https://example.com", "a\\b", "x?query", "a/%2f/../b"]) expect(packageFileUrl(path)).toBeUndefined();
    expect(packageFileUrl("evidence/a screenshot.png")).toBe("/api/validation/package/files/evidence/a%20screenshot.png");
  });
});

import { useEffect, useId, useState } from "react";
import type { ApprovalRequest, SignatureMeaning } from "@/app/contracts";
import { ApiError, api } from "@/app/api/client";
import { formatUtc } from "@/app/format";
import { displayName, useIdentity } from "@/app/identity";
import { MOCK_API } from "@/app/health";
import { Badge } from "@/app/ui";

const MEANING_TEXT: Record<string, string> = {
  authored: "authored",
  reviewed: "reviewed",
  approved: "approved",
  executed: "executed",
  verified: "verified",
};

/** Plain-English messages for the compliance error codes (A7). */
export function signErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "self_approval_forbidden":
        return `Authors can't approve their own work. ${err.message}`;
      case "out_of_order":
        return `Signatures must follow the required order. ${err.message}`;
      default:
        return err.message;
    }
  }
  return err instanceof Error ? err.message : String(err);
}

function nextMeaning(a: ApprovalRequest): string | null {
  const signed = new Set(a.signatures.map((s) => s.meaning));
  return a.required_meanings.find((m) => !signed.has(m as SignatureMeaning)) ?? null;
}

function StatusChip({ status }: { status: ApprovalRequest["status"] }) {
  if (status === "approved") return <Badge tone="better">✓ Approved</Badge>;
  if (status === "rejected") return <Badge tone="worse">✕ Rejected</Badge>;
  return <Badge tone="caution">◷ Pending approval</Badge>;
}

export function ApprovalPanel({ approval, onChange }: { approval: ApprovalRequest; onChange: (a: ApprovalRequest) => void }) {
  const me = useIdentity();
  const pinId = useId();
  const next = nextMeaning(approval);
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    setPin("");
  }, [me.user, approval.id]);

  const sign = async () => {
    if (!next) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.sign(approval.id, { meaning: next as SignatureMeaning, pin }, { silent: true });
      onChange(updated);
      setPin("");
    } catch (err) {
      setError(signErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-ink-200 p-3" data-testid="approval-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-ink-900">Approval</p>
        <span data-testid="approval-status">
          <StatusChip status={approval.status} />
        </span>
      </div>
      <p className="mt-1 text-xs text-ink-500">
        Author {displayName(approval.author)} · required: {approval.required_meanings.join(" → ")}
      </p>

      <ul className="mt-3 space-y-1.5" data-testid="signature-list">
        {approval.required_meanings.map((m) => {
          const sig = approval.signatures.find((s) => s.meaning === m);
          return (
            <li key={m} className="flex items-start gap-2 text-sm">
              <span aria-hidden className={sig ? "text-better-700" : "text-ink-400"}>
                {sig ? "✓" : "○"}
              </span>
              {sig ? (
                <span>
                  <span className="font-semibold capitalize text-ink-900">{MEANING_TEXT[sig.meaning] ?? sig.meaning}</span> by{" "}
                  <span className="font-semibold">{displayName(sig.signer)}</span> ({sig.role})
                  <span className="block text-xs tabular text-ink-500">
                    {formatUtc(sig.signed_at)} · record hash <code className="font-mono">{sig.record_hash.slice(0, 12)}…</code>
                  </span>
                </span>
              ) : (
                <span className="capitalize text-ink-500">{m} — awaiting signature</span>
              )}
            </li>
          );
        })}
      </ul>

      {approval.status === "pending" && next && (
        <form
          className="mt-3 border-t border-ink-100 pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            void sign();
          }}
        >
          <p className="text-sm text-ink-800">
            Sign as <strong>{me.name}</strong> ({me.roleLabel}) with meaning <strong className="capitalize">{next}</strong>
          </p>
          <p className="mt-1 text-xs text-ink-500">
            By signing, I confirm that I have {MEANING_TEXT[next] ?? next} this scenario. The signature is bound to the exact record hash.
          </p>
          <div className="mt-2 flex items-end gap-2">
            <div className="flex-1">
              <label htmlFor={pinId} className="label text-xs">
                Re-enter your PIN
              </label>
              <input
                id={pinId}
                type="password"
                inputMode="numeric"
                autoComplete="off"
                className="input mt-1"
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                data-testid="sign-pin"
                required
              />
            </div>
            <button type="submit" className="btn-primary" disabled={busy || pin.length === 0} data-testid="sign-button">
              {busy ? "Signing…" : `Sign: ${next}`}
            </button>
          </div>
          {MOCK_API && <p className="mt-1 text-[11px] text-ink-500">Mock API: every demo PIN is 1234.</p>}
          {error && (
            <p role="alert" className="mt-2 rounded-md border border-worse-200 bg-worse-50 px-3 py-2 text-sm font-medium text-worse-900" data-testid="sign-error">
              {error}
            </p>
          )}
        </form>
      )}
    </div>
  );
}

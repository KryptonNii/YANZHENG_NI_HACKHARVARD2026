import { useEffect, useId, useState } from "react";
import type { SignatureMeaning } from "@/app/contracts";
import { ApiError, api } from "@/app/api/client";
import type { ApprovalView, SignatureView } from "@/app/api/types";
import { formatUtc } from "@/app/format";
import { displayName, useIdentity } from "@/app/identity";
import { MOCK_API } from "@/app/health";
import { Badge } from "@/app/ui";

/** Plain-English messages for the compliance error codes (A7). */
export function signErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "self_approval_forbidden":
        return `Authors can't approve their own work. ${err.message}`;
      case "out_of_order":
        return `Signatures must follow the required order. ${err.message}`;
      case "invalid_credential":
      case "invalid_credentials":
        return `Wrong PIN — the signature was not recorded. ${err.message}`;
      default:
        return err.message;
    }
  }
  return err instanceof Error ? err.message : String(err);
}

export function nextMeaning(a: ApprovalView): string | null {
  if (a.status !== "pending") return null;
  if (a.next_meaning !== undefined) return a.next_meaning ?? null;
  const signed = new Set(a.signatures.map((s) => s.meaning));
  return a.required_meanings.find((m) => !signed.has(m as SignatureMeaning)) ?? null;
}

function StatusChip({ status }: { status: ApprovalView["status"] }) {
  if (status === "approved") return <Badge tone="better">✓ Approved</Badge>;
  if (status === "rejected") return <Badge tone="worse">✕ Rejected</Badge>;
  return <Badge tone="caution">◷ Pending approval</Badge>;
}

function Validity({ sig }: { sig: SignatureView }) {
  if (sig.valid === true) return <Badge tone="better" title="The record still matches the hash that was signed">valid</Badge>;
  if (sig.valid === false) return <Badge tone="worse" title={sig.reason ?? undefined}>invalid — {sig.reason ?? "record changed"}</Badge>;
  if (sig.valid === null) return <Badge tone="neutral" title={sig.reason ?? undefined}>validity unknown</Badge>;
  return null;
}

export function ApprovalPanel({ approval, onChange }: { approval: ApprovalView; onChange: (a: ApprovalView) => void }) {
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
        Author {approval.author_name ?? displayName(approval.author)} · required: {approval.required_meanings.join(" → ")}
      </p>
      {approval.record_changed && (
        <p className="mt-2 rounded-md bg-worse-50 px-2 py-1 text-xs font-medium text-worse-900">The record changed after it was submitted; existing signatures no longer match it.</p>
      )}

      <ul className="mt-3 space-y-2" data-testid="signature-list">
        {approval.required_meanings.map((m) => {
          const sig = approval.signatures.find((s) => s.meaning === m);
          return (
            <li key={m} className="flex items-start gap-2 text-sm">
              <span aria-hidden className={sig ? "text-better-700" : "text-ink-400"}>
                {sig ? "✓" : "○"}
              </span>
              {sig ? (
                <span className="min-w-0">
                  <span className="font-semibold capitalize text-ink-900">{sig.meaning}</span> by{" "}
                  <span className="font-semibold">{sig.signer_name ?? displayName(sig.signer)}</span> ({sig.role}) <Validity sig={sig} />
                  <span className="block text-xs tabular text-ink-500">
                    {formatUtc(sig.signed_at)} · record sha256 <code className="font-mono">{sig.record_hash.slice(0, 12)}…</code>
                  </span>
                </span>
              ) : (
                <span className="capitalize text-ink-500">{m} — awaiting signature</span>
              )}
            </li>
          );
        })}
      </ul>
      {approval.status === "rejected" && approval.reject_reason && <p className="mt-2 text-sm text-worse-800">Rejected: {approval.reject_reason}</p>}

      {next && (
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
            By signing, I confirm that I have {next} this scenario. The signature is bound to the exact record hash and recorded in the audit trail.
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
          {MOCK_API && <p className="mt-1 text-[11px] text-ink-500">Mock API demo PINs: Alex 1111 · Riley 2222 · Sam 3333.</p>}
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

import { useEffect, useState } from "react";
import type { SignatureMeaning } from "@/app/contracts";
import { ApiError, api } from "@/app/api/client";
import type { ApprovalView, SavedScenario, SignatureView } from "@/app/api/types";
import { formatRange, formatUtc } from "@/app/format";
import { displayName, useIdentity } from "@/app/identity";
import { Badge, EmptyState, ErrorPanel, Modal, Spinner } from "@/app/ui";
import { signErrorMessage } from "./errors";

const STATUSES = ["pending", "approved", "rejected", "all"] as const;

function statusTone(status: ApprovalView["status"]) {
  if (status === "approved") return "better" as const;
  if (status === "rejected") return "worse" as const;
  return "caution" as const;
}

function Validity({ sig }: { sig: SignatureView }) {
  if (sig.valid === true) return <Badge tone="better">valid</Badge>;
  if (sig.valid === false) return <Badge tone="worse">invalid because record changed</Badge>;
  if (sig.valid === null) return <Badge tone="neutral">validity unknown</Badge>;
  return null;
}

export function ApprovalsPage() {
  const me = useIdentity();
  const [status, setStatus] = useState<(typeof STATUSES)[number]>("pending");
  const [items, setItems] = useState<ApprovalView[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [signing, setSigning] = useState<ApprovalView | null>(null);

  const load = async (filter = status) => {
    setError(null);
    try {
      const all = await api.listApprovals({ silent: true });
      setItems(filter === "all" ? all : all.filter((a) => a.status === filter));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
      setItems([]);
    }
  };

  useEffect(() => {
    void load(status);
    // reload when the filter or the acting user changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, me.user]);

  return (
    <div className="space-y-4" data-testid="approvals-page">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Approvals</h1>
          <p className="mt-1 text-sm text-ink-500">Signing as {me.name} ({me.roleLabel}). An author cannot approve their own record.</p>
        </div>
        <div role="tablist" aria-label="Approval status" className="inline-flex rounded-lg border border-ink-300 bg-ink-100 p-0.5">
          {STATUSES.map((id) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={status === id}
              className={`rounded-md px-3 py-1.5 text-sm font-semibold capitalize ${status === id ? "bg-white shadow-sm" : "text-ink-600"}`}
              onClick={() => setStatus(id)}
            >
              {id}
            </button>
          ))}
        </div>
      </header>
      {error && <ErrorPanel title="Couldn't load approvals" message={error} onRetry={() => void load()} />}
      {items === null && <Spinner label="Loading approvals" />}
      {items && items.length === 0 && <EmptyState title="No approval requests in this queue" />}
      <ul className="space-y-3">
        {items?.map((item) => (
          <li key={item.id} className="card p-4" data-testid={`approval-${item.id}`}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-semibold text-ink-900">{item.title || `${item.record_type} ${item.record_id}`}</p>
                <p className="mt-0.5 text-xs text-ink-500">
                  {item.record_type.replaceAll("_", " ")} · {item.record_id} · author {item.author_name ?? displayName(item.author)}
                </p>
              </div>
              <Badge tone={statusTone(item.status)}>{item.status}</Badge>
            </div>
            <p className="mt-2 text-xs text-ink-500">Required: {item.required_meanings.join(" → ")}</p>
            {item.record_changed && (
              <p className="mt-2 text-sm font-medium text-worse-800">The record changed after submission. Signatures bound to the old hash are no longer valid.</p>
            )}
            <ul className="mt-3 space-y-2">
              {item.signatures.length === 0 && <li className="text-sm text-ink-500">No signatures yet.</li>}
              {item.signatures.map((sig) => (
                <li key={sig.id} className="text-sm">
                  <span className="font-semibold capitalize">{sig.meaning}</span> · <Validity sig={sig} />
                  <span className="mt-0.5 block text-xs text-ink-600">{sig.manifestation ?? `${displayName(sig.signer)} · ${formatUtc(sig.signed_at)}`}</span>
                  <span className="mt-1 block text-xs text-ink-600">{sig.signer_name ?? sig.signer} · {sig.signer} · {sig.role} · {sig.meaning.toUpperCase()} · {formatUtc(sig.signed_at)}</span>
                  <span className="mt-1 block break-all font-mono text-[11px] text-ink-500">Record sha256 {sig.record_hash}</span>
                </li>
              ))}
            </ul>
            <RecordPreview item={item} />
            {item.status === "pending" && item.next_meaning && (
              <button type="button" className="btn-primary mt-3" disabled={item.record_changed} onClick={() => setSigning(item)}>
                Sign this record
              </button>
            )}
          </li>
        ))}
      </ul>
      <SignDialog
        key={me.user}
        approval={signing}
        onClose={() => setSigning(null)}
        onSigned={(next) => {
          setSigning(null);
          setItems((cur) => (cur?.map((row) => (row.id === next.id ? next : row)) ?? [next]).filter((row) => status === "all" || row.status === status));
        }}
      />
    </div>
  );
}

function recordHash(item: ApprovalView): string | null {
  const hash = (item as ApprovalView & { record_hash?: string }).record_hash;
  return hash ?? null;
}

function RecordPreview({ item }: { item: ApprovalView }) {
  const [open, setOpen] = useState(false);
  const [scenario, setScenario] = useState<SavedScenario | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const show = async () => {
    setOpen(true);
    if (item.record_type !== "scenario" || scenario) return;
    try {
      setScenario(await api.getScenario(item.record_id, { silent: true }));
    } catch {
      setNote("The scenario summary is not available. The record id above is what will be signed.");
    }
  };

  return (
    <div className="mt-3">
      {!open ? (
        <button type="button" className="text-sm font-semibold text-accent-700" onClick={() => void show()}>
          Show record
        </button>
      ) : (
        <div className="rounded-lg bg-ink-50 p-3 text-sm text-ink-700">
          {scenario ? (
            <>
              <p className="font-semibold text-ink-900">{scenario.name}</p>
              <p className="mt-1 text-xs text-ink-500">
                {scenario.status} · version {scenario.version}
                {scenario.metrics.cost_usd ? ` · cost ${formatRange(scenario.metrics.cost_usd)}` : ""}
              </p>
            </>
          ) : (
            <p>{note ?? `${item.record_type} ${item.record_id}`}</p>
          )}
          <p className="mt-1 font-mono text-[11px] text-ink-500">sha256 {recordHash(item) ?? "not on this response"}</p>
        </div>
      )}
    </div>
  );
}

function SignDialog({ approval, onClose, onSigned }: { approval: ApprovalView | null; onClose: () => void; onSigned: (a: ApprovalView) => void }) {
  const me = useIdentity();
  const meaning = (approval?.next_meaning ?? null) as SignatureMeaning | null;
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPin("");
    setError(null);
  }, [approval?.id]);

  const sign = async () => {
    if (!approval || !meaning || busy || !pin.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.sign(approval.id, { meaning, pin }, { silent: true });
      onSigned(next);
    } catch (err) {
      setError(signErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={approval !== null}
      title="Sign"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" disabled={busy || pin.length === 0 || !meaning} onClick={() => void sign()}>
            {busy ? "Signing…" : "Sign"}
          </button>
        </>
      }
    >
      {approval && meaning && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void sign();
          }}
        >
          <div>
            <label className="label" htmlFor="sign-meaning">
              Meaning
            </label>
            <select id="sign-meaning" className="input mt-1" value={meaning} onChange={() => undefined}>
              <option value={meaning}>{meaning}</option>
            </select>
            <p className="mt-1 text-xs text-ink-500">Only the next meaning in order can be signed.</p>
          </div>
          <p className="text-sm text-ink-800">By signing, I confirm that I have {meaning} this {approval.record_type.replaceAll("_", " ")}.</p>
          <p className="text-sm">Signing as {me.name} ({me.user}, {me.roleLabel})</p>
          <p className="break-all font-mono text-xs text-ink-500">{approval.record_type}/{approval.record_id} · sha256 {recordHash(approval) ?? "unavailable"}</p>
          <div>
            <label className="label" htmlFor="sign-pin">
              PIN
            </label>
            <input id="sign-pin" type="password" autoComplete="off" className="input mt-1" value={pin} onChange={(e) => setPin(e.target.value)} required />
          </div>
          {error && (
            <p role="alert" data-testid="sign-error" className="rounded-md border border-worse-200 bg-worse-50 px-3 py-2 text-sm font-medium text-worse-900">
              {error}
            </p>
          )}
        </form>
      )}
    </Modal>
  );
}

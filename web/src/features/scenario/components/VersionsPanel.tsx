import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { ApprovalRequest } from "@/app/contracts";
import { api, isAbort } from "@/app/api/client";
import type { SavedScenario } from "@/app/api/types";
import { formatUtc, formatValue } from "@/app/format";
import { displayName } from "@/app/identity";
import { useToast } from "@/app/toast";
import { Badge, EmptyState, Spinner } from "@/app/ui";
import { ApprovalPanel } from "./ApprovalPanel";

export function ScenarioStatusChip({ status }: { status: SavedScenario["status"] }) {
  switch (status) {
    case "approved":
      return <Badge tone="better">✓ Approved</Badge>;
    case "submitted":
      return <Badge tone="caution">◷ Submitted</Badge>;
    case "rejected":
      return <Badge tone="worse">✕ Rejected</Badge>;
    default:
      return <Badge tone="neutral">Draft</Badge>;
  }
}

/** Saved versions of scenarios for this design + submit / approval / export for the selected one. */
export function VersionsPanel({
  scenarios,
  loading,
  selectedId,
  onSelect,
  onLoadLevers,
  onRefresh,
}: {
  scenarios: SavedScenario[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onLoadLevers: (s: SavedScenario) => void;
  onRefresh: () => void;
}) {
  const toast = useToast();
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [approval, setApproval] = useState<ApprovalRequest | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const selected = scenarios.find((s) => s.id === selectedId) ?? null;

  const loadApproval = useCallback(
    async (s: SavedScenario, signal?: AbortSignal) => {
      if (s.status === "draft") {
        setApproval(null);
        return;
      }
      setApprovalLoading(true);
      try {
        if (s.approval_id) {
          setApproval(await api.getApproval(s.approval_id, { signal, silent: true }));
        } else {
          const all = await api.listApprovals({ signal, silent: true });
          const mine = all.filter((a) => a.record_type === "scenario" && a.record_id === s.id);
          setApproval(mine[mine.length - 1] ?? null);
        }
      } catch (err) {
        if (!isAbort(err)) setApproval(null);
      } finally {
        setApprovalLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!selected) {
      setApproval(null);
      return;
    }
    const ctrl = new AbortController();
    void loadApproval(selected, ctrl.signal);
    return () => ctrl.abort();
  }, [selected, loadApproval]);

  const submit = async () => {
    if (!selected) return;
    setSubmitting(true);
    try {
      const a = await api.submitScenario(selected.id);
      setApproval(a);
      toast.push("success", "Submitted for approval", `${selected.name} v${selected.version} is now locked; edits create a new version.`);
      onRefresh();
    } catch {
      // toast already shown by the client
    } finally {
      setSubmitting(false);
    }
  };

  const toggleCompare = (id: string) =>
    setCompareIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids.slice(-1), id]));

  return (
    <section className="card p-4" aria-labelledby="versions-title" data-testid="versions-panel">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="versions-title" className="card-title">
          Saved scenarios &amp; approval
        </h2>
        {compareIds.length === 2 ? (
          <Link className="btn-secondary py-1.5" to={`/compare?a=${encodeURIComponent(compareIds[0])}&b=${encodeURIComponent(compareIds[1])}`} data-testid="compare-selected">
            Compare selected (2)
          </Link>
        ) : (
          <span className="text-xs text-ink-500">Tick two scenarios to compare them</span>
        )}
      </div>

      {loading && scenarios.length === 0 ? (
        <Spinner label="Loading saved scenarios" />
      ) : scenarios.length === 0 ? (
        <EmptyState title="No saved scenarios yet">Use “Save scenario” to keep this lever set as a version you can compare and submit.</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="versions-table">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
                <th scope="col" className="w-8 pb-1"><span className="sr-only">Compare</span></th>
                <th scope="col" className="pb-1 font-semibold">Scenario</th>
                <th scope="col" className="pb-1 font-semibold">Author</th>
                <th scope="col" className="pb-1 text-right font-semibold">Cost P50</th>
                <th scope="col" className="pb-1 font-semibold">Status</th>
                <th scope="col" className="pb-1"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => (
                <tr key={s.id} className={`border-t border-ink-100 ${s.id === selectedId ? "bg-accent-50/60" : ""}`}>
                  <td className="py-1.5">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-accent-700"
                      aria-label={`Select ${s.name} v${s.version} for comparison`}
                      checked={compareIds.includes(s.id)}
                      onChange={() => toggleCompare(s.id)}
                    />
                  </td>
                  <td className="py-1.5">
                    <button type="button" className="text-left font-semibold text-ink-900 hover:underline" onClick={() => onSelect(s.id)}>
                      {s.name} <span className="font-normal text-ink-500">v{s.version}</span>
                    </button>
                    <span className="block text-xs text-ink-500">{formatUtc(s.created_at)}</span>
                  </td>
                  <td className="py-1.5 text-ink-700">{displayName(s.author)}</td>
                  <td className="py-1.5 text-right tabular text-ink-800">{s.result ? formatValue(s.result.cost_usd.p50, "usd") : "—"}</td>
                  <td className="py-1.5">
                    <ScenarioStatusChip status={s.status} />
                  </td>
                  <td className="py-1.5 text-right">
                    <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => onLoadLevers(s)}>
                      Load levers
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="mt-4 grid gap-3 border-t border-ink-100 pt-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]" data-testid="selected-scenario">
          <div>
            <p className="text-sm font-semibold text-ink-900">
              {selected.name} <span className="font-normal text-ink-500">v{selected.version}</span>
            </p>
            <p className="mt-0.5 text-xs text-ink-500">
              Parameter set <code className="font-mono">{selected.parameter_set_version ?? "—"}</code> · {selected.id.slice(0, 8)}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {selected.status === "draft" && (
                <button type="button" className="btn-primary" onClick={() => void submit()} disabled={submitting} data-testid="submit-approval">
                  {submitting ? "Submitting…" : "Submit for approval"}
                </button>
              )}
              <a className="btn-secondary" href={api.exportUrl(selected.id, "csv")} download>
                Export CSV
              </a>
              <a className="btn-secondary" href={api.exportUrl(selected.id, "pdf")} target="_blank" rel="noreferrer">
                Export PDF
              </a>
            </div>
            {selected.status !== "draft" && (
              <p className="mt-2 text-xs text-ink-500">Submitted scenarios are immutable; changing levers and saving creates a new version.</p>
            )}
          </div>
          <div>
            {approvalLoading && !approval ? (
              <Spinner label="Loading approval" />
            ) : approval ? (
              <ApprovalPanel
                approval={approval}
                onChange={(a) => {
                  setApproval(a);
                  if (a.status !== "pending") onRefresh();
                }}
              />
            ) : selected.status === "draft" ? (
              <p className="rounded-lg bg-ink-50 px-3 py-2 text-sm text-ink-600">Not submitted yet. Submitting locks this version and starts review → approval.</p>
            ) : (
              <p className="rounded-lg bg-ink-50 px-3 py-2 text-sm text-ink-600">No approval request found for this scenario.</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

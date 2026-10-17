import { useMemo, useState } from "react";
import type { Visit } from "@/app/contracts";
import type { ExtractionCandidate } from "@/app/api/types";
import { DraftStamp } from "@/app/ui";

type RowStatus = "pending" | "accepted" | "edited" | "rejected";

interface Row {
  key: number;
  candidate: ExtractionCandidate;
  visit: Visit;
  status: RowStatus;
  editing: boolean;
}

const STATUS_CHIP: Record<RowStatus, { text: string; cls: string }> = {
  pending: { text: "To review", cls: "border-ink-300 bg-ink-50 text-ink-700" },
  accepted: { text: "✓ Accepted", cls: "border-better-300 bg-better-50 text-better-800" },
  edited: { text: "✎ Edited", cls: "border-accent-300 bg-accent-50 text-accent-800" },
  rejected: { text: "✕ Rejected", cls: "border-worse-300 bg-worse-50 text-worse-800" },
};

/**
 * Human review of AI-extracted schedule-of-activities candidates (§2 rule 6: AI outputs are
 * drafts). Nothing is applied until a person accepts rows and presses "Apply to design".
 */
export function ProtocolReview({
  candidates,
  warnings,
  canApply,
  applying,
  onApply,
}: {
  candidates: ExtractionCandidate[];
  warnings: string[];
  canApply: boolean;
  applying: boolean;
  onApply: (visits: Visit[], stats: { accepted: number; edited: number; rejected: number }) => void;
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    candidates.map((c, i) => ({ key: i, candidate: c, visit: structuredClone(c.visit), status: "pending", editing: false })),
  );

  const update = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const counts = useMemo(() => {
    const c = { pending: 0, accepted: 0, edited: 0, rejected: 0 };
    rows.forEach((r) => (c[r.status] += 1));
    return c;
  }, [rows]);

  const apply = () => {
    const visits = rows
      .filter((r) => r.status === "accepted" || r.status === "edited")
      .map((r) => r.visit)
      .sort((a, b) => a.week - b.week || a.number - b.number);
    onApply(visits, { accepted: counts.accepted, edited: counts.edited, rejected: counts.rejected });
  };

  return (
    <div data-testid="protocol-review">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <DraftStamp>AI draft — confirm each row</DraftStamp>
          <span className="text-sm text-ink-600">
            {candidates.length} candidate visit{candidates.length === 1 ? "" : "s"} · {counts.accepted + counts.edited} accepted · {counts.rejected} rejected ·{" "}
            {counts.pending} to review
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-ghost py-1.5 text-xs"
            onClick={() => setRows((rs) => rs.map((r) => (r.status === "pending" ? { ...r, status: "accepted" } : r)))}
            disabled={counts.pending === 0}
          >
            Accept all remaining
          </button>
          <button
            type="button"
            className="btn-primary py-1.5"
            disabled={!canApply || applying || counts.accepted + counts.edited === 0}
            onClick={apply}
            data-testid="apply-extraction"
            title={canApply ? undefined : "Import the trial first, then apply the extracted schedule to it"}
          >
            {applying ? "Applying…" : "Apply to design"}
          </button>
        </div>
      </div>
      {warnings.length > 0 && (
        <ul className="mb-3 list-disc rounded-lg bg-caution-50 py-2 pl-8 pr-3 text-sm text-caution-900">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {counts.pending > 0 && counts.accepted + counts.edited > 0 && (
        <p className="mb-2 text-xs text-ink-500">Rows still “to review” are not applied.</p>
      )}
      <div className="overflow-x-auto rounded-lg border border-ink-200">
        <table className="w-full text-sm">
          <thead className="bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">Visit</th>
              <th scope="col" className="px-3 py-2 font-semibold">Week</th>
              <th scope="col" className="px-3 py-2 font-semibold">Procedures</th>
              <th scope="col" className="px-3 py-2 font-semibold">Source (page · quote)</th>
              <th scope="col" className="px-3 py-2 font-semibold">Status</th>
              <th scope="col" className="px-3 py-2"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={`border-t border-ink-100 align-top ${r.status === "rejected" ? "bg-ink-50 text-ink-500" : ""}`}>
                <td className="px-3 py-2">
                  {r.editing ? (
                    <input
                      className="input py-1"
                      aria-label={`Visit ${r.visit.number} label`}
                      value={r.visit.label}
                      onChange={(e) => update(r.key, { visit: { ...r.visit, label: e.target.value } })}
                    />
                  ) : (
                    <span className={r.status === "rejected" ? "line-through" : "font-medium text-ink-900"}>
                      V{r.visit.number} {r.visit.label}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 tabular">
                  {r.editing ? (
                    <input
                      className="input w-20 py-1"
                      type="number"
                      step="0.5"
                      aria-label={`Visit ${r.visit.number} week`}
                      value={r.visit.week}
                      onChange={(e) => update(r.key, { visit: { ...r.visit, week: Number(e.target.value) } })}
                    />
                  ) : (
                    r.visit.week
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex max-w-xs flex-wrap gap-1">
                    {r.visit.procedures.map((p) => (
                      <span key={p.code} className="chip border-ink-200 bg-white text-ink-700" title={p.code}>
                        {p.label}
                        {r.editing && (
                          <button
                            type="button"
                            className="ml-0.5 text-ink-400 hover:text-worse-700"
                            aria-label={`Remove ${p.label}`}
                            onClick={() => update(r.key, { visit: { ...r.visit, procedures: r.visit.procedures.filter((x) => x.code !== p.code) } })}
                          >
                            ×
                          </button>
                        )}
                      </span>
                    ))}
                    {r.visit.procedures.length === 0 && <span className="text-xs text-ink-400">none</span>}
                  </div>
                </td>
                <td className="max-w-sm px-3 py-2 text-xs text-ink-600">
                  {r.candidate.source_page !== null && <span className="font-semibold text-ink-800">p. {r.candidate.source_page}</span>}
                  {r.candidate.quote && <q className="ml-1 italic">{r.candidate.quote}</q>}
                  {r.candidate.source_page === null && !r.candidate.quote && <span className="text-caution-800">No source quote — check manually</span>}
                  {r.candidate.confidence !== null && <span className="ml-1 text-ink-400">· confidence {Math.round(r.candidate.confidence * 100)}%</span>}
                </td>
                <td className="px-3 py-2">
                  <span className={`chip ${STATUS_CHIP[r.status].cls}`}>{STATUS_CHIP[r.status].text}</span>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  {r.editing ? (
                    <button type="button" className="btn-secondary px-2 py-1 text-xs" onClick={() => update(r.key, { editing: false, status: "edited" })}>
                      Done
                    </button>
                  ) : (
                    <div className="flex justify-end gap-1">
                      <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => update(r.key, { status: "accepted" })} aria-label={`Accept visit ${r.visit.number}`}>
                        Accept
                      </button>
                      <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => update(r.key, { editing: true })} aria-label={`Edit visit ${r.visit.number}`}>
                        Edit
                      </button>
                      <button type="button" className="btn-ghost px-2 py-1 text-xs text-worse-700" onClick={() => update(r.key, { status: "rejected" })} aria-label={`Reject visit ${r.visit.number}`}>
                        Reject
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { ApiError, api, isAbort } from "@/app/api/client";
import type { ScienceResults, ScienceTrial } from "@/app/api/types";
import { formatCo2e, formatRange, formatSignedPct, formatUtc } from "@/app/format";
import { Badge, EmptyState, ErrorPanel, Skeleton } from "@/app/ui";
import { moduleLabel } from "./metrics";

const PAPER_URL = "https://bmjopen.bmj.com/content/14/1/e075755";

function pctTone(p: number | null): string {
  if (p === null) return "text-ink-500";
  const a = Math.abs(p);
  return a <= 10 ? "text-better-700" : a <= 30 ? "text-caution-800" : "text-worse-700";
}

function ModuleBars({ trial }: { trial: ScienceTrial }) {
  const max = Math.max(
    ...trial.modules.flatMap((m) => [m.published_kg ?? 0, m.ours?.p90 ?? 0]),
    1,
  );
  const w = (v: number) => `${Math.max((v / max) * 100, 0.5)}%`;
  return (
    <table className="w-full text-sm" data-testid="science-modules">
      <caption className="sr-only">Per-module carbon, published versus TrialPilot</caption>
      <thead>
        <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
          <th scope="col" className="w-44 pb-1 font-semibold">Module</th>
          <th scope="col" className="pb-1 font-semibold">
            <span className="mr-3 inline-flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm bg-ink-400" aria-hidden /> Published</span>
            <span className="inline-flex items-center gap-1"><span className="inline-block h-2 w-3 rounded-sm bg-accent-600" aria-hidden /> TrialPilot P50 (P10–P90 whisker)</span>
          </th>
          <th scope="col" className="w-20 pb-1 text-right font-semibold">Diff</th>
        </tr>
      </thead>
      <tbody>
        {trial.modules.map((m) => (
          <tr key={m.module} className="border-t border-ink-100 align-top">
            <th scope="row" className="py-1.5 pr-2 text-left font-medium text-ink-800">
              {moduleLabel(m.module)}
              {m.note && <span className="block text-xs font-normal text-ink-500">{m.note}</span>}
            </th>
            <td className="py-1.5">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <div className="h-2.5 rounded-sm bg-ink-400" style={{ width: m.published_kg !== null ? w(m.published_kg) : 0 }} aria-hidden />
                  <span className="whitespace-nowrap text-xs tabular text-ink-600">{m.published_kg !== null ? formatCo2e(m.published_kg) : "not reported"}</span>
                </div>
                <div className="flex items-center gap-2">
                  {m.ours ? (
                    <div className="relative h-2.5" style={{ width: w(m.ours.p90) }} aria-hidden>
                      <div className="absolute inset-y-0 left-0 rounded-sm bg-accent-600" style={{ width: `${(m.ours.p50 / Math.max(m.ours.p90, 1e-9)) * 100}%` }} />
                      <div className="absolute top-1/2 h-px bg-accent-900" style={{ left: `${(m.ours.p10 / Math.max(m.ours.p90, 1e-9)) * 100}%`, right: 0 }} />
                    </div>
                  ) : null}
                  <span className="whitespace-nowrap text-xs tabular text-ink-600">{m.ours ? `${formatCo2e(m.ours.p50)} (${formatRange(m.ours)})` : "not computed"}</span>
                </div>
              </div>
            </td>
            <td className={`py-1.5 text-right font-semibold tabular ${pctTone(m.pct_diff)}`}>{m.pct_diff === null ? "—" : formatSignedPct(m.pct_diff)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TrialResultCard({ trial }: { trial: ScienceTrial }) {
  return (
    <article className="card p-5" aria-labelledby={`sci-${trial.id}`} data-testid="science-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={`sci-${trial.id}`} className="text-xl font-bold text-ink-900">{trial.name}</h2>
          {trial.registry_id && <p className="text-xs text-ink-500">{trial.registry_id}</p>}
        </div>
        {trial.check && <Badge tone="neutral">{trial.check}</Badge>}
      </div>
      <dl className="mt-4 grid grid-cols-3 gap-3 rounded-lg bg-ink-50 p-3">
        <div>
          <dt className="text-xs text-ink-500">Published total</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{trial.published_total_kg !== null ? formatCo2e(trial.published_total_kg) : "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-500">TrialPilot (P50)</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{trial.ours_total ? formatCo2e(trial.ours_total.p50) : "—"}</dd>
          {trial.ours_total && <dd className="text-xs tabular text-ink-500">P10–P90 {formatRange(trial.ours_total)}</dd>}
        </div>
        <div>
          <dt className="text-xs text-ink-500">Difference</dt>
          <dd className={`text-lg font-bold tabular ${pctTone(trial.pct_diff)}`}>{trial.pct_diff === null ? "—" : formatSignedPct(trial.pct_diff)}</dd>
        </div>
      </dl>
      {trial.modules.length > 0 && (
        <div className="mt-4">
          <ModuleBars trial={trial} />
        </div>
      )}
      <div className="mt-4 grid gap-3 text-sm sm:grid-cols-2">
        {trial.matched.length > 0 && (
          <div>
            <p className="font-semibold text-better-800">✓ What matched</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-700">{trial.matched.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
        )}
        {trial.not_matched.length > 0 && (
          <div>
            <p className="font-semibold text-worse-800">✕ What didn't</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-700">{trial.not_matched.map((t) => <li key={t}>{t}</li>)}</ul>
          </div>
        )}
      </div>
      {trial.explanation && <p className="mt-3 text-sm text-ink-700"><span className="font-semibold">Why: </span>{trial.explanation}</p>}
      <p className="mt-3 text-xs text-ink-500">
        Source:{" "}
        <a className="link" href={trial.paper_url ?? PAPER_URL} target="_blank" rel="noreferrer">
          {trial.paper_title ?? "Griffiths, Fox, Williamson et al., BMJ Open 2024"}
        </a>
      </p>
    </article>
  );
}

export function SciencePage() {
  const [data, setData] = useState<ScienceResults | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    api
      .science({ signal: ctrl.signal, silent: true })
      .then(setData)
      .catch((err) => {
        if (!isAbort(err)) setError(err);
      })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [reload]);

  const notReady = error instanceof ApiError && (error.status === 404 || error.status === 501);

  return (
    <div className="space-y-5">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold tracking-tight text-ink-900">Science check</h1>
        <p className="mt-1 text-sm text-ink-600">
          Can our engine reproduce published trial carbon footprints? We rerun two trials measured with the Low Carbon Clinical Trials Group method
          (CASPS and PRIMETIME,{" "}
          <a className="link" href={PAPER_URL} target="_blank" rel="noreferrer">BMJ Open 2024</a>) and report the gaps honestly — parameters are not
          tuned to hit the published number.
        </p>
        {data?.generated_at && <p className="mt-1 text-xs text-ink-500">Results generated {formatUtc(data.generated_at)}</p>}
      </div>
      {loading ? (
        <div className="grid gap-5 xl:grid-cols-2">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      ) : notReady ? (
        <EmptyState title="Reproduction results are not available yet">
          The science module writes <code className="font-mono">science/out/results.json</code> (run <code className="font-mono">python -m science.reproduce</code>);
          the API serves it at <code className="font-mono">/api/science/results</code>.
        </EmptyState>
      ) : error ? (
        <ErrorPanel title="Could not load the science results" message={error.message} onRetry={() => setReload((r) => r + 1)} />
      ) : data && data.trials.length > 0 ? (
        <>
          <div className="grid gap-5 xl:grid-cols-2">{data.trials.map((t) => <TrialResultCard key={t.id} trial={t} />)}</div>
          {data.notes.length > 0 && (
            <ul className="list-disc space-y-1 pl-5 text-sm text-ink-600">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          )}
        </>
      ) : (
        <EmptyState title="No trials in the results file" />
      )}
    </div>
  );
}

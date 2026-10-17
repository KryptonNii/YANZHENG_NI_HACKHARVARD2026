import { Fragment, useEffect, useState } from "react";
import { ApiError, api, isAbort } from "@/app/api/client";
import type {
  ScienceCheck,
  ScienceFinding,
  ScienceIndustryBand,
  ScienceModuleRow,
  ScienceRange,
  ScienceResults,
  ScienceRowStatus,
  ScienceTrial,
} from "@/app/api/types";
import type { MetricRange } from "@/app/contracts";
import { formatCo2e, formatRange } from "@/app/format";
import { Badge, EmptyState, ErrorPanel, Segmented, SimulatedBadge, Skeleton } from "@/app/ui";
import { moduleLabel } from "./metrics";

const PAPER_URL = "https://bmjopen.bmj.com/content/14/1/e075755";

const CHECK_ORDER = ["method", "corrected", "library", "engine_library", "engine_paper_factors"];
/** The hero comparison is our engine. Method stays first in the control so the paper arithmetic is one click away. */
const DEFAULT_CHECK = ["engine_library", "engine_paper_factors", "library", "corrected", "method"];

const CHECK_SHORT: Record<string, string> = {
  method: "Method",
  corrected: "Corrected",
  library: "Library",
  engine_library: "Engine",
  engine_paper_factors: "Engine, paper factors",
};

const STATUS_WORD: Record<ScienceRowStatus, string> = {
  match: "Match",
  close: "Close",
  gap: "Gap",
  not_reported: "Not reported",
  unavailable: "Unavailable",
};

function statusTone(status: ScienceRowStatus): "better" | "caution" | "worse" | "neutral" {
  if (status === "match") return "better";
  if (status === "close") return "caution";
  if (status === "gap") return "worse";
  return "neutral";
}

function formatSciPct(p: number | null): string {
  if (p === null || !Number.isFinite(p)) return "—";
  const rounded = Math.round(p * 10) / 10;
  if (rounded === 0) return "0%";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded)}%`;
}

function asKg(r: ScienceRange): MetricRange {
  return { p10: r.p10, p50: r.p50, p90: r.p90, unit: "kg_co2e" };
}

/** Industry-band figures are tonnes as stored. The file's unit string is printed; the numbers are not rescaled. */
function formatTonnes(v: number): string {
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v)} t`;
}

function formatTonneRange(r: ScienceRange): string {
  return `${formatTonnes(r.p10)} – ${formatTonnes(r.p90)}`;
}

function rowLabel(row: ScienceModuleRow): string {
  return row.label || moduleLabel(row.module);
}

function defaultCheckId(checks: ScienceCheck[]): string {
  for (const id of DEFAULT_CHECK) {
    const found = checks.find((c) => c.id === id && c.available);
    if (found) return found.id;
  }
  return checks.find((c) => c.available)?.id ?? checks[0]?.id ?? "";
}

function orderedChecks(checks: ScienceCheck[]): ScienceCheck[] {
  return [...checks].sort((a, b) => {
    const ia = CHECK_ORDER.indexOf(a.id);
    const ib = CHECK_ORDER.indexOf(b.id);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
}

function hasSpread(r: ScienceRange | null): boolean {
  return !!r && r.p10 !== r.p90;
}

function ModuleTable({ rows }: { rows: ScienceModuleRow[] }) {
  const max = Math.max(...rows.flatMap((m) => [m.published_kg ?? 0, m.ours?.p90 ?? 0]), 1);
  const w = (v: number) => `${Math.max((v / max) * 100, 0.6)}%`;
  return (
    <table className="w-full text-sm" data-testid="science-modules">
      <caption className="sr-only">Per-module carbon, published versus this check</caption>
      <thead>
        <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
          <th scope="col" className="w-44 pb-1 font-semibold">Module</th>
          <th scope="col" className="pb-1 font-semibold">
            <span className="mr-3 inline-flex items-center gap-1">
              <span className="inline-block h-2 w-3 rounded-sm bg-ink-400" aria-hidden /> Published
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2 w-3 rounded-sm bg-accent-600" aria-hidden /> This check, P50
            </span>
          </th>
          <th scope="col" className="w-36 pb-1 text-right font-semibold">Result</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((m) => (
          <Fragment key={m.module}>
          <tr className="border-t border-ink-100 align-middle">
            <th scope="row" className="py-2 pr-2 text-left font-medium text-ink-800">
              {rowLabel(m)}
            </th>
            <td className="py-2">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <div
                    className="h-2.5 rounded-sm bg-ink-400"
                    style={{ width: m.published_kg !== null ? w(m.published_kg) : 0 }}
                    aria-hidden
                  />
                  <span className="whitespace-nowrap text-xs tabular text-ink-600">
                    {m.published_kg !== null ? formatCo2e(m.published_kg) : "not reported"}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {m.ours ? (
                    <div className="relative h-2.5" style={{ width: w(m.ours.p90) }} aria-hidden>
                      <div
                        className="absolute inset-y-0 left-0 rounded-sm bg-accent-600"
                        style={{ width: `${(m.ours.p50 / Math.max(m.ours.p90, 1e-9)) * 100}%` }}
                      />
                      <div
                        className="absolute top-1/2 h-px bg-accent-900"
                        style={{ left: `${(m.ours.p10 / Math.max(m.ours.p90, 1e-9)) * 100}%`, right: 0 }}
                      />
                    </div>
                  ) : null}
                  <span className="whitespace-nowrap text-xs tabular text-ink-600">
                    {m.ours ? `${formatCo2e(m.ours.p50)} (${formatRange(asKg(m.ours))})` : "not computed"}
                  </span>
                </div>
              </div>
            </td>
            <td className="py-2 text-right">
              <Badge tone={statusTone(m.status)}>{STATUS_WORD[m.status]}</Badge>
              <span className="mt-1 block text-sm font-semibold tabular text-ink-800">{formatSciPct(m.diff_pct)}</span>
            </td>
          </tr>
          {m.explanation && (
            <tr>
              <td colSpan={3} className="pb-2 text-xs leading-snug text-ink-600">
                {m.explanation}
              </td>
            </tr>
          )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function TotalStrip({ row }: { row: ScienceModuleRow }) {
  const inside =
    row.published_within_range === true
      ? "Published total is inside the P10–P90 range."
      : row.published_within_range === false && hasSpread(row.ours)
        ? "Published total is outside the P10–P90 range."
        : null;
  return (
    <div className="mt-4">
      <dl className="grid grid-cols-3 gap-3 rounded-lg bg-ink-50 p-3">
        <div>
          <dt className="text-xs text-ink-500">Published total</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{row.published_kg !== null ? formatCo2e(row.published_kg) : "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-500">This check (P50)</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{row.ours ? formatCo2e(row.ours.p50) : "—"}</dd>
          {row.ours && <dd className="text-xs tabular text-ink-500">P10–P90 {formatRange(asKg(row.ours))}</dd>}
        </div>
        <div>
          <dt className="text-xs text-ink-500">Difference</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{formatSciPct(row.diff_pct)}</dd>
          <dd className="mt-1">
            <Badge tone={statusTone(row.status)}>{STATUS_WORD[row.status]}</Badge>
          </dd>
        </div>
      </dl>
      {inside && <p className="mt-2 text-sm text-ink-700">{inside}</p>}
      {row.explanation && <p className="mt-2 text-sm text-ink-700">{row.explanation}</p>}
    </div>
  );
}

const SEVERITY_TONE: Record<string, "worse" | "caution" | "neutral"> = {
  large: "worse",
  medium: "caution",
  info: "neutral",
};

function effectText(kg: number | null): string | null {
  if (kg === null) return null;
  if (kg === 0) return "No change to the published total";
  const sign = kg > 0 ? "+" : "−";
  return `${sign}${formatCo2e(Math.abs(kg))} versus the published arithmetic`;
}

function Findings({ findings }: { findings: ScienceFinding[] }) {
  if (findings.length === 0) return null;
  const order = { large: 0, medium: 1, info: 2 };
  const rows = [...findings].sort((a, b) => (order[a.severity as keyof typeof order] ?? 3) - (order[b.severity as keyof typeof order] ?? 3));
  return (
    <section className="mt-4" data-testid="science-findings" aria-label="Findings">
      <h3 className="text-sm font-semibold text-ink-800">Findings in the paper</h3>
      <ul className="mt-2 space-y-2">
        {rows.map((f) => (
          <li key={f.id} className="rounded-lg border border-ink-100 px-3 py-2">
            <p className="text-sm text-ink-800">
              <Badge tone={SEVERITY_TONE[f.severity] ?? "neutral"} className="mr-2 align-middle">
                {f.severity}
              </Badge>
              {f.summary}
            </p>
            {f.detail && <p className="mt-1 text-xs leading-snug text-ink-600">{f.detail}</p>}
            {effectText(f.effect_kg) && <p className="mt-1 text-xs tabular text-ink-500">{effectText(f.effect_kg)}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function TrialResultCard({ trial, paperUrl }: { trial: ScienceTrial; paperUrl: string }) {
  const [checkId, setCheckId] = useState(() => defaultCheckId(trial.checks));
  const check = trial.checks.find((c) => c.id === checkId) ?? trial.checks[0];
  const assumptions = trial.design_inputs.filter((d) => d.origin === "assumption");
  const facts = [
    trial.phase,
    trial.patients !== null ? `${trial.patients.toLocaleString("en-US")} patients` : null,
    trial.sites !== null ? `${trial.sites.toLocaleString("en-US")} sites` : null,
    trial.countries.length ? trial.countries.join(", ") : null,
  ].filter(Boolean);

  return (
    <article className="card p-5" aria-labelledby={`sci-${trial.id}`} data-testid="science-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={`sci-${trial.id}`} className="text-xl font-bold text-ink-900">
            {trial.name}
          </h2>
          {trial.registry_id && <p className="text-xs text-ink-500">{trial.registry_id}</p>}
          {facts.length > 0 && <p className="mt-1 text-sm text-ink-600">{facts.join(" · ")}</p>}
        </div>
        {trial.published.total_kg !== null && <Badge tone="neutral">Published {formatCo2e(trial.published.total_kg)}</Badge>}
      </div>

      {trial.summary.length > 0 && (
        <div className="mt-3 space-y-2 text-sm leading-relaxed text-ink-800">
          {trial.summary.map((s) => (
            <p key={s}>{s}</p>
          ))}
        </div>
      )}

      {trial.checks.length > 1 && (
        <div className="mt-4">
          <Segmented
            label={`${trial.name} check`}
            size="sm"
            value={check?.id ?? checkId}
            onChange={setCheckId}
            options={orderedChecks(trial.checks).map((c) => ({
              value: c.id,
              label: CHECK_SHORT[c.id] ?? c.title,
              title: c.title,
            }))}
          />
        </div>
      )}

      {check && (
        <div className="mt-3" data-testid="science-check">
          <h3 className="text-sm font-semibold text-ink-900">{check.title}</h3>
          {check.description && <p className="mt-1 text-sm text-ink-600">{check.description}</p>}
          {!check.available ? (
            <p className="mt-3 text-sm text-ink-700" role="status">
              This check is unavailable. {check.unavailable_reason ?? "The reproduction did not produce it."}
            </p>
          ) : (
            <>
              {check.total && <TotalStrip row={check.total} />}
              {check.modules.length > 0 && (
                <div className="mt-4">
                  <ModuleTable rows={check.modules} />
                </div>
              )}
              {check.notes.length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-600">
                  {check.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
              {check.line_changes.length > 0 && (
                <details className="mt-3">
                  <summary className="cursor-pointer text-sm font-semibold text-ink-800">
                    Line-by-line factor changes ({check.line_changes.length})
                  </summary>
                  <ul className="mt-2 space-y-2">
                    {check.line_changes.map((line) => (
                      <li key={line.line_id} className="rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-700">
                        <p className="font-semibold text-ink-800">
                          {moduleLabel(line.module)} — {line.item}
                        </p>
                        <p className="mt-0.5 tabular">
                          Paper {line.paper_kg !== null ? formatCo2e(line.paper_kg) : "—"}
                          {line.library_kg ? ` · library P50 ${formatCo2e(line.library_kg.p50)}` : ""}
                          {` · ${line.kind.replace(/_/g, " ")}`}
                        </p>
                        {line.note && <p className="mt-0.5">{line.note}</p>}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </div>
      )}

      {trial.checks.length === 0 && <p className="mt-3 text-sm text-ink-600">This result has no checks.</p>}

      <Findings findings={trial.findings} />

      {assumptions.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-semibold text-ink-800">
            Assumptions used to rebuild the trial ({assumptions.length})
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-ink-600">
            {assumptions.map((a) => (
              <li key={a.field}>
                <span className="font-semibold text-ink-800">{a.field.replace(/_/g, " ")}</span>: {a.value}
                {a.ref ? ` — ${a.ref}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="mt-3 text-xs text-ink-500">
        Source:{" "}
        <a className="link" href={paperUrl} target="_blank" rel="noreferrer">
          Griffiths, Fox, Williamson et al., BMJ Open 2024
        </a>
        {trial.source ? `. ${trial.source}` : ""}
      </p>
    </article>
  );
}

function bandName(title: string, registryId: string | null): string {
  const head = title.split(":")[0]?.trim() ?? "";
  if (head && head.length <= 20 && head === head.toUpperCase()) return head;
  return registryId ?? (title.length > 48 ? `${title.slice(0, 45)}…` : title);
}

function IndustryBand({ band }: { band: ScienceIndustryBand }) {
  const fileUnits = [...new Set(band.demo_trials.map((t) => t.total_t?.unit).filter((u): u is string => !!u))];
  return (
    <section className="card p-5" aria-labelledby="industry-band-title" data-testid="science-band">
      <h2 id="industry-band-title" className="text-lg font-bold text-ink-900">
        Industry band
      </h2>
      <p className="mt-1 text-sm text-ink-700">
        {band.low_t !== null && band.high_t !== null
          ? `${formatTonnes(band.low_t)} – ${formatTonnes(band.high_t)} CO₂e`
          : "Band not reported"}
        {band.trials_t.length > 0 ? ` (published trials ${band.trials_t.map((t) => formatTonnes(t)).join(", ")})` : ""}. Sanity check only — a different method, and it includes drug manufacture.
      </p>
      {band.note && <p className="mt-2 text-sm text-ink-600">{band.note}</p>}
      {fileUnits.length > 0 && (
        <p className="mt-2 text-xs text-ink-500" data-testid="science-band-unit">
          Demo trial totals are shown in tonnes. The results file labels them {fileUnits.join(", ")}. These numbers are not rescaled.
          {fileUnits.includes("kg_co2e") ? " The file still says kg_co2e; the figures are displayed as stored." : ""}
        </p>
      )}
      {band.demo_trials.length > 0 && (
        <table className="mt-4 w-full text-sm">
          <caption className="sr-only">Demo trials against the industry carbon band</caption>
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
              <th scope="col" className="pb-1 font-semibold">Trial</th>
              <th scope="col" className="pb-1 text-right font-semibold">P50</th>
              <th scope="col" className="pb-1 text-right font-semibold">P10–P90</th>
              <th scope="col" className="pb-1 text-right font-semibold">Versus band</th>
            </tr>
          </thead>
          <tbody>
            {band.demo_trials.map((t) => (
              <tr key={t.design_id} className="border-t border-ink-100">
                <th scope="row" className="py-2 pr-2 text-left font-medium text-ink-800">
                  {bandName(t.title, t.registry_id)}
                  {!t.available && t.reason && <span className="mt-0.5 block text-xs font-normal text-ink-500">{t.reason}</span>}
                </th>
                <td className="py-2 text-right tabular">{t.total_t ? formatTonnes(t.total_t.p50) : "—"}</td>
                <td className="py-2 text-right tabular text-ink-600">{t.total_t ? formatTonneRange(t.total_t) : "—"}</td>
                <td className="py-2 text-right">
                  {t.within_band === true && <Badge tone="better">Inside the band</Badge>}
                  {t.within_band === false && <Badge tone="caution">Outside the band</Badge>}
                  {t.within_band === null && <span className="text-ink-500">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {band.source && <p className="mt-3 text-xs text-ink-500">{band.source}</p>}
    </section>
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
  const paperUrl = data?.paper.url || data?.paper.full_text || PAPER_URL;
  const matchPct = data?.thresholds_pct.match ?? 1;
  const closePct = data?.thresholds_pct.close ?? 10;

  return (
    <div className="space-y-5">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold tracking-tight text-ink-900">Science check</h1>
        <p className="mt-1 text-sm text-ink-600">
          Can our engine reproduce published trial carbon footprints? We rerun two trials measured with the Low Carbon Clinical Trials Group method
          (CASPS and PRIMETIME,{" "}
          <a className="link" href={paperUrl} target="_blank" rel="noreferrer">
            BMJ Open 2024
          </a>
          ) and report the gaps honestly — parameters are not tuned to hit the published number.
        </p>
        <p className="mt-2 text-xs text-ink-500">
          Match means within {matchPct}%. Close means within {closePct}%. Anything larger is a gap, and each gap has an explanation. Drug supply is a
          TrialPilot extension and is not in the published total.
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {data?.simulated ? <SimulatedBadge /> : data?.data_label ? <Badge tone="neutral">Published data — not simulated</Badge> : null}
          {data?.engine && (
            <Badge tone={data.engine.available ? "better" : "caution"}>
              {data.engine.available ? "Engine check available" : "Engine check unavailable"}
            </Badge>
          )}
        </div>
        {data?.data_label && !data.simulated && <p className="mt-2 text-xs text-ink-500">{data.data_label}</p>}
        {(data?.parameter_set_version || data?.draws) && (
          <p className="mt-1 text-xs text-ink-500">
            {data.parameter_set_version ? `Parameter set ${data.parameter_set_version}` : ""}
            {data.seed !== null && data.draws !== null ? ` · seed ${data.seed}, ${data.draws.toLocaleString("en-US")} draws` : ""}
            {data.how_to_reproduce ? ` · reproduce with ${data.how_to_reproduce}` : ""}
          </p>
        )}
      </div>
      {loading ? (
        <div className="space-y-5">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      ) : notReady ? (
        <EmptyState title="Reproduction results are not available yet">
          The science module writes <code className="font-mono">science/out/results.json</code> (run{" "}
          <code className="font-mono">python -m science.reproduce</code>); the API serves it at <code className="font-mono">/api/science/results</code>.
        </EmptyState>
      ) : error ? (
        <ErrorPanel title="Could not load the science results" message={error.message} onRetry={() => setReload((r) => r + 1)} />
      ) : data && data.trials.length > 0 ? (
        <>
          {data.engine && !data.engine.available && data.engine.reason && (
            <p className="text-sm text-ink-700" role="status">
              Engine checks were not run. {data.engine.reason}
            </p>
          )}
          <div className="space-y-5">
            {data.trials.map((t) => (
              <TrialResultCard key={t.id} trial={t} paperUrl={paperUrl} />
            ))}
          </div>
          {data.industry_band && <IndustryBand band={data.industry_band} />}
        </>
      ) : (
        <EmptyState title="No trials in the results file" />
      )}
    </div>
  );
}

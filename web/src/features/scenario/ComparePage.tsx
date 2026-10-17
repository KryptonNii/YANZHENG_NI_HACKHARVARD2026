import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { Levers, MetricRange } from "@/app/contracts";
import { api, isAbort } from "@/app/api/client";
import type { CompareResult, SavedScenario } from "@/app/api/types";
import { formatRange, formatSignedPct, formatSignedValue, formatUtc, formatValue } from "@/app/format";
import { displayName } from "@/app/identity";
import { EmptyState, Skeleton, Spinner } from "@/app/ui";
import { ScenarioStatusChip } from "./components/VersionsPanel";
import { delta, isKnownRange, METRICS, moduleLabel, type MetricKey } from "./metrics";

const ROWS: Array<{ key: MetricKey | "drug_waste_share"; label: string }> = [
  ...METRICS.map((m) => ({ key: m.key, label: m.label })),
  { key: "drug_waste_share", label: "Drug waste share" },
];

function useFullScenario(id: string | null): { scenario: SavedScenario | null; loading: boolean } {
  const [scenario, setScenario] = useState<SavedScenario | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!id) {
      setScenario(null);
      return;
    }
    const ctrl = new AbortController();
    setScenario(null);
    setLoading(true);
    api
      .getScenario(id, { signal: ctrl.signal })
      .then((value) => { if (!ctrl.signal.aborted) setScenario(value); })
      .catch((err) => {
        if (!isAbort(err)) setScenario(null);
      })
      .finally(() => { if (!ctrl.signal.aborted) setLoading(false); });
    return () => ctrl.abort();
  }, [id]);
  return { scenario: scenario?.id === id ? scenario : null, loading };
}

function leverRows(a: Levers, b: Levers): Array<{ label: string; a: string; b: string; differs: boolean }> {
  const pct = (x: number) => `${Math.round(x * 100)}%`;
  const list = (xs: Array<number | string>) => (xs.length ? xs.join(", ") : "none");
  const rows = [
    { label: "Remote monitoring", a: pct(a.remote_monitoring_share), b: pct(b.remote_monitoring_share) },
    { label: "Home-nurse visits", a: list(a.home_visit_numbers.map((n) => `V${n}`)), b: list(b.home_visit_numbers.map((n) => `V${n}`)) },
    { label: "Telehealth visits", a: list(a.remote_visit_numbers.map((n) => `V${n}`)), b: list(b.remote_visit_numbers.map((n) => `V${n}`)) },
    { label: "Local labs", a: pct(a.local_lab_share), b: pct(b.local_lab_share) },
    { label: "Drug supply", a: a.drug_supply_strategy === "upfront" ? "Upfront" : "On-demand", b: b.drug_supply_strategy === "upfront" ? "Upfront" : "On-demand" },
    { label: "Removed procedures", a: list(a.removed_procedures), b: list(b.removed_procedures) },
    { label: "Excluded sites", a: String(a.excluded_site_ids.length), b: String(b.excluded_site_ids.length) },
  ];
  return rows.map((r) => ({ ...r, differs: r.a !== r.b }));
}

/** Change A → B. With a per-draw delta range (same design) the P10–P90 of the difference is shown. */
function DeltaCell({ a, b, perDraw }: { a: MetricRange; b: MetricRange; perDraw: MetricRange | undefined }) {
  if (perDraw && isKnownRange(perDraw)) {
    const same = perDraw.p10 <= 0 && perDraw.p90 >= 0;
    const better = perDraw.p50 < 0;
    const tone = Math.abs(perDraw.p50) < 1e-9 ? "text-ink-500" : better ? "text-better-700" : "text-worse-700";
    return (
      <span className={tone}>
        <span className="font-semibold">
          {Math.abs(perDraw.p50) < 1e-9 ? "● no change" : `${better ? "▼" : "▲"} ${formatSignedValue(perDraw.p50, b.unit)} ${better ? "lower" : "higher"}`}
        </span>
        <span className="block text-xs text-ink-500">
          P10–P90 of the difference: {formatSignedValue(perDraw.p10, b.unit)} to {formatSignedValue(perDraw.p90, b.unit)}
          {same && Math.abs(perDraw.p50) >= 1e-9 ? " (range includes no change)" : ""}
        </span>
      </span>
    );
  }
  if (!isKnownRange(a) || !isKnownRange(b)) return <span className="text-ink-500">unknown (a value is missing)</span>;
  const d = delta(b, a);
  if (d.direction === "same") return <span className="text-ink-500">● no change</span>;
  const better = d.direction === "lower";
  return (
    <span className={`font-semibold ${better ? "text-better-700" : "text-worse-700"}`}>
      {better ? "▼" : "▲"} {formatSignedValue(d.abs, b.unit)} ({formatSignedPct(d.pct)}) {better ? "lower" : "higher"}
      <span className="block text-xs font-normal text-ink-500">difference of P50s</span>
    </span>
  );
}

function Picker({ label, value, options, onChange, testId }: { label: string; value: string | null; options: SavedScenario[]; onChange: (id: string) => void; testId: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      <select className="input mt-1" value={value ?? ""} onChange={(e) => onChange(e.target.value)} data-testid={testId}>
        <option value="" disabled>
          Choose a saved scenario…
        </option>
        {options.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name} v{s.version} — design v{s.design_version ?? "?"} — {displayName(s.author)} ({s.status})
          </option>
        ))}
      </select>
    </label>
  );
}

export function ComparePage() {
  const [search, setSearch] = useSearchParams();
  const [all, setAll] = useState<SavedScenario[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [cmp, setCmp] = useState<CompareResult | null>(null);
  const [cmpError, setCmpError] = useState<string | null>(null);
  const aId = search.get("a");
  const bId = search.get("b");

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .listScenarios(undefined, { signal: ctrl.signal, silent: true })
      .then(setAll)
      .catch(() => setAll([]))
      .finally(() => setLoadingList(false));
    return () => ctrl.abort();
  }, []);

  const A = useFullScenario(aId);
  const B = useFullScenario(bId);
  const a = A.scenario;
  const b = B.scenario;
  const sameDesign = !!a && !!b && a.design_version !== null && a.design_id === b.design_id && a.design_version === b.design_version;
  const resultA = a?.result;
  const resultB = b?.result;

  useEffect(() => {
    setCmp(null);
    setCmpError(null);
    if (!a || !b || !sameDesign) return;
    const ctrl = new AbortController();
    api
      .compare(a.id, b.id, { signal: ctrl.signal, silent: true })
      .then(setCmp)
      .catch((err) => {
        if (!isAbort(err)) setCmpError(err instanceof Error ? err.message : String(err));
      });
    return () => ctrl.abort();
  }, [a, b, sameDesign]);

  const setSide = (key: "a" | "b", id: string) => {
    const next = new URLSearchParams(search);
    next.set(key, id);
    setSearch(next, { replace: true });
  };

  const levers = useMemo(() => (a?.levers && b?.levers ? leverRows(a.levers, b.levers) : []), [a, b]);
  const modules = useMemo(() => {
    if (!resultA || !resultB) return [];
    const ids = [...new Set([...resultA.modules, ...resultB.modules].map((m) => m.module))];
    return ids.map((m) => ({ module: m, a: resultA.modules.find((x) => x.module === m), b: resultB.modules.find((x) => x.module === m) }));
  }, [resultA, resultB]);

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-900">Compare scenarios</h1>
        <p className="mt-1 text-sm text-ink-600">
          Side by side, with the change from A to B. Lower is better for every metric. For two scenarios of the same trial design, the change is
          computed per Monte Carlo draw, so its P10–P90 shows how certain the difference is.
        </p>
      </div>

      {loadingList ? (
        <Spinner label="Loading saved scenarios" />
      ) : all.length < 2 ? (
        <EmptyState title="Save at least two scenarios to compare" action={<Link to="/" className="btn-secondary">Import a trial</Link>}>
          In the simulator, set levers and press “Save scenario”. Saved versions appear here.
        </EmptyState>
      ) : (
        <div className="card grid gap-4 p-4 md:grid-cols-2">
          <Picker label="Scenario A (reference)" value={aId} options={all} onChange={(id) => setSide("a", id)} testId="compare-a" />
          <Picker label="Scenario B" value={bId} options={all} onChange={(id) => setSide("b", id)} testId="compare-b" />
        </div>
      )}

      {a && b && !sameDesign && (
        <p className="rounded-lg border border-caution-300 bg-caution-50 px-4 py-2 text-sm text-caution-900">
          These scenarios are not on the same design version
          {a.design_version != null || b.design_version != null ? ` (design v${a.design_version ?? "?"} and design v${b.design_version ?? "?"})` : ""}.
          Per-draw comparison stays off, because the difference would mix the design change with the levers.
        </p>
      )}
      {cmp && cmp.warnings.length > 0 && (
        <ul className="list-disc rounded-lg border border-caution-300 bg-caution-50 py-2 pl-8 pr-4 text-sm text-caution-900">
          {cmp.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {cmpError && <p className="text-sm text-ink-600">Per-draw comparison unavailable ({cmpError}); showing the difference of P50s.</p>}

      {(A.loading || B.loading) && <Skeleton className="h-64 w-full" />}

      {a && b && resultA && resultB && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {[a, b].map((s, i) => (
              <div key={s.id} className="card p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Scenario {i === 0 ? "A" : "B"}</p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <p className="text-lg font-bold text-ink-900">
                    {s.name} <span className="font-normal text-ink-500">v{s.version}</span>
                  </p>
                  <ScenarioStatusChip status={s.status} />
                </div>
                <p className="mt-0.5 text-xs text-ink-500">
                  {displayName(s.author)} · {formatUtc(s.created_at)} · parameter set <code className="font-mono">{s.parameter_set_version}</code>
                </p>
                <Link className="link mt-2 inline-block text-sm" to={`/scenario/${encodeURIComponent(s.design_id)}?s=${encodeURIComponent(s.id)}`}>
                  Open in simulator
                </Link>
              </div>
            ))}
          </div>

          <section className="card overflow-x-auto p-4" aria-labelledby="cmp-metrics">
            <h2 id="cmp-metrics" className="card-title mb-2">
              Metrics (P50, with P10–P90)
            </h2>
            <table className="w-full text-sm" data-testid="compare-table">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
                  <th scope="col" className="pb-2 font-semibold">Metric</th>
                  <th scope="col" className="pb-2 font-semibold">A</th>
                  <th scope="col" className="pb-2 font-semibold">B</th>
                  <th scope="col" className="pb-2 font-semibold">Change A → B</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map((m) => {
                  const ra = resultA[m.key];
                  const rb = resultB[m.key];
                  return (
                    <tr key={m.key} className="border-t border-ink-100 align-top">
                      <th scope="row" className="py-2 pr-3 text-left font-semibold text-ink-800">
                        {m.label}
                      </th>
                      <td className="py-2 pr-3 tabular">
                        <span className="font-semibold text-ink-900">{formatValue(ra.p50, ra.unit)}</span>
                        <span className="block text-xs text-ink-500">{formatRange(ra)}</span>
                      </td>
                      <td className="py-2 pr-3 tabular">
                        <span className="font-semibold text-ink-900">{formatValue(rb.p50, rb.unit)}</span>
                        <span className="block text-xs text-ink-500">{formatRange(rb)}</span>
                      </td>
                      <td className="py-2 tabular">
                        <DeltaCell a={ra} b={rb} perDraw={cmp?.deltas[m.key]} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <div className="grid gap-5 xl:grid-cols-2">
            <section className="card overflow-x-auto p-4" aria-labelledby="cmp-levers">
              <h2 id="cmp-levers" className="card-title mb-2">
                Levers
              </h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
                    <th scope="col" className="pb-2 font-semibold">Lever</th>
                    <th scope="col" className="pb-2 font-semibold">A</th>
                    <th scope="col" className="pb-2 font-semibold">B</th>
                  </tr>
                </thead>
                <tbody>
                  {levers.map((r) => (
                    <tr key={r.label} className={`border-t border-ink-100 ${r.differs ? "bg-accent-50/50" : ""}`}>
                      <th scope="row" className="py-1.5 pr-3 text-left font-medium text-ink-800">
                        {r.label}
                        {r.differs && <span className="ml-1 text-xs font-normal text-accent-800">(differs)</span>}
                      </th>
                      <td className="py-1.5 pr-3 text-ink-700">{r.a}</td>
                      <td className="py-1.5 font-semibold text-ink-900">{r.b}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="card overflow-x-auto p-4" aria-labelledby="cmp-modules">
              <h2 id="cmp-modules" className="card-title mb-2">
                Modules (difference of P50s)
              </h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
                    <th scope="col" className="pb-2 font-semibold">Module</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Cost A → B</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Carbon A → B</th>
                  </tr>
                </thead>
                <tbody>
                  {modules.map(({ module, a: ma, b: mb }) => {
                    const subtract = (left: number | null | undefined, right: number | null | undefined) =>
                      typeof left === "number" && typeof right === "number" ? right - left : null;
                    const dc = ma && mb ? subtract(ma.cost_usd.p50, mb.cost_usd.p50) : null;
                    const dk = ma && mb ? subtract(ma.co2e_kg.p50, mb.co2e_kg.p50) : null;
                    const cls = (d: number | null) => (d === null || !Number.isFinite(d) || Math.abs(d) < 1e-9 ? "text-ink-500" : d < 0 ? "text-better-700" : "text-worse-700");
                    const txt = (d: number | null, unit: string) => (d === null ? "—" : Number.isFinite(d) && Math.abs(d) < 1e-9 ? "no change" : formatSignedValue(d, unit));
                    return (
                      <tr key={module} className="border-t border-ink-100">
                        <th scope="row" className="py-1.5 pr-3 text-left font-medium text-ink-800">
                          {moduleLabel(module)}
                        </th>
                        <td className={`py-1.5 text-right tabular ${cls(dc)}`}>{txt(dc, "usd")}</td>
                        <td className={`py-1.5 text-right tabular ${cls(dk)}`}>{txt(dk, "kg_co2e")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </section>
          </div>
        </>
      )}
    </div>
  );
}

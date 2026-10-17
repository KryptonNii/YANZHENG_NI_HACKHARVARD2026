import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import type { Levers, MetricRange } from "@/app/contracts";
import { api, isAbort } from "@/app/api/client";
import type { SavedScenario, ScenarioResultX } from "@/app/api/types";
import { formatRange, formatSignedPct, formatSignedValue, formatUtc, formatValue } from "@/app/format";
import { displayName } from "@/app/identity";
import { EmptyState, Skeleton, Spinner } from "@/app/ui";
import { ScenarioStatusChip } from "./components/VersionsPanel";
import { delta, METRICS, moduleLabel } from "./metrics";

interface Side {
  scenario: SavedScenario;
  result: ScenarioResultX | null;
}

function useSide(id: string | null, all: SavedScenario[]): { side: Side | null; loading: boolean } {
  const [side, setSide] = useState<Side | null>(null);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!id) {
      setSide(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    (async () => {
      const scenario = all.find((s) => s.id === id) ?? (await api.getScenario(id, { signal: ctrl.signal, silent: true }));
      // saved rows normally carry their result; recompute only if the API omitted it
      const result = scenario.result ?? (await api.compute(scenario.design_id, scenario.levers, { signal: ctrl.signal, silent: true }));
      return { scenario, result };
    })()
      .then((s) => setSide(s))
      .catch((err) => {
        if (!isAbort(err)) setSide(null);
      })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [id, all]);
  return { side, loading };
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

function DeltaCell({ a, b }: { a: MetricRange; b: MetricRange }) {
  const d = delta(b, a);
  if (d.direction === "same") return <span className="text-ink-500">● no change</span>;
  const better = d.direction === "lower";
  return (
    <span className={`font-semibold ${better ? "text-better-700" : "text-worse-700"}`}>
      {better ? "▼" : "▲"} {formatSignedValue(d.abs, b.unit)} ({formatSignedPct(d.pct)}) {better ? "lower" : "higher"}
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
            {s.name} v{s.version} — {displayName(s.author)} ({s.status})
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

  const A = useSide(aId, all);
  const B = useSide(bId, all);
  const setSide = (key: "a" | "b", id: string) => {
    const next = new URLSearchParams(search);
    next.set(key, id);
    setSearch(next, { replace: true });
  };

  const levers = useMemo(() => (A.side && B.side ? leverRows(A.side.scenario.levers, B.side.scenario.levers) : []), [A.side, B.side]);
  const modules = useMemo(() => {
    if (!A.side?.result || !B.side?.result) return [];
    const ids = [...new Set([...A.side.result.modules, ...B.side.result.modules].map((m) => m.module))];
    return ids.map((m) => ({
      module: m,
      a: A.side!.result!.modules.find((x) => x.module === m),
      b: B.side!.result!.modules.find((x) => x.module === m),
    }));
  }, [A.side, B.side]);

  const differentDesigns = A.side && B.side && A.side.scenario.design_id !== B.side.scenario.design_id;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-ink-900">Compare scenarios</h1>
        <p className="mt-1 text-sm text-ink-600">Side by side, with the change from A to B. Lower is better for every metric shown.</p>
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

      {differentDesigns && (
        <p className="rounded-lg border border-caution-300 bg-caution-50 px-4 py-2 text-sm text-caution-900">
          These scenarios belong to different trial designs, so differences also reflect the trials themselves.
        </p>
      )}

      {(A.loading || B.loading) && <Skeleton className="h-64 w-full" />}

      {A.side && B.side && A.side.result && B.side.result && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            {[A.side, B.side].map((s, i) => (
              <div key={s.scenario.id} className="card p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">Scenario {i === 0 ? "A" : "B"}</p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <p className="text-lg font-bold text-ink-900">
                    {s.scenario.name} <span className="font-normal text-ink-500">v{s.scenario.version}</span>
                  </p>
                  <ScenarioStatusChip status={s.scenario.status} />
                </div>
                <p className="mt-0.5 text-xs text-ink-500">
                  {displayName(s.scenario.author)} · {formatUtc(s.scenario.created_at)} · parameter set{" "}
                  <code className="font-mono">{s.result?.parameter_set_version}</code>
                </p>
                <Link className="link mt-2 inline-block text-sm" to={`/scenario/${encodeURIComponent(s.scenario.design_id)}?s=${encodeURIComponent(s.scenario.id)}`}>
                  Open in simulator
                </Link>
              </div>
            ))}
          </div>

          <section className="card overflow-x-auto p-4" aria-labelledby="cmp-metrics">
            <h2 id="cmp-metrics" className="card-title mb-2">Metrics (P50, with P10–P90)</h2>
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
                {[...METRICS.map((m) => ({ key: m.key as keyof ScenarioResultX, label: m.label })), { key: "drug_waste_share" as const, label: "Drug waste share" }].map((m) => {
                  const a = A.side!.result![m.key] as MetricRange;
                  const b = B.side!.result![m.key] as MetricRange;
                  return (
                    <tr key={String(m.key)} className="border-t border-ink-100">
                      <th scope="row" className="py-2 pr-3 text-left font-semibold text-ink-800">{m.label}</th>
                      <td className="py-2 pr-3 tabular">
                        <span className="font-semibold text-ink-900">{formatValue(a.p50, a.unit)}</span>
                        <span className="block text-xs text-ink-500">{formatRange(a)}</span>
                      </td>
                      <td className="py-2 pr-3 tabular">
                        <span className="font-semibold text-ink-900">{formatValue(b.p50, b.unit)}</span>
                        <span className="block text-xs text-ink-500">{formatRange(b)}</span>
                      </td>
                      <td className="py-2 tabular">
                        <DeltaCell a={a} b={b} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>

          <div className="grid gap-5 xl:grid-cols-2">
            <section className="card overflow-x-auto p-4" aria-labelledby="cmp-levers">
              <h2 id="cmp-levers" className="card-title mb-2">Levers</h2>
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
                        {r.differs && <span className="sr-only"> (differs)</span>}
                      </th>
                      <td className="py-1.5 pr-3 text-ink-700">{r.a}</td>
                      <td className="py-1.5 font-semibold text-ink-900">{r.b}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <section className="card overflow-x-auto p-4" aria-labelledby="cmp-modules">
              <h2 id="cmp-modules" className="card-title mb-2">Modules (P50)</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
                    <th scope="col" className="pb-2 font-semibold">Module</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Cost A → B</th>
                    <th scope="col" className="pb-2 text-right font-semibold">Carbon A → B</th>
                  </tr>
                </thead>
                <tbody>
                  {modules.map(({ module, a, b }) => {
                    const dc = a && b ? b.cost_usd.p50 - a.cost_usd.p50 : null;
                    const dk = a && b ? b.co2e_kg.p50 - a.co2e_kg.p50 : null;
                    const cls = (d: number | null) => (d === null || Math.abs(d) < 1e-9 ? "text-ink-500" : d < 0 ? "text-better-700" : "text-worse-700");
                    return (
                      <tr key={module} className="border-t border-ink-100">
                        <th scope="row" className="py-1.5 pr-3 text-left font-medium text-ink-800">{moduleLabel(module)}</th>
                        <td className={`py-1.5 text-right tabular ${cls(dc)}`}>{dc === null ? "—" : Math.abs(dc) < 1e-9 ? "no change" : formatSignedValue(dc, "usd")}</td>
                        <td className={`py-1.5 text-right tabular ${cls(dk)}`}>{dk === null ? "—" : Math.abs(dk) < 1e-9 ? "no change" : formatSignedValue(dk, "kg_co2e")}</td>
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

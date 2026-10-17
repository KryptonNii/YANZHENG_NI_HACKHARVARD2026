import { useMemo, useState } from "react";
import type { Parameter } from "@/app/contracts";
import { AssumptionTag, Spinner } from "@/app/ui";
import { useParamLibrary } from "./hooks/useParamLibrary";
import { moduleLabel } from "./metrics";

const PAPER_URL = "https://bmjopen.bmj.com/content/14/1/e075755";
const MODULES = ["setup", "trial_management", "meetings_travel", "intervention", "data_collection", "supplies_equipment", "patient_assessments", "samples", "laboratory", "closeout", "drug_supply"];

function ParamTable({ params }: { params: Parameter[] }) {
  const [q, setQ] = useState("");
  const [onlyAssumptions, setOnlyAssumptions] = useState(false);
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return params
      .filter((p) => (!onlyAssumptions || p.assumption) && (!s || `${p.id} ${p.label} ${p.source_title ?? ""}`.toLowerCase().includes(s)))
      .sort((a, b) => a.id.localeCompare(b.id));
  }, [params, q, onlyAssumptions]);
  const assumed = params.filter((p) => p.assumption).length;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <input type="search" className="input max-w-sm" placeholder="Search parameters or sources" aria-label="Search parameters" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="flex items-center gap-2 text-sm text-ink-700">
          <input type="checkbox" className="h-4 w-4 accent-accent-700" checked={onlyAssumptions} onChange={(e) => setOnlyAssumptions(e.target.checked)} />
          Only assumptions
        </label>
        <span className="text-sm text-ink-500">
          {params.length} parameters · {params.length - assumed} sourced · {assumed} labelled assumptions
        </span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-ink-200">
        <table className="w-full text-sm" data-testid="param-table">
          <thead className="bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">Parameter</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Low</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Mid</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">High</th>
              <th scope="col" className="px-3 py-2 font-semibold">Unit</th>
              <th scope="col" className="px-3 py-2 font-semibold">Source / rationale</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className="border-t border-ink-100 align-top">
                <td className="px-3 py-2">
                  <p className="font-medium text-ink-900">{p.label}</p>
                  <code className="font-mono text-[11px] text-ink-500">{p.id} · v{p.version}{p.region ? ` · ${p.region}` : ""}</code>
                </td>
                <td className="px-3 py-2 text-right tabular">{p.value_low}</td>
                <td className="px-3 py-2 text-right tabular font-semibold">{p.value_mid}</td>
                <td className="px-3 py-2 text-right tabular">{p.value_high}</td>
                <td className="px-3 py-2 text-xs text-ink-600">{p.unit}</td>
                <td className="max-w-md px-3 py-2 text-xs text-ink-700">
                  {p.assumption ? (
                    <span className="flex items-start gap-2"><AssumptionTag /> <span className="pt-0.5">{p.rationale ?? "No rationale recorded."}</span></span>
                  ) : p.source_url ? (
                    <a className="link" href={p.source_url} target="_blank" rel="noreferrer">{p.source_title ?? p.source_url}</a>
                  ) : (
                    p.source_title ?? <span className="text-caution-900">No source recorded</span>
                  )}
                  {p.source_year ? ` (${p.source_year})` : ""}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-ink-500">No parameters match.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AboutPage() {
  const lib = useParamLibrary();
  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold tracking-tight text-ink-900">Method &amp; sources</h1>
        <p className="mt-2 text-ink-700">
          TrialPilot estimates what a clinical-trial design costs in money, site staff time, patient travel time, calendar time and carbon — and how
          those change when you move design levers. It is a planning aid, not a budget: every number is a range with its working shown.
        </p>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <section className="card p-5">
          <h2 className="card-title">Activity × factor</h2>
          <p className="mt-2 text-sm text-ink-700">
            Each trial-specific activity (visits, monitoring trips, sample shipments, kits) is counted from the design, then multiplied by cost,
            staff-minute and emission factors from the parameter library. Carbon follows the Low Carbon Clinical Trials Group 10-module framework (
            <a className="link" href={PAPER_URL} target="_blank" rel="noreferrer">Griffiths, Fox, Williamson, BMJ Open 2024</a>).
          </p>
        </section>
        <section className="card p-5">
          <h2 className="card-title">Uncertainty</h2>
          <p className="mt-2 text-sm text-ink-700">
            Every parameter has a low, mid and high value. The engine samples each from a triangular distribution (2,000 seeded Monte Carlo draws)
            and reports P10, P50 and P90. The provenance drawer ranks the five parameters that drive most of the variance.
          </p>
        </section>
        <section className="card p-5">
          <h2 className="card-title">Honesty rules</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-700">
            <li>Every parameter has a source (URL and year) or is labelled an assumption with a rationale.</li>
            <li>Missing inputs are reported as missing and filled with labelled assumptions, never silently zeroed.</li>
            <li>Simulated operational data is labelled “Simulated feed”.</li>
            <li>AI-extracted protocol data is a draft until a person accepts it.</li>
          </ul>
        </section>
      </div>

      <section className="card p-5">
        <h2 className="card-title">Modules</h2>
        <ol className="mt-3 grid gap-x-6 gap-y-1 text-sm text-ink-700 sm:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m, i) => (
            <li key={m}>
              <span className="tabular text-ink-500">{i + 1}.</span> {moduleLabel(m)}
              {m === "intervention" && <span className="text-xs text-ink-500"> — excluded by default</span>}
              {m === "drug_supply" && <span className="text-xs text-ink-500"> — extension beyond the published method</span>}
            </li>
          ))}
        </ol>
      </section>

      <section className="card p-5">
        <h2 className="card-title mb-3">Parameter library</h2>
        {lib.status === "loading" && <Spinner label="Loading parameter library" />}
        {lib.status === "error" && <p className="text-sm text-worse-800">The parameter library could not be loaded: {lib.message}</p>}
        {lib.status === "ready" && <ParamTable params={[...lib.byId.values()]} />}
      </section>
    </div>
  );
}

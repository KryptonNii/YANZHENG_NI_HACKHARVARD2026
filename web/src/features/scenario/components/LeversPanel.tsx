import { useId, useMemo, useState, type ReactNode } from "react";
import type { Levers, TrialDesign } from "@/app/contracts";
import { DEFAULT_LEVERS } from "@/app/api/normalize";
import { Segmented } from "@/app/ui";
import { leversEqual } from "../hooks/useScenarioCompute";

type VisitMode = "site" | "home" | "remote";

function visitMode(levers: Levers, n: number): VisitMode {
  if (levers.home_visit_numbers.includes(n)) return "home";
  if (levers.remote_visit_numbers.includes(n)) return "remote";
  return "site";
}

function setVisitMode(levers: Levers, n: number, mode: VisitMode): Levers {
  const home = levers.home_visit_numbers.filter((x) => x !== n);
  const remote = levers.remote_visit_numbers.filter((x) => x !== n);
  if (mode === "home") home.push(n);
  if (mode === "remote") remote.push(n);
  return { ...levers, home_visit_numbers: home.sort((a, b) => a - b), remote_visit_numbers: remote.sort((a, b) => a - b) };
}

function toggle<T>(xs: T[], x: T): T[] {
  return xs.includes(x) ? xs.filter((y) => y !== x) : [...xs, x];
}

function Group({ title, hint, children, changed }: { title: string; hint?: string; children: ReactNode; changed?: boolean }) {
  return (
    <fieldset className="min-w-0 border-t border-ink-100 px-4 py-4 first:border-t-0">
      <legend className="sr-only">{title}</legend>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-ink-900" aria-hidden>
          {title}
        </p>
        {changed && <span className="chip border-accent-300 bg-accent-50 text-accent-800">changed</span>}
      </div>
      {hint && <p className="-mt-1 mb-2 text-xs text-ink-500">{hint}</p>}
      {children}
    </fieldset>
  );
}

function ShareSlider({ label, value, onChange, describe, testId }: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  describe: (pct: number) => string;
  testId: string;
}) {
  const id = useId();
  const pct = Math.round(value * 100);
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="label">
          {label}
        </label>
        <output htmlFor={id} className="text-lg font-bold tabular text-ink-900">
          {pct}%
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={0}
        max={100}
        step={5}
        value={pct}
        aria-valuetext={describe(pct)}
        data-testid={testId}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        className="mt-2"
      />
      <p className="mt-1 text-xs text-ink-500">{describe(pct)}</p>
    </div>
  );
}

export function LeversPanel({ design, levers, onChange }: { design: TrialDesign; levers: Levers; onChange: (l: Levers) => void }) {
  const [siteFilter, setSiteFilter] = useState("");

  const procedures = useMemo(() => {
    const byCode = new Map<string, { code: string; label: string; visits: number }>();
    for (const v of design.visits) {
      for (const p of v.procedures) {
        const e = byCode.get(p.code) ?? { code: p.code, label: p.label, visits: 0 };
        e.visits += 1;
        byCode.set(p.code, e);
      }
    }
    return [...byCode.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [design.visits]);

  const sites = useMemo(() => {
    const q = siteFilter.trim().toLowerCase();
    const list = q
      ? design.sites.filter((s) => `${s.name} ${s.city ?? ""} ${s.country}`.toLowerCase().includes(q))
      : design.sites;
    return list;
  }, [design.sites, siteFilter]);

  const set = (patch: Partial<Levers>) => onChange({ ...levers, ...patch });
  const visitsChanged = levers.home_visit_numbers.length + levers.remote_visit_numbers.length > 0;

  return (
    <div className="card overflow-hidden" data-testid="levers-panel">
      <div className="flex items-center justify-between border-b border-ink-200 bg-ink-50/60 px-4 py-3">
        <h2 className="text-base font-semibold text-ink-900">Design levers</h2>
        <button
          type="button"
          className="btn-ghost px-2 py-1 text-xs"
          onClick={() => onChange({ ...DEFAULT_LEVERS })}
          disabled={leversEqual(levers, DEFAULT_LEVERS)}
        >
          Reset to baseline
        </button>
      </div>

      <Group title="Remote monitoring" changed={levers.remote_monitoring_share > 0}>
        <ShareSlider
          label="Monitoring visits done remotely"
          value={levers.remote_monitoring_share}
          onChange={(v) => set({ remote_monitoring_share: v })}
          describe={(p) => (p === 0 ? "All monitoring visits on site" : `${p}% of monitoring visits replaced by remote review`)}
          testId="lever-remote-monitoring"
        />
      </Group>

      <Group
        title="Visits: on site, home nurse or telehealth"
        hint="Moving a visit removes patient travel for it and adds home-nurse or telehealth cost."
        changed={visitsChanged}
      >
        {design.visits.length === 0 ? (
          <p className="text-sm text-ink-500">No visit schedule in this design yet. Import a protocol to add one.</p>
        ) : (
          <ul className="max-h-72 space-y-1.5 overflow-y-auto pr-1" data-testid="visit-levers">
            {design.visits.map((v) => {
              const mode = visitMode(levers, v.number);
              return (
                <li key={v.number} className="flex items-center justify-between gap-2 rounded-lg px-1 py-0.5 hover:bg-ink-50">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink-800" title={v.label}>
                      <span className="tabular text-ink-500">V{v.number}</span> {v.label}
                    </p>
                    <p className="text-xs text-ink-500">
                      Week {v.week}
                      {!v.can_be_remote && mode !== "site" && (
                        <span className="ml-1 font-semibold text-caution-800" title="The design does not mark this visit as remote-eligible; confirm clinically">
                          · not marked remote-eligible
                        </span>
                      )}
                    </p>
                  </div>
                  <Segmented<VisitMode>
                    size="sm"
                    label={`Visit ${v.number} ${v.label} location`}
                    value={mode}
                    onChange={(m) => onChange(setVisitMode(levers, v.number, m))}
                    options={[
                      { value: "site", label: "Site" },
                      { value: "home", label: "Home" },
                      { value: "remote", label: "Tele", title: "Telehealth" },
                    ]}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </Group>

      <Group title="Local labs" changed={levers.local_lab_share > 0}>
        <ShareSlider
          label="Samples analysed locally"
          value={levers.local_lab_share}
          onChange={(v) => set({ local_lab_share: v })}
          describe={(p) => (p === 0 ? "All samples shipped to the central lab" : `${p}% of samples analysed at local labs (adds harmonisation cost)`)}
          testId="lever-local-labs"
        />
      </Group>

      <Group title="Drug supply strategy" changed={levers.drug_supply_strategy !== "upfront"}>
        <Segmented
          label="Drug supply strategy"
          value={levers.drug_supply_strategy}
          onChange={(v) => set({ drug_supply_strategy: v })}
          options={[
            { value: "upfront", label: "Upfront stocking" },
            { value: "on_demand", label: "On-demand resupply" },
          ]}
        />
        <p className="mt-1.5 text-xs text-ink-500">
          {levers.drug_supply_strategy === "upfront"
            ? "Each site stocked for its expected patients at activation."
            : "Sites resupplied when stock runs low: less waste, more shipments, stockout risk reported."}
        </p>
      </Group>

      <Group title="Remove procedures" hint="Removed from every visit." changed={levers.removed_procedures.length > 0}>
        {procedures.length === 0 ? (
          <p className="text-sm text-ink-500">No procedures in the visit schedule.</p>
        ) : (
          <ul className="max-h-56 space-y-0.5 overflow-y-auto pr-1">
            {procedures.map((p) => {
              const removed = levers.removed_procedures.includes(p.code);
              return (
                <li key={p.code}>
                  <label className="flex cursor-pointer items-center gap-2.5 rounded-md px-1 py-1 text-sm hover:bg-ink-50">
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-ink-400 accent-worse-700"
                      checked={removed}
                      onChange={() => set({ removed_procedures: toggle(levers.removed_procedures, p.code) })}
                    />
                    <span className={`flex-1 ${removed ? "text-ink-500 line-through" : "text-ink-800"}`}>{p.label}</span>
                    <span className="text-xs text-ink-500 tabular">
                      {p.visits} visit{p.visits === 1 ? "" : "s"}
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
        )}
      </Group>

      <Group
        title={`Sites (${design.sites.length - levers.excluded_site_ids.length} of ${design.sites.length} included)`}
        hint="Untick to exclude a site, or click its dot on the map."
        changed={levers.excluded_site_ids.length > 0}
      >
        {design.sites.length > 8 && (
          <input
            type="search"
            className="input mb-2 py-1.5"
            placeholder="Filter sites by name, city or country"
            aria-label="Filter sites"
            value={siteFilter}
            onChange={(e) => setSiteFilter(e.target.value)}
          />
        )}
        <ul className="max-h-56 space-y-0.5 overflow-y-auto pr-1" data-testid="site-levers">
          {sites.map((s) => {
            const included = !levers.excluded_site_ids.includes(s.id);
            return (
              <li key={s.id}>
                <label className="flex cursor-pointer items-center gap-2.5 rounded-md px-1 py-1 text-sm hover:bg-ink-50">
                  <input
                    type="checkbox"
                    className="h-4 w-4 rounded border-ink-400 accent-accent-700"
                    checked={included}
                    onChange={() => set({ excluded_site_ids: toggle(levers.excluded_site_ids, s.id) })}
                  />
                  <span className={`min-w-0 flex-1 truncate ${included ? "text-ink-800" : "text-ink-500 line-through"}`} title={s.name}>
                    {s.name}
                  </span>
                  <span className="shrink-0 text-xs text-ink-500">{[s.city, s.country].filter(Boolean).join(", ")}</span>
                </label>
              </li>
            );
          })}
          {sites.length === 0 && <li className="px-1 text-sm text-ink-500">No sites match.</li>}
        </ul>
      </Group>
    </div>
  );
}

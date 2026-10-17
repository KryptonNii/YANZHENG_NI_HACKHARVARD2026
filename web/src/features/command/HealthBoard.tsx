import { useMemo, useState } from "react";
import type { ProvenanceItem } from "@/app/contracts";
import { Badge, Drawer } from "@/app/ui";
import type { CountryRow, HealthSnapshot, SiteRow } from "./api";
import { bandText, displayStatus, kpiCaption, kpiHeadline, siteStatusLabel, statusLabel, statusTone } from "./present";

function BandSpark({ value, band }: { value: number; band: { p10: number; p50: number; p90: number } }) {
  const lo = band.p10;
  const hi = Math.max(band.p90, lo);
  const span = hi - lo || 1;
  const pad = span * 0.2;
  const min = Math.min(lo, value) - pad;
  const max = Math.max(hi, value) + pad;
  const x = (n: number) => ((n - min) / (max - min || 1)) * 100;
  const outside = value < lo || value > hi;
  return (
    <svg viewBox="0 0 100 16" className="h-4 w-28 shrink-0" role="img" aria-label={`Actual ${value}, plan band ${lo} to ${hi}, P50 ${band.p50}`}>
      <rect x={x(lo)} y={5} width={Math.max(x(hi) - x(lo), 1.5)} height={6} rx={3} fill="#e2e8f0" />
      <circle cx={x(band.p50)} cy={8} r={1.8} fill="#64748b" />
      <circle cx={x(value)} cy={8} r={2.6} fill={outside ? "#b91c1c" : "#0f766e"} />
    </svg>
  );
}

function SortHeader({ label, active, dir, onClick }: { label: string; active: boolean; dir: "asc" | "desc"; onClick: () => void }) {
  return (
    <button type="button" className="inline-flex items-center gap-1 font-semibold text-ink-600 hover:text-ink-900" onClick={onClick}>
      {label}
      <span aria-hidden className="text-[10px] text-ink-400">
        {active ? (dir === "asc" ? "▲" : "▼") : "↕"}
      </span>
    </button>
  );
}

export function HealthBoard({ health, onOpenProvenance }: { health: HealthSnapshot; onOpenProvenance: (item: ProvenanceItem, title: string) => void }) {
  return (
    <section aria-label="Study health" data-testid="kpi-grid">
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
        {health.kpis.map((kpi) => {
          const caption = kpiCaption(kpi, health.study);
          const prov = health.provenance?.[kpi.id];
          return (
            <li key={kpi.id} className="card flex flex-col p-3" data-testid={`kpi-${kpi.id}`}>
              <div className="flex items-start justify-between gap-2">
                <p className="text-[11px] font-semibold uppercase leading-tight tracking-wide text-ink-500">{kpi.label}</p>
                <Badge tone={statusTone(displayStatus(kpi, health.study))}>{statusLabel(displayStatus(kpi, health.study))}</Badge>
              </div>
              <p className="mt-2 text-lg font-semibold leading-tight tabular text-ink-900">{kpiHeadline(kpi, health.study)}</p>
              {caption && <p className="mt-1 text-xs leading-snug text-ink-500">{caption}</p>}
              {prov && (
                <button type="button" className="mt-2 self-start text-xs font-semibold text-accent-700 hover:underline" onClick={() => onOpenProvenance(prov, kpi.label)}>
                  Why this number
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

type SiteSort = "name" | "country" | "status" | "enrolled" | "queries";
type CountrySort = "country" | "sites" | "stalled" | "enrolled" | "queries";

export function Drilldown({ health }: { health: HealthSnapshot }) {
  const [level, setLevel] = useState<"countries" | "sites">("sites");
  const [country, setCountry] = useState<string | null>(null);
  const [siteSort, setSiteSort] = useState<{ key: SiteSort; dir: "asc" | "desc" }>({ key: "enrolled", dir: "desc" });
  const [countrySort, setCountrySort] = useState<{ key: CountrySort; dir: "asc" | "desc" }>({ key: "enrolled", dir: "desc" });

  const sites = useMemo(() => {
    const rows = country ? health.sites.filter((s) => s.country === country) : health.sites;
    const dir = siteSort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => dir * cmpSite(a, b, siteSort.key));
  }, [health.sites, country, siteSort]);

  const countries = useMemo(() => {
    const dir = countrySort.dir === "asc" ? 1 : -1;
    return [...health.countries].sort((a, b) => dir * cmpCountry(a, b, countrySort.key));
  }, [health.countries, countrySort]);

  const toggleSite = (key: SiteSort) => setSiteSort((s) => ({ key, dir: s.key === key && s.dir === "desc" ? "asc" : "desc" }));
  const toggleCountry = (key: CountrySort) => setCountrySort((s) => ({ key, dir: s.key === key && s.dir === "desc" ? "asc" : "desc" }));

  return (
    <section className="card overflow-hidden" data-testid="drilldown">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-200 px-4 py-3">
        <div>
          <h2 className="card-title">Study → country → site</h2>
          <p className="mt-1 text-xs text-ink-500">Enrollment against the plan band. The dot is actual; the bar is P10–P90.</p>
        </div>
        <div className="flex items-center gap-2">
          {country && (
            <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => setCountry(null)}>
              Clear {country}
            </button>
          )}
          <div role="tablist" aria-label="Drill-down level" className="inline-flex rounded-lg border border-ink-300 bg-ink-100 p-0.5">
            {(["countries", "sites"] as const).map((id) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={level === id}
                className={`rounded-md px-3 py-1 text-sm font-semibold capitalize ${level === id ? "bg-white text-ink-900 shadow-sm" : "text-ink-600"}`}
                onClick={() => setLevel(id)}
              >
                {id}
              </button>
            ))}
          </div>
        </div>
      </header>
      <div className="max-h-[28rem] overflow-auto">
        {level === "countries" ? (
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-ink-50 text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2"><SortHeader label="Country" active={countrySort.key === "country"} dir={countrySort.dir} onClick={() => toggleCountry("country")} /></th>
                <th className="px-3 py-2"><SortHeader label="Sites" active={countrySort.key === "sites"} dir={countrySort.dir} onClick={() => toggleCountry("sites")} /></th>
                <th className="px-3 py-2"><SortHeader label="Stalled" active={countrySort.key === "stalled"} dir={countrySort.dir} onClick={() => toggleCountry("stalled")} /></th>
                <th className="px-3 py-2"><SortHeader label="Enrolled vs plan" active={countrySort.key === "enrolled"} dir={countrySort.dir} onClick={() => toggleCountry("enrolled")} /></th>
                <th className="px-3 py-2"><SortHeader label="Queries" active={countrySort.key === "queries"} dir={countrySort.dir} onClick={() => toggleCountry("queries")} /></th>
              </tr>
            </thead>
            <tbody>
              {countries.map((c) => (
                <tr key={c.country} className="border-t border-ink-100 hover:bg-accent-50/40">
                  <td className="px-4 py-2">
                    <button
                      type="button"
                      className="font-semibold text-accent-800 hover:underline"
                      onClick={() => {
                        setCountry(c.country);
                        setLevel("sites");
                      }}
                    >
                      {c.country}
                    </button>
                    {c.region && <span className="ml-2 text-xs text-ink-500">{c.region}</span>}
                  </td>
                  <td className="px-3 py-2 tabular">{c.n_sites}</td>
                  <td className="px-3 py-2 tabular">{c.stalled_sites}</td>
                  <td className="px-3 py-2">
                    <EnrollmentCell value={c.enrolled} band={c.planned_to_date} />
                  </td>
                  <td className="px-3 py-2 tabular">{c.open_queries}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-ink-50 text-xs uppercase tracking-wide">
              <tr>
                <th className="px-4 py-2"><SortHeader label="Site" active={siteSort.key === "name"} dir={siteSort.dir} onClick={() => toggleSite("name")} /></th>
                <th className="px-3 py-2"><SortHeader label="Country" active={siteSort.key === "country"} dir={siteSort.dir} onClick={() => toggleSite("country")} /></th>
                <th className="px-3 py-2"><SortHeader label="Status" active={siteSort.key === "status"} dir={siteSort.dir} onClick={() => toggleSite("status")} /></th>
                <th className="px-3 py-2"><SortHeader label="Enrolled vs plan" active={siteSort.key === "enrolled"} dir={siteSort.dir} onClick={() => toggleSite("enrolled")} /></th>
                <th className="px-3 py-2"><SortHeader label="Queries" active={siteSort.key === "queries"} dir={siteSort.dir} onClick={() => toggleSite("queries")} /></th>
                <th className="px-3 py-2">Kits on hand</th>
              </tr>
            </thead>
            <tbody>
              {sites.map((s) => (
                <tr key={s.site_id} className="border-t border-ink-100" data-testid={`site-${s.site_id}`}>
                  <td className="px-4 py-2">
                    <span className="font-semibold text-ink-900">{s.name}</span>
                    <span className="ml-2 font-mono text-xs text-ink-400">{s.site_id}</span>
                  </td>
                  <td className="px-3 py-2">{s.country}</td>
                  <td className="px-3 py-2">
                    <Badge tone={statusTone(s.status)}>{siteStatusLabel(s.status)}</Badge>
                  </td>
                  <td className="px-3 py-2">
                    <EnrollmentCell value={s.enrolled} band={s.planned_to_date} />
                  </td>
                  <td className="px-3 py-2 tabular">
                    {s.open_queries}
                    <span className="ml-1 text-xs text-ink-500">{s.median_query_age_days == null ? "" : `· ${s.median_query_age_days}d`}</span>
                  </td>
                  <td className="px-3 py-2 tabular text-ink-700">
                    {Math.round(s.drug_on_hand_kits)}
                    {s.drug_need_kits && <span className="ml-1 text-xs text-ink-500">need {bandText(s.drug_need_kits)}</span>}
                  </td>
                </tr>
              ))}
              {sites.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-6 text-center text-ink-500">No sites in this view.</td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}

function EnrollmentCell({ value, band }: { value: number; band: { p10: number; p50: number; p90: number } }) {
  return (
    <div className="flex items-center gap-2">
      <BandSpark value={value} band={band} />
      <span className="tabular text-ink-800">
        {value}
        <span className="ml-1 text-xs text-ink-500">/ {Math.round(band.p50)}</span>
      </span>
    </div>
  );
}

function cmpSite(a: SiteRow, b: SiteRow, key: SiteSort): number {
  if (key === "name") return a.name.localeCompare(b.name);
  if (key === "country") return a.country.localeCompare(b.country) || a.name.localeCompare(b.name);
  if (key === "status") return a.status.localeCompare(b.status);
  if (key === "queries") return a.open_queries - b.open_queries;
  return a.enrolled - b.enrolled;
}

function cmpCountry(a: CountryRow, b: CountryRow, key: CountrySort): number {
  if (key === "country") return a.country.localeCompare(b.country);
  if (key === "sites") return a.n_sites - b.n_sites;
  if (key === "stalled") return a.stalled_sites - b.stalled_sites;
  if (key === "queries") return a.open_queries - b.open_queries;
  return a.enrolled - b.enrolled;
}

export function ProvenanceDrawer({ item, title, onClose }: { item: ProvenanceItem | null; title: string; onClose: () => void }) {
  return (
    <Drawer open={item !== null} title={title} subtitle={item?.formula_id} onClose={onClose}>
      {item && (
        <div className="space-y-4 text-sm">
          <p className="text-ink-800">{item.description}</p>
          {(item.assumptions ?? []).length > 0 && (
            <div>
              <p className="card-title mb-1">Assumptions</p>
              <ul className="list-disc space-y-1 pl-4 text-ink-700">
                {item.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </div>
          )}
          <div>
            <p className="card-title mb-1">Inputs</p>
            <ul className="space-y-1 font-mono text-xs text-ink-700">
              {Object.entries(item.inputs).map(([k, v]) => (
                <li key={k}>
                  {k}: {String(v)}
                </li>
              ))}
            </ul>
          </div>
          <p className="text-xs text-ink-500">Parameters: {item.parameter_ids.join(", ") || "none"}</p>
        </div>
      )}
    </Drawer>
  );
}

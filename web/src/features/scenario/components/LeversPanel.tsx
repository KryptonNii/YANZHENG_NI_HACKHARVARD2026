import { useTranslation, translate as t } from "@/app/i18n";
import { useId, useMemo, useState, type ReactNode } from "react";
import type { Levers, TrialDesign } from "@/app/contracts";
import { DEFAULT_LEVERS } from "@/app/api/normalize";
import { Segmented } from "@/app/ui";
import { leversEqual } from "../hooks/useScenarioCompute";
import { groupProcedures, procedureMeaning } from "../procedureGroups";
import { ENDPOINT_ROLES, LINK_BASES } from "./ProtocolReview";

type VisitMode = "site" | "home" | "remote";
type EndpointLink = {
  label: string;
  role: keyof typeof ENDPOINT_ROLES;
  basis: keyof typeof LINK_BASES;
  note: string;
  visits: number[];
};

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
  useTranslation();
  return (
    <fieldset className="min-w-0 border-t border-ink-100 px-4 py-4 first:border-t-0">
      <legend className="sr-only">{title}</legend>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="text-sm font-semibold text-ink-900" aria-hidden>
          {title}
        </p>
        {changed && <span className="chip border-accent-300 bg-accent-50 text-accent-800">{t("changed", "已更改")}</span>}
      </div>
      {hint && <p className="-mt-1 mb-2 text-xs text-ink-500">{hint}</p>}
      {children}
    </fieldset>
  );
}

function ShareSlider({ label, value, onChange, describe, testId, min = 0, max = 100, step = 5 }: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  describe: (pct: number) => string;
  testId: string;
  min?: number;
  max?: number;
  step?: number;
}) {
  useTranslation();
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
        min={min}
        max={max}
        step={step}
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
  useTranslation();
  const [siteFilter, setSiteFilter] = useState("");
  const countriesId = useId();
  const enrollmentRate = levers.enrollment_rate_multiplier ?? 1;
  const addedCountries = levers.added_country_count ?? 0;

  const procedures = useMemo(() => groupProcedures(design.visits), [design.visits]);
  const endpointLinks = useMemo(() => {
    const links = new Map<string, Map<string, EndpointLink>>();
    for (const visit of design.visits) {
      for (const p of visit.procedures) {
        const role = p.endpoint_role ?? "unknown";
        const basis = p.link_basis ?? "unmatched";
        const note = p.endpoint_note ?? "";
        const entries = links.get(p.code) ?? new Map<string, EndpointLink>();
        const key = JSON.stringify([p.label, role, basis, note]);
        const entry = entries.get(key) ?? { label: p.label, role, basis, note, visits: [] };
        if (!entry.visits.includes(visit.number)) entry.visits.push(visit.number);
        entries.set(key, entry);
        links.set(p.code, entries);
      }
    }
    return links;
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
        <h2 className="text-base font-semibold text-ink-900">{t("Design levers", "设计调整项")}</h2>
        <button
          type="button"
          className="btn-ghost px-2 py-1 text-xs"
          onClick={() => onChange({ ...DEFAULT_LEVERS })}
          disabled={leversEqual(levers, DEFAULT_LEVERS)}
        >
          {t("Reset to baseline", "重置为基线")}
        </button>
      </div>

      <Group title={t("Enrollment speed", "入组速度")} changed={enrollmentRate !== 1}>
        <ShareSlider
          label={t("Enrollment speed", "入组速度")}
          value={enrollmentRate}
          min={50}
          max={150}
          step={10}
          onChange={(v) => set({ enrollment_rate_multiplier: v })}
          describe={(p) => p === 100 ? t("Sites enroll at the planned rate", "研究中心按计划速度招募受试者") : t(`Sites enroll at ${p}% of the planned rate`, `研究中心按计划速度的 ${p}% 招募受试者`)}
          testId="lever-enrollment-rate"
        />
      </Group>

      <Group title={t("Add assumed countries", "添加假设国家")} changed={addedCountries > 0}>
        <label htmlFor={countriesId} className="label">{t("Add assumed countries", "添加假设国家")}</label>
        <input
          id={countriesId}
          type="number"
          min={0}
          max={5}
          step={1}
          value={addedCountries}
          data-testid="lever-added-countries"
          onChange={(e) => set({ added_country_count: Math.max(0, Math.min(5, Math.round(Number(e.target.value)))) })}
          className="input mt-1 w-20 tabular"
        />
        <p className="mt-1 text-xs text-ink-500">
          {addedCountries === 0 ? t("No extra countries", "未添加国家") : t(`${addedCountries} assumed ${addedCountries === 1 ? "country" : "countries"} added`, `已添加 ${addedCountries} 个假设国家`)}
        </p>
        {addedCountries > 0 && <p className="mt-1 text-xs text-ink-500">{t("Added countries are assumptions, not registry sites. Each adds one assumed site, weighted by the median positive expected enrollment of active sites, or the default patients per site when unavailable.", "新增国家为假设，不属于注册记录中的研究中心。每个国家增加一个假设研究中心，按活跃中心的正值预期入组人数中位数赋权；若无可用数据，则采用每中心默认人数。")}</p>}
      </Group>

      <Group title={t("Remote monitoring", "远程监查")} changed={levers.remote_monitoring_share > 0}>
        <ShareSlider
          label={t("Monitoring visits done remotely", "远程开展的监查访视")}
          value={levers.remote_monitoring_share}
          onChange={(v) => set({ remote_monitoring_share: v })}
          describe={(p) => (p === 0 ? t("All monitoring visits on site", "所有监查访视均在现场进行") : t(`${p}% of monitoring visits replaced by remote review`, `${p}% 的监查访视替换为远程审核`))}
          testId="lever-remote-monitoring"
        />
      </Group>

      <Group
        title={t("Visits: on site, home nurse or telehealth", "访视：现场、上门护理或远程医疗")}
        hint={t("Moving a visit removes patient travel for it and adds home-nurse or telehealth cost.", "更改访视地点可减少受试者出行，同时增加上门护理或远程医疗费用。")}
        changed={visitsChanged}
      >
        {design.visits.length === 0 ? (
          <p className="text-sm text-ink-500">{t("No visit schedule in this design yet. Import a protocol to add one.", "此设计暂无访视计划。导入试验方案即可添加。")}</p>
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
                      {t("Week", "周次")} {v.week}
                      {!v.can_be_remote && mode !== "site" && (
                        <span className="ml-1 font-semibold text-caution-800" title={t("The design does not mark this visit as remote-eligible; confirm clinically", "设计未将此访视标记为可远程开展；请进行临床确认")}>
                          {t("· not marked remote-eligible", "· 未标记为可远程开展")}
                        </span>
                      )}
                    </p>
                  </div>
                  <Segmented<VisitMode>
                    size="sm"
                    label={t(`Visit ${v.number} ${v.label} location`, `访视 ${v.number} ${v.label} 的地点`)}
                    value={mode}
                    onChange={(m) => onChange(setVisitMode(levers, v.number, m))}
                    options={[
                      { value: "site", label: t("Site", "现场") },
                      { value: "home", label: t("Home", "上门") },
                      { value: "remote", label: t("Tele", "远程"), title: t("Telehealth", "远程医疗") },
                    ]}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </Group>

      <Group title={t("Local labs", "本地实验室")} changed={levers.local_lab_share > 0}>
        <ShareSlider
          label={t("Samples analysed locally", "在本地分析的样本")}
          value={levers.local_lab_share}
          onChange={(v) => set({ local_lab_share: v })}
          describe={(p) => (p === 0 ? t("All samples shipped to the central lab", "所有样本均送至中心实验室") : t(`${p}% of samples analysed at local labs (adds harmonisation cost)`, `${p}% 的样本在本地实验室分析（增加标准化费用）`))}
          testId="lever-local-labs"
        />
      </Group>

      <Group title={t("Drug supply strategy", "药物供应策略")} changed={levers.drug_supply_strategy !== "upfront"}>
        <Segmented
          label={t("Drug supply strategy", "药物供应策略")}
          value={levers.drug_supply_strategy}
          onChange={(v) => set({ drug_supply_strategy: v })}
          options={[
            { value: "upfront", label: t("Upfront stocking", "预先备货") },
            { value: "on_demand", label: t("On-demand resupply", "按需补货") },
          ]}
        />
        <p className="mt-1.5 text-xs text-ink-500">
          {levers.drug_supply_strategy === "upfront"
            ? t("Each site stocked for its expected patients at activation.", "各研究中心启用时，按预期受试者人数备货。")
            : t("Sites resupplied when stock runs low: less waste, more shipments, stockout risk reported.", "库存不足时补货：减少浪费、增加运输次数，并报告缺货风险。")}
        </p>
      </Group>

      <Group
        title={t("Remove procedures", "移除检查项目")}
        hint={t("One row per procedure code. Checking Remove removes every assessment listed, on every visit where that code appears. Endpoint roles can be corrected during protocol review.", "每行对应一个检查项目代码。勾选移除后，将删除所有访视中具有该代码的全部评估。终点关联可在试验方案审核时更正。")}
        changed={levers.removed_procedures.length > 0}
      >
        {procedures.length === 0 ? (
          <p className="text-sm text-ink-500">{t("No procedures in the visit schedule.", "访视计划中暂无检查项目。")}</p>
        ) : (
          <ul className="max-h-72 space-y-1 overflow-y-auto pr-1" data-testid="procedure-levers">
            {procedures.map((p) => {
              const removed = levers.removed_procedures.includes(p.code);
              const labels = p.labels.filter((label) => label !== p.meaning);
              const labelText = (labels.length > 0 ? labels : p.labels).join(", ");
              return (
                <li key={p.code} data-testid={`procedure-${p.code}`}>
                  <label className="flex cursor-pointer items-start gap-2.5 rounded-md px-1 py-1 text-sm hover:bg-ink-50">
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 rounded border-ink-400 accent-worse-700"
                      checked={removed}
                      aria-label={t(`Remove ${p.meaning}`, `移除 ${procedureMeaning(p)}`)}
                      onChange={() => set({ removed_procedures: toggle(levers.removed_procedures, p.code) })}
                    />
                    <span className={`min-w-0 flex-1 ${removed ? "text-ink-500 line-through" : "text-ink-800"}`}>
                      <span className="block font-medium">{procedureMeaning(p)}</span>
                      {labelText !== p.meaning && <span className="mt-0.5 block text-xs text-ink-600">{labelText}</span>}
                    </span>
                    <span className="shrink-0 text-right text-xs text-ink-500 tabular">
                      {t(`${p.occurrences} time${p.occurrences === 1 ? "" : "s"}`, `${p.occurrences} 次`)}
                      <span className="block">{t(`at ${p.visits} visit${p.visits === 1 ? "" : "s"}`, `涉及 ${p.visits} 次访视`)}</span>
                    </span>
                  </label>
                  <ul className="ml-7 space-y-1 pb-2 text-xs text-ink-600">
                    {[...(endpointLinks.get(p.code)?.entries() ?? [])].map(([key, link]) => (
                      <li key={key}>
                        <span className="font-medium">{link.label}: {ENDPOINT_ROLES[link.role]}</span>
                        <span className="block text-ink-500">{LINK_BASES[link.basis]} {t("· Visits", "· 访视")} {link.visits.join(", ")}</span>
                        {link.note && <p>{link.note}</p>}
                        {removed && link.role === "supports_primary" && (
                          <p role="status" className="font-medium text-caution-800">{t("This procedure is tied to a primary outcome.", "此检查项目与主要结局关联。")}</p>
                        )}
                        {removed && link.role === "not_linked" && (
                          <p role="status" className="text-caution-800">{t("No primary or secondary outcome in the registry record matches this procedure.", "注册记录中没有与此检查项目匹配的主要或次要结局。")}</p>
                        )}
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ul>
        )}
      </Group>

      <Group
        title={t(`Sites (${design.sites.length - levers.excluded_site_ids.length} of ${design.sites.length} included)`, `研究中心（已纳入 ${design.sites.length - levers.excluded_site_ids.length} / ${design.sites.length}）`)}
        hint={t("Untick to exclude a site, or click its dot on the map.", "取消勾选可排除研究中心，也可点击地图上的对应圆点。")}
        changed={levers.excluded_site_ids.length > 0}
      >
        {design.sites.length > 8 && (
          <input
            type="search"
            className="input mb-2 py-1.5"
            placeholder={t("Filter sites by name, city or country", "按名称、城市或国家筛选研究中心")}
            aria-label={t("Filter sites", "筛选研究中心")}
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
          {sites.length === 0 && <li className="px-1 text-sm text-ink-500">{t("No sites match.", "没有匹配的研究中心。")}</li>}
        </ul>
      </Group>
    </div>
  );
}

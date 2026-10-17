import { useTranslation, translate as t } from "@/app/i18n";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ModuleBreakdown } from "@/app/contracts";
import type { ScenarioResultX } from "@/app/api/types";
import { formatBare, formatSignedValue, formatValue } from "@/app/format";
import { Segmented, Skeleton } from "@/app/ui";
import { isExcludedByDefault, isExtensionModule, moduleLabel } from "../metrics";

type Basis = "cost_usd" | "co2e_kg";

// Calm categorical palette; every segment is also named in the table beside the chart.
const MODULE_COLORS: Record<string, string> = {
  setup: "#64748b",
  trial_management: "#0f766e",
  meetings_travel: "#0891b2",
  intervention: "#cbd5e1",
  data_collection: "#6366f1",
  supplies_equipment: "#ca8a04",
  patient_assessments: "#2563eb",
  samples: "#db2777",
  laboratory: "#7c3aed",
  closeout: "#334155",
  drug_supply: "#ea580c",
};
const FALLBACK = ["#0d9488", "#9333ea", "#65a30d", "#e11d48"];
const colorFor = (m: string, i: number) => MODULE_COLORS[m] ?? FALLBACK[i % FALLBACK.length];

export function ModuleChart({
  baseline,
  current,
  onSelectModule,
}: {
  baseline: ScenarioResultX | null;
  current: ScenarioResultX | null;
  onSelectModule: (module: string) => void;
}) {
  useTranslation();
  const [basis, setBasis] = useState<Basis>("cost_usd");
  const unit = basis === "cost_usd" ? "usd" : "kg_co2e";

  const modules = useMemo(() => {
    const ids = new Set<string>();
    baseline?.modules.forEach((m) => ids.add(m.module));
    current?.modules.forEach((m) => ids.add(m.module));
    return [...ids];
  }, [baseline, current]);

  const rows = useMemo(() => {
    const pick = (r: { modules: ModuleBreakdown[] } | null, m: string) => r?.modules.find((x) => x.module === m)?.[basis].p50 ?? null;
    return modules.map((m) => ({ module: m, base: pick(baseline, m), cur: pick(current, m) }));
  }, [modules, baseline, current, basis]);

  const chartData = useMemo(() => {
    const toRow = (name: string, r: { modules: ModuleBreakdown[] } | null) => {
      const row: Record<string, number | string> = { name };
      r?.modules.forEach((m) => {
        const raw = basis === "co2e_kg" ? m.co2e_kg.p50 : m.cost_usd.p50;
        // Unknown stays off the axis. A missing P50 is not drawn as zero.
        if (typeof raw === "number") row[m.module] = basis === "co2e_kg" ? raw / 1000 : raw;
      });
      return row;
    };
    return [toRow("Baseline", baseline), toRow("Current", current)];
  }, [baseline, current, basis]);

  const ready = baseline && current;

  return (
    <section className="card p-4" aria-labelledby="module-chart-title" data-testid="module-chart">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 id="module-chart-title" className="card-title">
          {t("Breakdown by module (P50)", "按模块细分（P50）")}
        </h2>
        <Segmented
          label={t("Breakdown basis", "细分依据")}
          size="sm"
          value={basis}
          onChange={setBasis}
          options={[
            { value: "cost_usd", label: t("Cost", "费用") },
            { value: "co2e_kg", label: t("Carbon", "碳排放") },
          ]}
        />
      </div>
      {!ready ? (
        <Skeleton className="h-56 w-full" />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
          <div className="h-56" aria-hidden>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }} barCategoryGap={18}>
                <CartesianGrid horizontal={false} stroke="#e2e8f0" />
                <XAxis
                  type="number"
                  tick={{ fontSize: 12, fill: "#64748b" }}
                  tickFormatter={(v: number) => (basis === "co2e_kg" ? `${formatBare(v * 1000, "kg_co2e")} t` : formatBare(v, "usd"))}
                />
                <YAxis type="category" dataKey="name" tickFormatter={(name: string) => name === "Baseline" ? t("Baseline", "基线") : name === "Current" ? t("Current", "当前") : name} width={70} tick={{ fontSize: 13, fill: "#334155", fontWeight: 600 }} />
                <Tooltip
                  cursor={{ fill: "rgba(15,118,110,0.06)" }}
                  labelFormatter={(name: string) => name === "Baseline" ? t("Baseline", "基线") : name === "Current" ? t("Current", "当前") : name}
                  formatter={(v: number, name: string) => [
                    basis === "co2e_kg" ? formatValue(v * 1000, "kg_co2e") : formatValue(v, "usd"),
                    moduleLabel(name),
                  ]}
                />
                {modules.map((m, i) => (
                  <Bar
                    key={m}
                    dataKey={m}
                    stackId="modules"
                    fill={colorFor(m, i)}
                    cursor="pointer"
                    onClick={() => onSelectModule(m)}
                    isAnimationActive={false}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
          <table className="w-full text-sm" data-testid="module-table">
            <caption className="sr-only">{t("Module breakdown, baseline versus current, P50", "模块细分：基线与当前值对比，P50")}</caption>
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
                <th scope="col" className="pb-1 font-semibold">{t("Module", "模块")}</th>
                <th scope="col" className="pb-1 text-right font-semibold">{t("Current", "当前")}</th>
                <th scope="col" className="pb-1 text-right font-semibold">{t("Δ vs baseline", "相对基线变化")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const d = r.cur !== null && r.base !== null ? r.cur - r.base : null;
                return (
                  <tr key={r.module} className="border-t border-ink-100">
                    <th scope="row" className="py-1 pr-2 text-left font-normal">
                      <button type="button" className="num-button flex items-center gap-2 px-1 py-0.5" onClick={() => onSelectModule(r.module)}>
                        <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: colorFor(r.module, i) }} aria-hidden />
                        <span className="text-ink-800">{moduleLabel(r.module)}</span>
                        {isExtensionModule(r.module) && <span className="chip border-ink-300 bg-ink-50 text-ink-600" title={t("Extension beyond the published LCCTG method", "已发表 LCCTG 方法之外的扩展")}>{t("ext.", "扩展")}</span>}
                        {isExcludedByDefault(r.module) && <span className="chip border-ink-300 bg-ink-50 text-ink-600" title={t("Excluded from totals by default", "默认不计入总量")}>{t("excl.", "排除")}</span>}
                      </button>
                    </th>
                    <td className="whitespace-nowrap py-1 pl-2 text-right tabular text-ink-800">{r.cur !== null ? formatValue(r.cur, unit) : "—"}</td>
                    <td className={`whitespace-nowrap py-1 pl-2 text-right tabular ${d === null || Math.abs(d) < 1e-9 ? "text-ink-500" : d < 0 ? "text-better-700" : "text-worse-700"}`}>
                      {d === null ? "—" : Math.abs(d) < 1e-9 ? t("no change", "无变化") : `${d < 0 ? "▼" : "▲"} ${formatSignedValue(d, unit)}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

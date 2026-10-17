import type { MetricRange, ModuleBreakdown, ProvenanceItem } from "@/app/contracts";
import { EXTENSION_MODULES, EXCLUDED_BY_DEFAULT_MODULES } from "@/app/contracts";
import { humanize } from "@/app/format";
import { translate } from "@/app/i18n";

export type MetricKey = "cost_usd" | "site_staff_hours" | "patient_travel_hours" | "duration_months" | "co2e_kg";

export interface MetricDef {
  key: MetricKey;
  label: string;
  description: string;
  /** formula_id prefixes (A2/A3) whose provenance explains this metric */
  formulaPrefixes: string[];
}

/** The five hero metrics, in the order Regeneron cares about (§1): cost, workload, burden, timeline, carbon. */
export const METRICS: MetricDef[] = [
  { key: "cost_usd", label: "Cost", description: "Trial-specific cost in USD", formulaPrefixes: ["cost."] },
  { key: "site_staff_hours", label: "Site staff time", description: "Hours of site staff effort", formulaPrefixes: ["workload.", "staff.", "site_time."] },
  { key: "patient_travel_hours", label: "Patient travel time", description: "Hours patients spend travelling to visits", formulaPrefixes: ["burden.", "patient.", "travel_time."] },
  { key: "duration_months", label: "Duration", description: "Months from start to database lock (forecast)", formulaPrefixes: ["forecast.", "duration."] },
  { key: "co2e_kg", label: "Carbon", description: "Greenhouse gas emissions, kg CO₂e (shown in tonnes)", formulaPrefixes: ["carbon."] },
];

export const METRIC_BY_KEY = Object.fromEntries(METRICS.map((m) => [m.key, m])) as Record<MetricKey, MetricDef>;

const METRIC_ZH: Record<MetricKey, { label: string; description: string }> = {
  cost_usd: { label: "成本", description: "试验专属成本（美元）" },
  site_staff_hours: { label: "研究中心人力", description: "研究中心工作人员投入的小时数" },
  patient_travel_hours: { label: "患者出行时间", description: "患者往返访视所需的小时数" },
  duration_months: { label: "持续时间", description: "从开始到数据库锁定的月数（预测）" },
  co2e_kg: { label: "碳排放", description: "温室气体排放量，千克 CO₂e（以吨显示）" },
};

export function metricLabel(key: MetricKey): string {
  return translate(METRIC_BY_KEY[key].label, METRIC_ZH[key].label);
}

export function metricDescription(key: MetricKey): string {
  return translate(METRIC_BY_KEY[key].description, METRIC_ZH[key].description);
}

/**
 * §2 rule 2: unknown ≠ zero. The engine reports a metric it cannot compute (missing input) as
 * NaN, which arrives as null (or a string) in JSON; such a range is shown as "Unknown".
 */
export type KnownRange = MetricRange & { p10: number; p50: number; p90: number };

export function isKnownRange(r: MetricRange | null | undefined): r is KnownRange {
  return !!r && [r.p10, r.p50, r.p90].every((v) => typeof v === "number" && Number.isFinite(v));
}

export interface Delta {
  abs: number;
  pct: number;
  /** lower is better for every hero metric */
  direction: "lower" | "higher" | "same";
}

/** Change of P50 vs baseline. |pct| < 0.5 % counts as "same" (below display precision). */
export function delta(current: KnownRange, baseline: KnownRange): Delta {
  const abs = current.p50 - baseline.p50;
  const pct = baseline.p50 !== 0 ? (abs / Math.abs(baseline.p50)) * 100 : abs === 0 ? 0 : Number.POSITIVE_INFINITY;
  const direction = Math.abs(pct) < 0.5 ? "same" : abs < 0 ? "lower" : "higher";
  return { abs, pct, direction };
}

type ProvenanceSource = { modules: ModuleBreakdown[]; forecast?: { provenance: ProvenanceItem[] } | null; supply?: { provenance: ProvenanceItem[] } | null };

export function allProvenance(result: ProvenanceSource): Array<ProvenanceItem & { module: string }> {
  return [
    ...result.modules.flatMap((m) => m.provenance.map((p) => ({ ...p, module: m.module }))),
    ...(result.forecast?.provenance ?? []).map((p) => ({ ...p, module: "forecast" })),
    ...(result.supply?.provenance ?? []).map((p) => ({ ...p, module: "drug_supply" })),
  ];
}

/** Provenance items that explain a metric; falls back to every item when no prefix matches. */
export function provenanceForMetric(result: ProvenanceSource, key: MetricKey): { items: Array<ProvenanceItem & { module: string }>; matched: boolean } {
  const all = allProvenance(result);
  if (key === "duration_months" && result.forecast?.provenance.length) return { items: all.filter((p) => p.module === "forecast"), matched: true };
  const prefixes = METRIC_BY_KEY[key].formulaPrefixes;
  const items = all.filter((p) => prefixes.some((pre) => p.formula_id.startsWith(pre)));
  return items.length ? { items, matched: true } : { items: all, matched: false };
}

export const isExtensionModule = (m: string) => (EXTENSION_MODULES as readonly string[]).includes(m);
export const isExcludedByDefault = (m: string) => (EXCLUDED_BY_DEFAULT_MODULES as readonly string[]).includes(m);

const MODULE_LABELS: Record<string, string> = {
  setup: "Setup",
  trial_management: "Trial management",
  meetings_travel: "Meetings & monitoring travel",
  intervention: "Intervention",
  data_collection: "Data collection",
  supplies_equipment: "Supplies & equipment",
  patient_assessments: "Patient assessments & travel",
  samples: "Samples (shipping & storage)",
  laboratory: "Laboratory",
  closeout: "Closeout",
  drug_supply: "Drug supply (extension)",
};

export function moduleLabel(m: string): string {
  const chinese: Record<string, string> = {
    setup: "启动", trial_management: "试验管理", meetings_travel: "会议与监查差旅",
    intervention: "干预", data_collection: "数据采集", supplies_equipment: "耗材与设备",
    patient_assessments: "患者评估与出行", samples: "样本（运输与存储）", laboratory: "实验室",
    closeout: "收尾", drug_supply: "药物供应（扩展）", forecast: "预测",
  };
  return translate(MODULE_LABELS[m] ?? humanize(m), chinese[m] ?? humanize(m));
}

export function findModule(result: { modules: ModuleBreakdown[] }, module: string): ModuleBreakdown | undefined {
  return result.modules.find((m) => m.module === module);
}

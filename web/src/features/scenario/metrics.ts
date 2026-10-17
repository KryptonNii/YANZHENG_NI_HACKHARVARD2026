import type { MetricRange, ModuleBreakdown, ProvenanceItem, ScenarioResult } from "@/app/contracts";
import { EXTENSION_MODULES, EXCLUDED_BY_DEFAULT_MODULES } from "@/app/contracts";
import { humanize } from "@/app/format";

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

/**
 * §2 rule 2: unknown ≠ zero. The engine reports a metric it cannot compute (missing input) as
 * NaN, which arrives as null (or a string) in JSON; such a range is shown as "Unknown".
 */
export function isKnownRange(r: MetricRange | null | undefined): r is MetricRange {
  return !!r && [r.p10, r.p50, r.p90].every((v) => typeof v === "number" && Number.isFinite(v));
}

export interface Delta {
  abs: number;
  pct: number;
  /** lower is better for every hero metric */
  direction: "lower" | "higher" | "same";
}

/** Change of P50 vs baseline. |pct| < 0.5 % counts as "same" (below display precision). */
export function delta(current: MetricRange, baseline: MetricRange): Delta {
  const abs = current.p50 - baseline.p50;
  const pct = baseline.p50 !== 0 ? (abs / Math.abs(baseline.p50)) * 100 : abs === 0 ? 0 : Number.POSITIVE_INFINITY;
  const direction = Math.abs(pct) < 0.5 ? "same" : abs < 0 ? "lower" : "higher";
  return { abs, pct, direction };
}

export function allProvenance(result: ScenarioResult): Array<ProvenanceItem & { module: string }> {
  return result.modules.flatMap((m) => m.provenance.map((p) => ({ ...p, module: m.module })));
}

/** Provenance items that explain a metric; falls back to every item when no prefix matches. */
export function provenanceForMetric(result: ScenarioResult, key: MetricKey): { items: Array<ProvenanceItem & { module: string }>; matched: boolean } {
  const all = allProvenance(result);
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
  return MODULE_LABELS[m] ?? humanize(m);
}

export function findModule(result: ScenarioResult, module: string): ModuleBreakdown | undefined {
  return result.modules.find((m) => m.module === module);
}

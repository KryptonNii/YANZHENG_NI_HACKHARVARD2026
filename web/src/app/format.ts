import type { MetricRange, MetricRangeUnit } from "./contracts";

/** §2 rule 2: a missing value (NaN/null from the engine) is printed as "unknown", never 0. */
export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);

const nf = (digits: number) => new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });

/** Significant-ish rounding for display: 3 significant figures, no trailing noise. */
function compact(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e9) return `${nf(a >= 1e10 ? 1 : 2).format(v / 1e9)}B`;
  if (a >= 1e6) return `${nf(a >= 1e7 ? 1 : 2).format(v / 1e6)}M`;
  if (a >= 1e4) return `${nf(a >= 1e5 ? 0 : 1).format(v / 1e3)}k`;
  if (a >= 100) return nf(0).format(v);
  if (a >= 10) return nf(1).format(v);
  return nf(2).format(v);
}

export function formatUsd(v: number): string {
  if (!isNum(v)) return "unknown";
  return `${v < 0 ? "−" : ""}$${compact(Math.abs(v))}`;
}

export function formatHours(v: number): string {
  return `${v < 0 ? "−" : ""}${compact(Math.abs(v))} h`;
}

/** Carbon is kg CO2e internally (§3); show tonnes from 1,000 kg. */
export function formatCo2e(kg: number): string {
  const sign = kg < 0 ? "−" : "";
  const a = Math.abs(kg);
  if (a >= 1000) return `${sign}${compact(a / 1000)} t CO₂e`;
  return `${sign}${compact(a)} kg CO₂e`;
}

export function formatMonths(v: number): string {
  return `${v < 0 ? "−" : ""}${nf(1).format(Math.abs(v))} mo`;
}

/** `percent` metrics are 0–100 (e.g. drug_waste_share 23.5 = 23.5 %). */
export function formatPercent(v: number | null): string {
  if (!isNum(v)) return "unknown";
  return `${v < 0 ? "−" : ""}${nf(Math.abs(v) >= 10 ? 0 : 1).format(Math.abs(v))}%`;
}

export function formatValue(v: number | null, unit: MetricRangeUnit | string): string {
  if (!isNum(v)) return "unknown";
  switch (unit) {
    case "usd":
      return formatUsd(v);
    case "hours":
      return formatHours(v);
    case "kg_co2e":
      return formatCo2e(v);
    case "months":
      return formatMonths(v);
    case "percent":
      return formatPercent(v);
    case "patients":
      return `${compact(v)} patients`;
    case "kits":
      return `${compact(v)} kits`;
    case "count":
      return compact(v);
    default:
      return `${compact(v)} ${unit}`;
  }
}

/** Big-number display: the figure and its unit separately, so the unit can be set smaller. */
export function splitValue(v: number | null, unit: MetricRangeUnit | string): { num: string; unit: string } {
  if (!isNum(v)) return { num: "unknown", unit: "" };
  switch (unit) {
    case "usd":
      return { num: formatUsd(v), unit: "" };
    case "hours":
      return { num: `${v < 0 ? "−" : ""}${compact(Math.abs(v))}`, unit: "h" };
    case "kg_co2e": {
      const a = Math.abs(v);
      const sign = v < 0 ? "−" : "";
      return a >= 1000 ? { num: `${sign}${compact(a / 1000)}`, unit: "t CO₂e" } : { num: `${sign}${compact(a)}`, unit: "kg CO₂e" };
    }
    case "months":
      return { num: `${v < 0 ? "−" : ""}${nf(1).format(Math.abs(v))}`, unit: "months" };
    case "percent":
      return { num: formatPercent(v), unit: "" };
    default:
      return { num: compact(v), unit: String(unit) };
  }
}

/** Number without unit suffix, for compact range text ("1.2M – 1.9M"). */
export function formatBare(v: number | null, unit: MetricRangeUnit | string): string {
  if (!isNum(v)) return "unknown";
  if (unit === "usd") return formatUsd(v);
  if (unit === "kg_co2e") return Math.abs(v) >= 1000 ? compact(v / 1000) : compact(v);
  if (unit === "months") return nf(1).format(v);
  if (unit === "percent") return formatPercent(v);
  return compact(v);
}

export function formatRange(r: MetricRange): string {
  if (!isNum(r.p10) || !isNum(r.p90)) return "unknown";
  // Carbon: pick the unit from the P90 so both ends share it.
  if (r.unit === "kg_co2e") {
    const tonnes = Math.abs(r.p90) >= 1000;
    const f = (x: number) => (tonnes ? compact(x / 1000) : compact(x));
    return `${f(r.p10)} – ${f(r.p90)} ${tonnes ? "t CO₂e" : "kg CO₂e"}`;
  }
  return `${formatValue(r.p10, r.unit)} – ${formatValue(r.p90, r.unit)}`;
}

export function formatSignedPct(p: number): string {
  if (!Number.isFinite(p)) return "n/a";
  const rounded = Math.abs(p) < 10 ? Math.round(p * 10) / 10 : Math.round(p);
  if (rounded === 0) return "0%";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded)}%`;
}

export function formatSignedValue(v: number, unit: MetricRangeUnit | string): string {
  if (!isNum(v)) return "unknown";
  if (unit === "percent") {
    // a difference of two percentages is in percentage points
    const pp = Math.abs(v) >= 10 ? Math.round(Math.abs(v)) : Math.round(Math.abs(v) * 10) / 10;
    return pp === 0 ? "0 pp" : `${v > 0 ? "+" : "−"}${pp} pp`;
  }
  if (v === 0) return formatValue(0, unit);
  const body = formatValue(Math.abs(v), unit);
  return `${v > 0 ? "+" : "−"}${body}`;
}

export function formatUtc(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

export function humanize(id: string): string {
  const s = id.replace(/[_.]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

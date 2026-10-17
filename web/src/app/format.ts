import type { MetricRange, MetricRangeUnit } from "./contracts";
import { translate as t } from "./i18n";

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
  if (!isNum(v)) return t("unknown", "未知");
  return `${v < 0 ? "−" : ""}$${compact(Math.abs(v))}`;
}

export function formatHours(v: number): string {
  return `${v < 0 ? "−" : ""}${compact(Math.abs(v))} ${t("h", "小时")}`;
}

/** Carbon is kg CO2e internally (§3); show tonnes from 1,000 kg. */
export function formatCo2e(kg: number): string {
  const sign = kg < 0 ? "−" : "";
  const a = Math.abs(kg);
  if (a >= 1000) return `${sign}${compact(a / 1000)} t CO₂e`;
  return `${sign}${compact(a)} kg CO₂e`;
}

export function formatMonths(v: number): string {
  return `${v < 0 ? "−" : ""}${nf(1).format(Math.abs(v))} ${t("mo", "个月")}`;
}

/** `percent` metrics are 0–100 (e.g. drug_waste_share 23.5 = 23.5 %). */
export function formatPercent(v: number | null): string {
  if (!isNum(v)) return t("unknown", "未知");
  return `${v < 0 ? "−" : ""}${nf(Math.abs(v) >= 10 ? 0 : 1).format(Math.abs(v))}%`;
}

export function formatValue(v: number | null, unit: MetricRangeUnit | string): string {
  if (!isNum(v)) return t("unknown", "未知");
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
      return `${compact(v)} ${t("patients", "名患者")}`;
    case "kits":
      return `${compact(v)} ${t("kits", "套试剂盒")}`;
    case "count":
      return compact(v);
    default:
      return `${compact(v)} ${unit}`;
  }
}

/** Big-number display: the figure and its unit separately, so the unit can be set smaller. */
export function splitValue(v: number | null, unit: MetricRangeUnit | string): { num: string; unit: string } {
  if (!isNum(v)) return { num: t("unknown", "未知"), unit: "" };
  switch (unit) {
    case "usd":
      return { num: formatUsd(v), unit: "" };
    case "hours":
      return { num: `${v < 0 ? "−" : ""}${compact(Math.abs(v))}`, unit: t("h", "小时") };
    case "kg_co2e": {
      const a = Math.abs(v);
      const sign = v < 0 ? "−" : "";
      return a >= 1000 ? { num: `${sign}${compact(a / 1000)}`, unit: "t CO₂e" } : { num: `${sign}${compact(a)}`, unit: "kg CO₂e" };
    }
    case "months":
      return { num: `${v < 0 ? "−" : ""}${nf(1).format(Math.abs(v))}`, unit: t("months", "个月") };
    case "percent":
      return { num: formatPercent(v), unit: "" };
    default:
      return { num: compact(v), unit: String(unit) };
  }
}

/** Number without unit suffix, for compact range text ("1.2M – 1.9M"). */
export function formatBare(v: number | null, unit: MetricRangeUnit | string): string {
  if (!isNum(v)) return t("unknown", "未知");
  if (unit === "usd") return formatUsd(v);
  if (unit === "kg_co2e") return Math.abs(v) >= 1000 ? compact(v / 1000) : compact(v);
  if (unit === "months") return nf(1).format(v);
  if (unit === "percent") return formatPercent(v);
  return compact(v);
}

export function formatRange(r: MetricRange): string {
  if (!isNum(r.p10) || !isNum(r.p90)) return t("unknown", "未知");
  // Carbon: pick the unit from the P90 so both ends share it.
  if (r.unit === "kg_co2e") {
    const tonnes = Math.abs(r.p90) >= 1000;
    const f = (x: number) => (tonnes ? compact(x / 1000) : compact(x));
    return `${f(r.p10)} – ${f(r.p90)} ${tonnes ? "t CO₂e" : "kg CO₂e"}`;
  }
  return `${formatValue(r.p10, r.unit)} – ${formatValue(r.p90, r.unit)}`;
}

export function formatSignedPct(p: number): string {
  if (!Number.isFinite(p)) return t("n/a", "不适用");
  const rounded = Math.abs(p) < 10 ? Math.round(p * 10) / 10 : Math.round(p);
  if (rounded === 0) return "0%";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded)}%`;
}

export function formatSignedValue(v: number, unit: MetricRangeUnit | string): string {
  if (!isNum(v)) return t("unknown", "未知");
  if (unit === "percent") {
    // a difference of two percentages is in percentage points
    const pp = Math.abs(v) >= 10 ? Math.round(Math.abs(v)) : Math.round(Math.abs(v) * 10) / 10;
    return pp === 0 ? `0 ${t("pp", "个百分点")}` : `${v > 0 ? "+" : "−"}${pp} ${t("pp", "个百分点")}`;
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
  const english = s.charAt(0).toUpperCase() + s.slice(1);
  return t(english, FIELD_LABELS[id.toLowerCase()] ?? english);
}

const FIELD_LABELS: Record<string, string> = {
  biologic: "生物制品", small_molecule: "小分子药物", device: "医疗器械", none: "无", unknown: "未知",
  enrollment_target: "目标入组人数", duration_months: "持续时间（月）", drug_type: "药物类型", phase: "试验分期",
  countries: "国家", sites: "研究中心", visits: "访视", procedures: "检查项目", conditions: "疾病", arms: "试验组",
  intervention: "干预措施", interventions: "干预措施", allocation: "分配方式", masking: "盲法", primary_purpose: "主要目的",
  study_type: "研究类型", intervention_model: "干预模型", start_date: "开始日期", completion_date: "完成日期",
  primary_completion_date: "主要终点完成日期", eligibility: "入选条件", sex: "性别", minimum_age: "最低年龄", maximum_age: "最高年龄",
  recruiting: "招募中", not_yet_recruiting: "尚未开始招募", active_not_recruiting: "进行中，停止招募", completed: "已完成",
  terminated: "已终止", suspended: "已暂停", withdrawn: "已撤回", enrolling_by_invitation: "邀请入组", available: "可用",
  first_patient_in: "首例患者入组", last_patient_in: "末例患者入组", last_patient_out: "末例患者完成", database_lock: "数据库锁定",
};

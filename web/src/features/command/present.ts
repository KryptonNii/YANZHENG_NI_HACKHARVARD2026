import { translate as t } from "@/app/i18n";
import { displayText } from "./displayText";
import { formatRange, formatUsd, formatValue, isNum } from "@/app/format";
import type { MetricRange } from "@/app/contracts";
import type { Tone } from "./tones";
import type { Band, StudySnapshot, UiKpi } from "./api";

export const IMPACT_KEYS = ["cost_usd", "co2e_kg", "delay_days", "site_staff_hours"] as const;

export const IMPACT_LABEL: Record<(typeof IMPACT_KEYS)[number], string> = {
  cost_usd: "Cost",
  co2e_kg: "Carbon",
  delay_days: "Delay",
  site_staff_hours: "Site hours",
};

const STATUS_LABEL: Record<string, string> = {
  on_track: "On track",
  watch: "Watch",
  at_risk: "At risk",
  off_track: "At risk",
  unknown: "Unknown",
};

export function statusTone(status: string | undefined): Tone {
  if (status === "on_track" || status === "active") return "better";
  if (status === "watch" || status === "stalled") return "caution";
  if (status === "at_risk" || status === "off_track" || status === "never_enrolled") return "worse";
  return "neutral";
}

export function statusLabel(status: string | undefined): string {
  if (!status) return t("Unknown", "未知");
  return displayText(STATUS_LABEL[status] ?? status.replaceAll("_", " "));
}

export function siteStatusLabel(status: string): string {
  if (status === "never_enrolled") return t("Never enrolled", "从未入组");
  if (status === "not_started") return t("Not started", "尚未开始");
  if (status === "active") return t("Active", "活跃");
  if (status === "stalled") return t("Stalled", "停滞");
  return displayText(status.replaceAll("_", " "));
}

export function rangeText(range: { p10?: number | null; p50?: number | null; p90?: number | null; unit?: string } | null | undefined): string {
  if (!range || !isNum(range.p10) || !isNum(range.p50) || !isNum(range.p90) || !range.unit) return t("Unknown", "未知");
  return formatRange(range as MetricRange);
}

/** Alert impact keeps the unit on the range (delay arrives as months). A missing or unknown range is not an estimate. */
export function impactText(range: { p10?: number | null; p50?: number | null; p90?: number | null; unit?: string } | null | undefined): string {
  if (!range || !isNum(range.p10) || !isNum(range.p50) || !isNum(range.p90) || !range.unit) return t("not estimated", "未估计");
  return formatRange(range as MetricRange);
}

export function bandText(band: Band | null | undefined): string {
  if (!band) return t("Unknown", "未知");
  return rangeText({ ...band, unit: band.unit ?? "patients" });
}

function figure(kpi: UiKpi): string {
  if (kpi.value_text) return displayText(kpi.value_text);
  if (!isNum(kpi.value)) return t("Unknown", "未知");
  if (kpi.unit === "usd") return formatUsd(kpi.value);
  if (kpi.unit === "kg_co2e" || kpi.unit === "hours" || kpi.unit === "percent" || kpi.unit === "patients" || kpi.unit === "kits" || kpi.unit === "months") {
    return formatValue(kpi.value, kpi.unit);
  }
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(kpi.value)}${kpi.unit ? ` ${displayText(kpi.unit)}` : ""}`;
}

/** What the tile shows under the headline: plan band, median age, site mix, database-lock slip. */
export function kpiCaption(kpi: UiKpi, study: StudySnapshot): string | null {
  if (kpi.id === "open_queries") {
    const age = study.open_queries?.median_age_days;
    return age == null ? t("Median age unknown", "中位持续时间未知") : t(`Median age ${age} days`, `中位持续时间 ${age} 天`);
  }
  if (kpi.id === "sites_status") {
    const v = study.sites_status?.value;
    if (!v) return null;
    const never = v.never_enrolled ?? 0;
    return t(`${v.active ?? 0} active · ${v.stalled ?? 0} stalled · ${never} never enrolled`, `${v.active ?? 0} 个活跃 · ${v.stalled ?? 0} 个停滞 · ${never} 个从未入组`);
  }
  if (kpi.id === "milestones") {
    const db = study.milestones?.db_lock;
    if (!db) return null;
    const slip = db.slip_days_p50;
    const slipText = slip == null ? t("slip unknown", "延迟未知") : t(`P50 slip ${slip > 0 ? "+" : ""}${slip} days`, `P50 延迟 ${slip > 0 ? "+" : ""}${slip} 天`);
    return t(`Target ${db.target ?? "unknown"} · ${slipText}`, `目标 ${db.target ?? "未知"} · ${slipText}`);
  }
  if (kpi.id === "drug_supply") {
    const d = study.drug_supply;
    if (!d) return null;
    const transit = d.kits_in_transit;
    return transit == null ? null : t(`${Math.round(transit)} kits in transit`, `${Math.round(transit)} 盒药物在途`);
  }
  if (kpi.id === "enrollment" && study.enrollment?.target != null) {
    return t(`Target ${study.enrollment.target.toLocaleString("en-US")} · plan ${bandText(kpi.plan)}`, `目标 ${study.enrollment.target.toLocaleString("zh-CN")} · 计划 ${bandText(kpi.plan)}`);
  }
  if (kpi.plan) return t(`Plan ${bandText(kpi.plan)}`, `计划 ${bandText(kpi.plan)}`);
  return null;
}

export function displayStatus(kpi: UiKpi, study: StudySnapshot): string {
  if (kpi.id === "milestones") {
    const lock = study.milestones?.db_lock?.status;
    if (lock === "off_track") return "at_risk";
    if (lock === "watch" || lock === "on_track") return lock;
  }
  if (kpi.id === "sites_status") {
    const counts = study.sites_status?.value;
    if (counts) {
      if ((counts.never_enrolled ?? 0) > 0 || (counts.stalled ?? 0) > 0) return "watch";
      return "on_track";
    }
  }
  return kpi.status || "unknown";
}

export function kpiHeadline(kpi: UiKpi, study: StudySnapshot): string {
  if (kpi.id === "milestones") return study.milestones?.db_lock?.p50 ?? (kpi.value_text ? displayText(kpi.value_text) : t("Unknown", "未知"));
  return figure(kpi);
}

export const VERDICT: Record<string, { label: string; tone: Tone }> = {
  likely_worked: { label: "Likely worked", tone: "better" },
  inconclusive: { label: "Inconclusive", tone: "caution" },
  likely_coincidence: { label: "Likely coincidence", tone: "worse" },
  no_effect: { label: "No effect", tone: "neutral" },
};

export const SOURCE_LABEL: Record<string, string> = {
  EDC: "EDC",
  CTMS: "CTMS",
  IRT: "IRT",
  TRAVEL: "Travel",
  COURIER: "Courier",
  FINANCE: "Finance",
  VENDOR: "Vendor",
};

const RECONCILE: Record<string, { en: string; zh: string; tone: Tone }> = {
  exceeded: { en: "Better than predicted", zh: "好于预测", tone: "better" },
  met: { en: "As predicted", zh: "符合预测", tone: "better" },
  partial: { en: "Partly as predicted", zh: "部分达到预测", tone: "caution" },
  not_met: { en: "Below prediction", zh: "未达到预测", tone: "worse" },
  inconclusive: { en: "Cannot tell yet", zh: "暂无法判断", tone: "neutral" },
  insufficient_data: { en: "Not enough data yet", zh: "数据尚不足", tone: "neutral" },
};

export function reconcileLabel(verdict: string): string {
  const row = RECONCILE[verdict];
  return row ? t(row.en, row.zh) : verdict.replaceAll("_", " ");
}

export function reconcileTone(verdict: string): Tone {
  return RECONCILE[verdict]?.tone ?? "neutral";
}

type PredictedLike = { p10?: number | null; p50?: number | null; p90?: number | null; unit?: string } | null | undefined;

/** "6.4 days (5.9 – 6.5)". Days are a prediction unit of their own; everything else goes through formatRange. */
export function predictedText(range: PredictedLike): string {
  if (!range || !isNum(range.p10) || !isNum(range.p50) || !isNum(range.p90) || !range.unit) return "—";
  const one = (x: number) => (Math.abs(x) >= 10 ? Math.round(x) : Math.round(x * 10) / 10).toString();
  if (range.unit === "days") return `${one(range.p50)} ${t("d", "天")} (${one(range.p10)} – ${one(range.p90)})`;
  const median = formatValue(range.p50, range.unit);
  return `${median} (${formatRange(range as MetricRange)})`;
}

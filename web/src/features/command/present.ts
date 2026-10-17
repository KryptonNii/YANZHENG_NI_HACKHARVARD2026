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
  if (!status) return "Unknown";
  return STATUS_LABEL[status] ?? status.replaceAll("_", " ");
}

export function siteStatusLabel(status: string): string {
  if (status === "never_enrolled") return "Never enrolled";
  if (status === "not_started") return "Not started";
  if (status === "active") return "Active";
  if (status === "stalled") return "Stalled";
  return status.replaceAll("_", " ");
}

export function rangeText(range: { p10?: number | null; p50?: number | null; p90?: number | null; unit?: string } | null | undefined): string {
  if (!range || !isNum(range.p10) || !isNum(range.p50) || !isNum(range.p90) || !range.unit) return "Unknown";
  return formatRange(range as MetricRange);
}

/** Alert impact keeps the unit on the range (delay arrives as months). A missing or unknown range is not an estimate. */
export function impactText(range: { p10?: number | null; p50?: number | null; p90?: number | null; unit?: string } | null | undefined): string {
  if (!range || !isNum(range.p10) || !isNum(range.p50) || !isNum(range.p90) || !range.unit) return "not estimated";
  return formatRange(range as MetricRange);
}

export function bandText(band: Band | null | undefined): string {
  if (!band) return "Unknown";
  return rangeText({ ...band, unit: band.unit ?? "patients" });
}

function figure(kpi: UiKpi): string {
  if (kpi.value_text) return kpi.value_text;
  if (!isNum(kpi.value)) return "Unknown";
  if (kpi.unit === "usd") return formatUsd(kpi.value);
  if (kpi.unit === "kg_co2e" || kpi.unit === "hours" || kpi.unit === "percent" || kpi.unit === "patients" || kpi.unit === "kits" || kpi.unit === "months") {
    return formatValue(kpi.value, kpi.unit);
  }
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(kpi.value)}${kpi.unit ? ` ${kpi.unit}` : ""}`;
}

/** What the tile shows under the headline: plan band, median age, site mix, database-lock slip. */
export function kpiCaption(kpi: UiKpi, study: StudySnapshot): string | null {
  if (kpi.id === "open_queries") {
    const age = study.open_queries?.median_age_days;
    return age == null ? "Median age unknown" : `Median age ${age} days`;
  }
  if (kpi.id === "sites_status") {
    const v = study.sites_status?.value;
    if (!v) return null;
    const never = v.never_enrolled ?? 0;
    return `${v.active ?? 0} active · ${v.stalled ?? 0} stalled · ${never} never enrolled`;
  }
  if (kpi.id === "milestones") {
    const db = study.milestones?.db_lock;
    if (!db) return null;
    const slip = db.slip_days_p50;
    const slipText = slip == null ? "slip unknown" : `P50 slip ${slip > 0 ? "+" : ""}${slip} days`;
    return `Target ${db.target ?? "unknown"} · ${slipText}`;
  }
  if (kpi.id === "drug_supply") {
    const d = study.drug_supply;
    if (!d) return null;
    const transit = d.kits_in_transit;
    return transit == null ? null : `${Math.round(transit)} kits in transit`;
  }
  if (kpi.id === "enrollment" && study.enrollment?.target != null) {
    return `Target ${study.enrollment.target.toLocaleString("en-US")} · plan ${bandText(kpi.plan)}`;
  }
  if (kpi.plan) return `Plan ${bandText(kpi.plan)}`;
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
  if (kpi.id === "milestones") return study.milestones?.db_lock?.p50 ?? kpi.value_text ?? "Unknown";
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

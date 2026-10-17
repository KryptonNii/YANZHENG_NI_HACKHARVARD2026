/**
 * One-click demo trials on the import page. They are the registry records A4 fetched from
 * ClinicalTrials.gov and cached (GET /api/import/ctgov, data/fixtures/ctgov/, see handoffs/A4.md),
 * so they import offline — never ids typed from memory. Without a cache the page shows recent
 * designs from GET /api/designs instead.
 */
import { translate } from "@/app/i18n";

export interface DemoTrial {
  registryId: string;
  label: string;
  note?: string;
}

/** ClinicalTrials.gov ids are "NCT" + 8 digits. */
export const NCT_PATTERN = /^NCT\d{8}$/;

export function normalizeNct(input: string): string {
  return input.trim().toUpperCase().replace(/\s+/g, "");
}

export function nctError(input: string): string | null {
  const v = normalizeNct(input);
  if (!v) return translate("Enter a ClinicalTrials.gov ID.", "请输入 ClinicalTrials.gov 注册编号。");
  if (!v.startsWith("NCT")) return translate("ClinicalTrials.gov IDs start with “NCT”, e.g. NCT01234567.", "ClinicalTrials.gov 注册编号以“NCT”开头，例如 NCT01234567。");
  if (!NCT_PATTERN.test(v)) return translate("Use NCT followed by exactly 8 digits, e.g. NCT01234567.", "请使用 NCT 后接 8 位数字的格式，例如 NCT01234567。");
  return null;
}

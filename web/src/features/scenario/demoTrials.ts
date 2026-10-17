/**
 * One-click demo trials on the import page. Only registry ids that A4 verified by fetching them
 * from ClinicalTrials.gov and saved as fixtures (data/fixtures/ctgov/, see handoffs/A4.md) belong
 * here — never ids typed from memory. Until A4 publishes them the page shows recent designs from
 * GET /api/designs instead.
 */
export interface DemoTrial {
  registryId: string;
  label: string;
  note?: string;
}

export const DEMO_TRIALS: DemoTrial[] = [];

/** ClinicalTrials.gov ids are "NCT" + 8 digits. */
export const NCT_PATTERN = /^NCT\d{8}$/;

export function normalizeNct(input: string): string {
  return input.trim().toUpperCase().replace(/\s+/g, "");
}

export function nctError(input: string): string | null {
  const v = normalizeNct(input);
  if (!v) return "Enter a ClinicalTrials.gov ID.";
  if (!v.startsWith("NCT")) return "ClinicalTrials.gov IDs start with “NCT”, e.g. NCT01234567.";
  if (!NCT_PATTERN.test(v)) return "Use NCT followed by exactly 8 digits, e.g. NCT01234567.";
  return null;
}

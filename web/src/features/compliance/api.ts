import { ApiError, request } from "@/app/api/client";
import type { AuditEntry } from "@/app/contracts";

export { ApiError };

export interface AuditPageData {
  items: AuditEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface ChainResult {
  ok: boolean;
  first_bad_seq: number | null;
  checked: number;
  head_hash?: string | null;
  problem?: string | null;
}

export interface TraceTest {
  id: string;
  kind?: string;
  outcome?: string;
}

export interface TraceRow {
  id: string;
  text: string;
  risk?: string;
  gxp?: boolean;
  result: string;
  tests: TraceTest[];
  evidence: { file?: string; sha256?: string }[];
}

export interface PackageDeliverable {
  id: string;
  title: string;
  status: string;
  draft_stamp?: boolean | string | null;
  html?: string | null;
  md?: string | null;
  sha256?: string | null;
  approval?: { approved?: boolean; status?: string; reason?: string | null } | null;
}

export interface EvidenceFile { path: string; sha256?: string; bytes?: number }
export interface EvidenceManifest { files: EvidenceFile[] }

export interface DefectRow {
  id: string;
  detected?: boolean;
  stages?: string[];
  type?: string;
}

export interface ValidationPackage {
  generated_at?: string | null;
  draft_stamp?: string | null;
  system?: string;
  git?: { commit?: string; dirty?: boolean };
  execution?: {
    run_id?: string; evidence_dir?: string; executor_name?: string; finished_at?: string;
    counts?: Record<string, number>; git?: { commit?: string };
    integrity_problems?: string[];
    executed_signature?: { manifestation?: string };
  } | null;
  effort?: { manual_oq_5_requirements_minutes?: number | null; tpv_execute_minutes_all_requirements?: number | null } | null;
  deliverables: PackageDeliverable[];
  trace: {
    summary?: Record<string, number> | null;
    flags?: { untested_requirements?: string[]; failing_requirements?: string[]; below_min_depth?: string[]; tests_without_requirement_count?: number };
    rows?: TraceRow[];
  } | null;
  defects: {
    planted?: number;
    detected?: number;
    rows?: DefectRow[];
    note?: string;
    source?: string;
    head?: string;
    historical?: boolean;
    applied?: number;
  } | null;
  report: { status?: string; record_id?: string | null; reason?: string | null } | null;
  audit_chain?: { ok?: boolean; checked?: number; first_bad_seq?: number | null } | null;
}

function isObj(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

export async function listAudit(query: { limit: number; offset: number; actor?: string; action?: string; objectType?: string }): Promise<AuditPageData> {
  const params = new URLSearchParams({ limit: String(query.limit), offset: String(query.offset), order: "desc" });
  if (query.actor) params.set("actor", query.actor);
  if (query.action) params.set("action", query.action);
  if (query.objectType) params.set("object_type", query.objectType);
  const body = await request<unknown>("GET", `/audit?${params.toString()}`, { silent: true });
  const d = isObj(body) ? body : {};
  const items = Array.isArray(d.items) ? (d.items as AuditEntry[]) : [];
  return {
    items,
    total: typeof d.total === "number" ? d.total : items.length,
    limit: typeof d.limit === "number" ? d.limit : query.limit,
    offset: typeof d.offset === "number" ? d.offset : query.offset,
  };
}

export function verifyChain() {
  return request<ChainResult>("GET", "/audit/verify", { silent: true });
}

export async function validationPackage(): Promise<ValidationPackage> {
  const body = await request<unknown>("GET", "/validation/package", { silent: true });
  const d = isObj(body) ? body : {};
  const trace = isObj(d.trace) ? d.trace : null;
  const defects = isObj(d.defects) ? d.defects : null;
  const report = isObj(d.report) ? d.report : null;
  return {
    system: typeof d.system === "string" ? d.system : undefined,
    git: isObj(d.git) ? d.git : undefined,
    execution: isObj(d.execution) ? d.execution : null,
    effort: isObj(d.effort) ? d.effort : null,
    generated_at: typeof d.generated_at === "string" ? d.generated_at : null,
    draft_stamp: typeof d.draft_stamp === "string" ? d.draft_stamp : null,
    deliverables: Array.isArray(d.deliverables) ? (d.deliverables as PackageDeliverable[]) : [],
    trace: trace
      ? {
          summary: isObj(trace.summary) ? (trace.summary as Record<string, number>) : null,
          flags: isObj(trace.flags) ? trace.flags : {},
          rows: Array.isArray(trace.rows) ? trace.rows.filter(isObj).map((row) => ({
            ...row, id: String(row.id ?? ""), text: String(row.text ?? ""), result: String(row.result ?? "unknown"),
            tests: Array.isArray(row.tests) ? row.tests.filter(isObj) as unknown as TraceTest[] : [],
            evidence: Array.isArray(row.evidence) ? row.evidence.filter(isObj) : [],
          })) : [],
        }
      : null,
    defects: defects
      ? {
          planted: typeof defects.planted === "number" ? defects.planted : undefined,
          detected: typeof defects.detected === "number" ? defects.detected : undefined,
          rows: Array.isArray(defects.rows) ? (defects.rows as DefectRow[]) : [],
          note: typeof defects.note === "string" ? defects.note : undefined,
          source: typeof defects.source === "string" ? defects.source : undefined,
          head: typeof defects.head === "string" ? defects.head : undefined,
          historical: defects.historical === true || defects.source === "validation/defects/LAST_RUN.json",
          applied: typeof defects.applied === "number" ? defects.applied : undefined,
        }
      : null,
    report: report
      ? {
          status: typeof report.status === "string" ? report.status : undefined,
          record_id: typeof report.record_id === "string" ? report.record_id : null,
          reason: typeof report.reason === "string" ? report.reason : null,
        }
      : null,
    audit_chain: isObj(d.audit_chain) ? (d.audit_chain as ValidationPackage["audit_chain"]) : null,
  };
}

/** Restrict package links to relative paths served by A7, including deep attachment paths. */
export function packageFileUrl(path: string | null | undefined): string | undefined {
  if (!path || path.includes("\\") || /[?#:]/.test(path)) return undefined;
  const parts = path.split("/");
  if (parts.some((p) => !p || p === "." || p === "..")) return undefined;
  return `/api/validation/package/files/${parts.map(encodeURIComponent).join("/")}`;
}

export async function evidenceManifest(dir: string): Promise<EvidenceManifest> {
  const url = packageFileUrl(`${dir}/evidence_manifest.json`);
  if (!url) throw new Error("Invalid evidence path");
  const manifest = await request<EvidenceManifest>("GET", url.slice(4), { silent: true });
  if (!Array.isArray(manifest.files)) throw new Error("Evidence manifest has no files array");
  return manifest;
}

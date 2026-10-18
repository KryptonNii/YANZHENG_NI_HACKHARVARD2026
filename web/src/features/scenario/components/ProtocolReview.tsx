import { useTranslation, translate as t } from "@/app/i18n";
import { useMemo, useState } from "react";
import type { Procedure, Visit } from "@/app/contracts";
import type { ExtractionCandidate, ProtocolReviewStats } from "@/app/api/types";
import { DraftStamp } from "@/app/ui";

type RowStatus = "pending" | "accepted" | "edited" | "rejected";

interface Row {
  key: number;
  candidate: ExtractionCandidate;
  visit: Visit;
  status: RowStatus;
  editing: boolean;
  /** True once Edit was opened, so a later bulk accept is not "unopened". */
  opened: boolean;
  /** True when Accept all remaining set this row, and it was never opened. */
  viaBulk: boolean;
  weekDraft: string;
}

const STATUS_CHIP: Record<RowStatus, { text: string; cls: string }> = {
  pending: { get text() { return t("To review", "待审核"); }, cls: "border-ink-300 bg-ink-50 text-ink-700" },
  accepted: { get text() { return t("✓ Accepted", "✓ 已接受"); }, cls: "border-better-300 bg-better-50 text-better-800" },
  edited: { get text() { return t("✎ Edited", "✎ 已编辑"); }, cls: "border-accent-300 bg-accent-50 text-accent-800" },
  rejected: { get text() { return t("✕ Rejected", "✕ 已拒绝"); }, cls: "border-worse-300 bg-worse-50 text-worse-800" },
};

export const ENDPOINT_ROLES: Record<Procedure["endpoint_role"], string> = {
  get supports_primary() { return t("Supports primary outcome", "支持主要结局"); },
  get supports_secondary() { return t("Supports secondary outcome", "支持次要结局"); },
  get not_linked() { return t("Not linked to a registry outcome", "未关联注册记录中的结局"); },
  get unknown() { return t("To confirm", "待确认"); },
};

export const LINK_BASES: Record<Procedure["link_basis"], string> = {
  get outcome_title() { return t("Registry title match", "注册记录标题匹配"); },
  get human() { return t("Human review", "人工审核"); },
  get unmatched() { return t("Unmatched", "未匹配"); },
};

/** True when the reviewed visit differs from the AI candidate (label, week or any procedure field). */
function isEdited(candidate: Visit, visit: Visit): boolean {
  return visit.label !== candidate.label || visit.week !== candidate.week
    || JSON.stringify(visit.procedures) !== JSON.stringify(candidate.procedures);
}

/**
 * Human review of AI-extracted schedule-of-activities candidates (§2 rule 6: AI outputs are
 * drafts). Nothing is applied until a person accepts rows and presses "Apply to design".
 */
export function ProtocolReview({
  candidates,
  warnings,
  canApply,
  applying,
  onApply,
}: {
  candidates: ExtractionCandidate[];
  warnings: string[];
  canApply: boolean;
  applying: boolean;
  onApply: (visits: Visit[], stats: ProtocolReviewStats) => void;
}) {
  useTranslation();
  const [rows, setRows] = useState<Row[]>(() =>
    candidates.map((c, i) => ({
      key: i,
      candidate: c,
      visit: structuredClone(c.visit),
      status: "pending",
      editing: false,
      opened: false,
      viaBulk: false,
      weekDraft: String(c.visit.week),
    })),
  );

  const update = (key: number, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const editEndpoint = (row: Row, index: number, patch: Partial<Pick<Procedure, "endpoint_role" | "endpoint_note">>) =>
    update(row.key, {
      visit: {
        ...row.visit,
        procedures: row.visit.procedures.map((p, i) => i === index ? { ...p, ...patch, link_basis: "human" } : p),
      },
    });
  const counts = useMemo(() => {
    const c = { pending: 0, accepted: 0, edited: 0, rejected: 0 };
    rows.forEach((r) => (c[r.status] += 1));
    return c;
  }, [rows]);

  const weekValid = (draft: string) => draft.trim() !== "" && Number.isFinite(Number(draft));

  const apply = () => {
    const visits = rows
      .filter((r) => r.status === "accepted" || r.status === "edited")
      .map((r) => r.visit)
      .sort((a, b) => a.week - b.week || a.number - b.number);
    onApply(visits, {
      accepted: counts.accepted,
      edited: counts.edited,
      rejected: counts.rejected,
      bulk_accepted: rows.filter((r) => r.status === "accepted" && r.viaBulk).length,
    });
  };

  const acceptRemaining = () =>
    setRows((rs) =>
      rs.map((r) => {
        if (r.status !== "pending" || r.editing) return r;
        return { ...r, status: "accepted", viaBulk: !r.opened };
      }),
    );

  return (
    <div data-testid="protocol-review">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <DraftStamp>{t("Pending review", "待审核")}</DraftStamp>
          <span className="text-sm text-ink-600">
            {candidates.length} {t("visit", "次访视")}{t(candidates.length === 1 ? "" : "s", "")} · {counts.accepted + counts.edited} {t("accepted ·", "已接受 ·")} {counts.rejected} {t("rejected ·", "已拒绝 ·")}{" "}
            {counts.pending} {t("to review", "待审核")}
          </span>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="btn-ghost py-1.5 text-xs"
            onClick={acceptRemaining}
            disabled={counts.pending === 0}
          >
            {t("Accept remaining", "接受剩余项")}
          </button>
          <button
            type="button"
            className="btn-primary py-1.5"
            disabled={!canApply || applying || counts.accepted + counts.edited === 0}
            onClick={apply}
            data-testid="apply-extraction"
            title={canApply ? undefined : t("Import the trial first, then apply the extracted schedule to it", "请先导入试验，再应用提取的访视计划")}
          >
            {applying ? t("Applying…", "应用中…") : t("Apply to design", "应用到设计")}
          </button>
        </div>
      </div>
      {warnings.length > 0 && (
        <details className="mb-3 rounded-lg bg-caution-50 px-3 py-2 text-sm text-caution-900">
          <summary className="cursor-pointer font-semibold">{t("Review notes", "审核事项")} ({warnings.length})</summary>
          <ul className="mt-2 list-disc pl-5">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      )}
      {counts.pending > 0 && counts.accepted + counts.edited > 0 && (
        <p className="mb-2 text-xs text-ink-500">{t("Only accepted visits will be applied.", "仅应用已接受访视。")}</p>
      )}
      <div className="overflow-x-auto rounded-lg border border-ink-200">
        <table className="w-full text-sm">
          <thead className="bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">{t("Visit", "访视")}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{t("Week", "周次")}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{t("Procedures", "检查项目")}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{t("Source", "来源")}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{t("Status", "状态")}</th>
              <th scope="col" className="px-3 py-2"><span className="sr-only">{t("Actions", "操作")}</span></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className={`border-t border-ink-100 align-top ${r.status === "rejected" ? "bg-ink-50 text-ink-500" : ""}`}>
                <td className="px-3 py-2">
                  {r.editing ? (
                    <input
                      className="input py-1"
                      aria-label={t(`Visit ${r.visit.number} label`, `访视 ${r.visit.number} 的名称`)}
                      value={r.visit.label}
                      onChange={(e) => update(r.key, { visit: { ...r.visit, label: e.target.value } })}
                    />
                  ) : (
                    <span className={r.status === "rejected" ? "line-through" : "font-medium text-ink-900"}>
                      V{r.visit.number} {r.visit.label}
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 tabular">
                  {r.editing ? (
                    <input
                      className="input w-20 py-1"
                      type="number"
                      step="0.5"
                      aria-label={t(`Visit ${r.visit.number} week`, `访视 ${r.visit.number} 的周次`)}
                      value={r.weekDraft}
                      onChange={(e) => update(r.key, { weekDraft: e.target.value })}
                    />
                  ) : (
                    r.visit.week
                  )}
                  {r.editing && !weekValid(r.weekDraft) && (
                    <span className="mt-1 block text-xs font-medium text-worse-700">{t("Enter a valid week.", "请输入有效周次。")}</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="max-w-xs space-y-2">
                    {r.visit.procedures.map((p, index) => (
                      <div key={`${p.code}-${index}`} className="rounded border border-ink-200 bg-white p-2 text-ink-700">
                        <span className="font-medium" title={p.code}>{p.label}</span>
                        {r.editing && (
                          <button
                            type="button"
                            className="ml-0.5 text-ink-400 hover:text-worse-700"
                            aria-label={t(`Remove ${p.label}`, `移除 ${p.label}`)}
                            onClick={() => update(r.key, { visit: { ...r.visit, procedures: r.visit.procedures.filter((_, i) => i !== index) } })}
                          >
                            ×
                          </button>
                        )}
                        {r.editing ? (
                          <>
                            <select
                              className="input mt-1 py-1 text-xs"
                              aria-label={t(`Visit ${r.visit.number} ${p.label} endpoint role`, `访视 ${r.visit.number} ${p.label} 的终点角色`)}
                              value={p.endpoint_role ?? "unknown"}
                              onChange={(e) => editEndpoint(r, index, {
                                endpoint_role: e.target.value as Procedure["endpoint_role"],
                                endpoint_note: p.link_basis === "human" ? p.endpoint_note : "",
                              })}
                            >
                              {Object.entries(ENDPOINT_ROLES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                            </select>
                            <input
                              className="input mt-1 py-1 text-xs"
                              aria-label={t(`Visit ${r.visit.number} ${p.label} endpoint note`, `访视 ${r.visit.number} ${p.label} 的终点备注`)}
                              placeholder={t("Endpoint note", "终点备注")}
                              value={p.endpoint_note ?? ""}
                              onChange={(e) => editEndpoint(r, index, { endpoint_note: e.target.value })}
                            />
                          </>
                        ) : (
                          <>
                            <span className="mt-1 block text-xs">{ENDPOINT_ROLES[p.endpoint_role ?? "unknown"]}</span>
                            <details className="mt-1 text-xs text-ink-500">
                              <summary className="cursor-pointer">{t("Link details", "关联详情")}</summary>
                              {p.endpoint_note && <p className="mt-1">{p.endpoint_note}</p>}
                              <span className="mt-1 block">{LINK_BASES[p.link_basis ?? "unmatched"]}</span>
                            </details>
                          </>
                        )}
                      </div>
                    ))}
                    {r.visit.procedures.length === 0 && <span className="text-xs text-ink-400">{t("none", "无")}</span>}
                  </div>
                </td>
                <td className="max-w-sm px-3 py-2 text-xs text-ink-600">
                  {r.candidate.source_page !== null || r.candidate.quote ? (
                    <details>
                      <summary className="cursor-pointer font-semibold text-ink-800">{r.candidate.source_page !== null ? `${t("p.", "第")} ${r.candidate.source_page}${t("", " 页")}` : t("Source details", "来源详情")}</summary>
                      {r.candidate.quote && <q className="mt-1 block italic">{r.candidate.quote}</q>}
                      {r.candidate.confidence !== null && <span className="mt-1 block text-ink-400">{t("Confidence", "置信度")} {Math.round(r.candidate.confidence * 100)}%</span>}
                    </details>
                  ) : <span className="text-caution-800">{t("Source to confirm", "来源待确认")}</span>}
                </td>
                <td className="px-3 py-2">
                  <span className={`chip ${STATUS_CHIP[r.status].cls}`}>{STATUS_CHIP[r.status].text}</span>
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-right">
                  {r.editing ? (
                    <button
                      type="button"
                      className="btn-secondary px-2 py-1 text-xs"
                      disabled={!weekValid(r.weekDraft)}
                      onClick={() => {
                        const week = Number(r.weekDraft);
                        const visit = { ...r.visit, week };
                        update(r.key, { editing: false, visit, weekDraft: String(week), status: isEdited(r.candidate.visit, visit) ? "edited" : "accepted", viaBulk: false, opened: true });
                      }}
                    >
                      {t("Done", "完成")}
                    </button>
                  ) : (
                    <div className="flex justify-end gap-1">
                      <button type="button" className="btn-ghost px-2 py-1 text-xs" onClick={() => update(r.key, { status: isEdited(r.candidate.visit, r.visit) ? "edited" : "accepted", viaBulk: false })} aria-label={t(`Accept visit ${r.visit.number}`, `接受访视 ${r.visit.number}`)}>
                        {t("Accept", "接受")}
                      </button>
                      <button
                        type="button"
                        className="btn-ghost px-2 py-1 text-xs"
                        onClick={() => update(r.key, { editing: true, opened: true, viaBulk: false, weekDraft: String(r.visit.week) })}
                        aria-label={t(`Edit visit ${r.visit.number}`, `编辑访视 ${r.visit.number}`)}
                      >
                        {t("Edit", "编辑")}
                      </button>
                      <button type="button" className="btn-ghost px-2 py-1 text-xs text-worse-700" onClick={() => update(r.key, { status: "rejected" })} aria-label={t(`Reject visit ${r.visit.number}`, `拒绝访视 ${r.visit.number}`)}>
                        {t("Reject", "拒绝")}
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

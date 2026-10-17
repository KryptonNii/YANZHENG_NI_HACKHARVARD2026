import { useTranslation, translate as t } from "@/app/i18n";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, isAbort } from "@/app/api/client";
import type { ApprovalView, SavedScenario } from "@/app/api/types";
import { formatUtc, formatValue } from "@/app/format";
import { displayName } from "@/app/identity";
import { localizeCopy } from "@/app/localize";
import { useToast } from "@/app/toast";
import { Badge, EmptyState, Spinner } from "@/app/ui";
import { isKnownRange } from "../metrics";
import { ApprovalPanel } from "./ApprovalPanel";

export function ScenarioStatusChip({ status }: { status: SavedScenario["status"] }) {
  useTranslation();
  switch (status) {
    case "approved":
      return <Badge tone="better">{t("✓ Approved", "✓ 已批准")}</Badge>;
    case "submitted":
      return <Badge tone="caution">{t("◷ Submitted", "◷ 已提交")}</Badge>;
    case "rejected":
      return <Badge tone="worse">{t("✕ Rejected", "✕ 已拒绝")}</Badge>;
    default:
      return <Badge tone="neutral">{t("Draft", "草稿")}</Badge>;
  }
}

/** Saved versions of scenarios for this design + submit / approval / export for the selected one. */
export function VersionsPanel({
  scenarios,
  loading,
  selectedId,
  onSelect,
  onLoadLevers,
  onRefresh,
}: {
  scenarios: SavedScenario[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onLoadLevers: (s: SavedScenario) => void;
  onRefresh: () => void;
}) {
  useTranslation();
  const toast = useToast();
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [full, setFull] = useState<SavedScenario | null>(null);
  const [approval, setApproval] = useState<ApprovalView | null>(null);
  const [loadingFull, setLoadingFull] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const summary = scenarios.find((s) => s.id === selectedId) ?? null;
  const statusKey = summary?.status;

  const loadFull = useCallback(async (id: string, signal?: AbortSignal) => {
    setLoadingFull(true);
    try {
      const s = await api.getScenario(id, { signal, silent: true });
      setFull(s);
      // prefer A7's approval view (signature validity + manifestation) over the embedded copy
      const view = s.approval_id ? await api.getApproval(s.approval_id, { signal, silent: true }).catch(() => null) : null;
      setApproval(view ?? s.approval ?? null);
    } catch (err) {
      if (!isAbort(err)) {
        setFull(null);
        setApproval(null);
      }
    } finally {
      setLoadingFull(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setFull(null);
      setApproval(null);
      return;
    }
    const ctrl = new AbortController();
    void loadFull(selectedId, ctrl.signal);
    return () => ctrl.abort();
    // reload when the list reports a new status for the selected scenario
  }, [selectedId, statusKey, loadFull]);

  const selected = full ?? summary;

  const submit = async () => {
    if (!selected) return;
    setSubmitting(true);
    try {
      const s = await api.submitScenario(selected.id);
      setFull(s);
      setApproval(s.approval);
      toast.push("success", t("Submitted for approval", "已提交审批"), t(`${s.name} v${s.version} is now locked; changes create a new version.`, `${s.name} v${s.version} 已锁定；更改将创建新版本。`));
      onRefresh();
    } catch {
      // toast already shown by the client
    } finally {
      setSubmitting(false);
    }
  };

  const loadLevers = async (s: SavedScenario) => {
    try {
      const fullRow = s.levers ? s : await api.getScenario(s.id);
      onLoadLevers(fullRow);
    } catch {
      // toast shown by the client
    }
  };

  const toggleCompare = (id: string) => setCompareIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids.slice(-1), id]));

  return (
    <section className="card p-4" aria-labelledby="versions-title" data-testid="versions-panel">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="versions-title" className="card-title">
          {t("Saved scenarios & approval", "已保存方案与审批")}
        </h2>
        {compareIds.length === 2 ? (
          <Link className="btn-secondary py-1.5" to={`/compare?a=${encodeURIComponent(compareIds[0])}&b=${encodeURIComponent(compareIds[1])}`} data-testid="compare-selected">
            {t("Compare selected (2)", "比较所选方案（2）")}
          </Link>
        ) : (
          <span className="text-xs text-ink-500">{t("Tick two scenarios to compare them", "勾选两个方案进行比较")}</span>
        )}
      </div>

      {loading && scenarios.length === 0 ? (
        <Spinner label={t("Loading saved scenarios", "正在加载已保存方案")} />
      ) : scenarios.length === 0 ? (
        <EmptyState title={t("No saved scenarios yet", "暂无已保存方案")}>{t("Use “Save scenario” to keep this lever set as a version you can compare and submit.", "使用“保存方案”将当前调整项保存为可比较和提交的版本。")}</EmptyState>
      ) : (
        <div className="max-h-72 overflow-auto">
          <table className="w-full text-sm" data-testid="versions-table">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
                <th scope="col" className="w-8 pb-1">
                  <span className="sr-only">{t("Compare", "比较")}</span>
                </th>
                <th scope="col" className="pb-1 font-semibold">{t("Scenario", "方案")}</th>
                <th scope="col" className="whitespace-nowrap pb-1 text-right font-semibold">{t("Cost P50", "费用 P50")}</th>
                <th scope="col" className="pb-1 font-semibold">{t("Status", "状态")}</th>
                <th scope="col" className="pb-1">
                  <span className="sr-only">{t("Actions", "操作")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => {
                const cost = s.metrics.cost_usd;
                return (
                  <tr key={s.id} className={`border-t border-ink-100 ${s.id === selectedId ? "bg-accent-50/60" : ""}`}>
                    <td className="py-1.5">
                      <input
                        type="checkbox"
                        className="h-4 w-4 accent-accent-700"
                        aria-label={t(`Select ${s.name} v${s.version} for comparison`, `选择 ${localizeCopy(s.name)} v${s.version} 进行比较`)}
                        checked={compareIds.includes(s.id)}
                        onChange={() => toggleCompare(s.id)}
                      />
                    </td>
                    <td className="py-1.5">
                      <button type="button" className="text-left font-semibold text-ink-900 hover:underline" onClick={() => onSelect(s.id)} aria-pressed={s.id === selectedId}>
                        {localizeCopy(s.name)} <span className="font-normal text-ink-500">v{s.version}</span>
                      </button>
                      <span className="block text-xs text-ink-500">
                        {displayName(s.author)} · {formatUtc(s.created_at)}
                        {s.design_version != null ? t(` · design v${s.design_version}`, ` · 设计 v${s.design_version}`) : ""}
                      </span>
                    </td>
                    <td className="whitespace-nowrap py-1.5 pl-2 text-right tabular text-ink-800">{cost && isKnownRange(cost) ? formatValue(cost.p50, "usd") : cost ? t("unknown", "未知") : "—"}</td>
                    <td className="whitespace-nowrap py-1.5 pl-2">
                      <ScenarioStatusChip status={s.status} />
                    </td>
                    <td className="py-1.5 text-right">
                      <button type="button" className="btn-ghost whitespace-nowrap px-2 py-1 text-xs" onClick={() => void loadLevers(s)}>
                        {t("Load levers", "加载调整项")}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="mt-4 grid gap-3 border-t border-ink-100 pt-4 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]" data-testid="selected-scenario">
          <div>
            <p className="text-sm font-semibold text-ink-900">
              {localizeCopy(selected.name)} <span className="font-normal text-ink-500">v{selected.version}</span> <ScenarioStatusChip status={selected.status} />
            </p>
            <p className="mt-0.5 text-xs text-ink-500">
              {t("Parameter set", "参数集")} <code className="font-mono">{selected.parameter_set_version ?? "—"}</code>
              {selected.record_hash && (
                <>
                  {" "}
                  {t("· record sha256", "· 记录 SHA256")} <code className="font-mono">{selected.record_hash.slice(0, 12)}…</code>
                </>
              )}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {selected.status === "draft" && (
                <button type="button" className="btn-primary" onClick={() => void submit()} disabled={submitting} data-testid="submit-approval">
                  {submitting ? t("Submitting…", "提交中…") : t("Submit for approval", "提交审批")}
                </button>
              )}
              <a className="btn-secondary" href={api.exportUrl(selected.id, "csv")} download>
                {t("Export CSV", "导出 CSV")}
              </a>
              <a className="btn-secondary" href={api.exportUrl(selected.id, "pdf")} target="_blank" rel="noreferrer">
                {t("Export PDF", "导出 PDF")}
              </a>
            </div>
            {selected.status !== "draft" && (
              <p className="mt-2 text-xs text-ink-500">{t("Submitted scenarios are immutable. Saving changed levers creates a new version.", "已提交的方案不可修改。保存更改后的调整项将创建新版本。")}</p>
            )}
          </div>
          <div>
            {loadingFull && !approval ? (
              <Spinner label={t("Loading approval", "正在加载审批信息")} />
            ) : approval ? (
              <ApprovalPanel
                approval={approval}
                onChange={(a) => {
                  setApproval(a);
                  if (a.status !== "pending") onRefresh();
                }}
              />
            ) : selected.status === "draft" ? (
              <p className="rounded-lg bg-ink-50 px-3 py-2 text-sm text-ink-600">{t("Not submitted yet. Submitting locks this version and starts review → approval.", "尚未提交。提交后将锁定此版本，并启动审核 → 批准流程。")}</p>
            ) : (
              <p className="rounded-lg bg-ink-50 px-3 py-2 text-sm text-ink-600">{t("No approval request found for this scenario.", "未找到此方案的审批请求。")}</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

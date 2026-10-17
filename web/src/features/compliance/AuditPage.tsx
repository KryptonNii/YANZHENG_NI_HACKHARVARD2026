import { displayText } from "../command/displayText";
import { useTranslation } from "@/app/i18n";
import { Fragment, useEffect, useState } from "react";
import type { AuditEntry } from "@/app/contracts";
import { formatUtc } from "@/app/format";
import { displayName } from "@/app/identity";
import { Badge, EmptyState, ErrorPanel, Spinner } from "@/app/ui";
import { ApiError, listAudit, verifyChain, type ChainResult } from "./api";

const PAGE = 25;

export function AuditPage() {
  const t = useTranslation();
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [objectType, setObjectType] = useState("");
  const [applied, setApplied] = useState({ actor: "", action: "", objectType: "" });
  const [offset, setOffset] = useState(0);
  // bumped by "Try again" so a retry goes through the same cancellable load as filters and paging
  const [reload, setReload] = useState(0);
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [openSeq, setOpenSeq] = useState<number | null>(null);
  const [chain, setChain] = useState<ChainResult | null>(null);
  const [chainError, setChainError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const exportQuery = new URLSearchParams();
  if (applied.actor) exportQuery.set("actor", applied.actor);
  if (applied.action) exportQuery.set("action", applied.action);
  if (applied.objectType) exportQuery.set("object_type", applied.objectType);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    void listAudit({ limit: PAGE, offset, ...applied })
      .then((page) => {
        if (cancelled) return;
        setRows(page.items);
        setTotal(page.total);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setRows([]);
        setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, [applied, offset, reload]);

  const verify = async () => {
    setVerifying(true);
    setChainError(null);
    try {
      setChain(await verifyChain());
    } catch (err) {
      setChain(null);
      setChainError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setVerifying(false);
    }
  };

  return (
    <div className="space-y-4" data-testid="audit-page">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{t("Audit trail", "审计记录")}</h1>
          <p className="mt-1 text-sm text-ink-500">{t("Append-only hash chain. Every row is the record of one change.", "仅允许追加的哈希链。每一行记录一次更改。")}</p>
        </div>
        <div className="flex gap-2">
          <a className="btn-secondary" href={`/api/audit/export.csv${exportQuery.size ? `?${exportQuery}` : ""}`} download>{t("Export CSV", "导出 CSV")}</a>
          <button type="button" className="btn-primary" onClick={() => void verify()} disabled={verifying}>
            {verifying ? t("Verifying…", "正在验证…") : t("Verify chain", "验证哈希链")}
          </button>
        </div>
      </header>

      {chain &&
        (chain.ok ? (
          <p data-testid="chain-result" role="status" className="rounded-lg border border-better-200 bg-better-50 px-4 py-3 text-sm font-semibold text-better-900">
            {t("Chain intact —", "哈希链完整 —")} {chain.checked} {t("entries", "条记录")}
          </p>
        ) : (
          <p data-testid="chain-result" role="alert" className="rounded-lg border border-worse-200 bg-worse-50 px-4 py-3 text-sm font-semibold text-worse-900">
            {chain.first_bad_seq == null ? t("Chain verification failed", "哈希链验证失败") : t(`Broken at seq ${chain.first_bad_seq}`, `序号 ${chain.first_bad_seq} 处断裂`)}
            {chain.problem ? ` — ${chain.problem}` : ""}
          </p>
        ))}
      {chainError && <ErrorPanel title={t("Chain verification failed", "哈希链验证失败")} message={chainError} onRetry={() => void verify()} />}

      <form
        className="card flex flex-wrap items-end gap-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          setApplied({ actor: actor.trim(), action: action.trim(), objectType: objectType.trim() });
        }}
      >
        <label className="text-sm">
          <span className="label">{t("Actor", "操作人")}</span>
          <input className="input mt-1" value={actor} onChange={(e) => setActor(e.target.value)} />
        </label>
        <label className="text-sm">
          <span className="label">{t("Action", "操作")}</span>
          <input className="input mt-1" value={action} onChange={(e) => setAction(e.target.value)} placeholder="approval.sign" />
        </label>
        <label className="text-sm">
          <span className="label">{t("Object type", "对象类型")}</span>
          <input className="input mt-1" value={objectType} onChange={(e) => setObjectType(e.target.value)} />
        </label>
        <button type="submit" className="btn-secondary">
          {t("Apply filters", "应用筛选")}
        </button>
      </form>

      {error && <ErrorPanel title={t("Couldn't load the audit trail", "无法加载审计记录")} message={error} onRetry={() => setReload((n) => n + 1)} />}
      {rows === null && <Spinner label={t("Loading audit trail", "正在加载审计记录")} />}
      {rows && rows.length === 0 && <EmptyState title={t("No audit entries match these filters", "没有符合筛选条件的审计记录")} />}

      {rows && rows.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="bg-ink-50 text-xs uppercase tracking-wide text-ink-500">
              <tr>
                <th className="px-3 py-2">{t("Seq", "序号")}</th>
                <th className="px-3 py-2">{t("Time", "时间")}</th>
                <th className="px-3 py-2">{t("Actor", "操作人")}</th>
                <th className="px-3 py-2">{t("Role", "角色")}</th>
                <th className="px-3 py-2">{t("Action", "操作")}</th>
                <th className="px-3 py-2">{t("Object", "对象")}</th>
                <th className="px-3 py-2">{t("Reason", "原因")}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Fragment key={row.seq}>
                  <tr className="border-t border-ink-100">
                    <td className="px-3 py-2 tabular">
                      <button type="button" className="font-semibold text-accent-700" onClick={() => setOpenSeq(openSeq === row.seq ? null : row.seq)} aria-expanded={openSeq === row.seq}>
                        {row.seq}
                      </button>
                    </td>
                    <td className="px-3 py-2 tabular text-xs text-ink-600">{formatUtc(row.at)}</td>
                    <td className="px-3 py-2">{displayName(row.actor)}</td>
                    <td className="px-3 py-2">
                      <Badge tone="neutral">{displayText(row.role)}</Badge>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{row.action}</td>
                    <td className="px-3 py-2 text-xs">
                      {displayText(row.object_type)}
                      <span className="mt-0.5 block font-mono text-ink-500">{row.object_id}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-ink-600">{row.reason ?? "—"}</td>
                  </tr>
                  {openSeq === row.seq && (
                    <tr className="bg-ink-50">
                      <td colSpan={7} className="px-4 py-3 font-mono text-[11px] leading-relaxed text-ink-700">
                        <div>{t("prev", "上一条哈希")} {row.prev_entry_hash}</div>
                        <div>{t("entry", "当前条目哈希")} {row.entry_hash}</div>
                        <div>{t("before", "更改前")} {row.before_hash ?? "—"}</div>
                        <div>{t("after", "更改后")} {row.after_hash ?? "—"}</div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
          <footer className="flex items-center justify-between border-t border-ink-200 px-4 py-2 text-sm">
            <span className="text-ink-500">
              {total === 0 ? "0" : `${offset + 1}–${Math.min(offset + rows.length, total)}`} {t("of", "/")} {total}
            </span>
            <div className="flex gap-2">
              <button type="button" className="btn-secondary" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
                {t("Previous", "上一页")}
              </button>
              <button type="button" className="btn-secondary" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
                {t("Next", "下一页")}
              </button>
            </div>
          </footer>
        </div>
      )}
    </div>
  );
}

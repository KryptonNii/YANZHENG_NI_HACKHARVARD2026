import { useTranslation, translate as t } from "@/app/i18n";
import { useEffect, useId, useState } from "react";
import type { SignatureMeaning } from "@/app/contracts";
import { api } from "@/app/api/client";
import type { ApprovalView, SignatureView } from "@/app/api/types";
import { formatUtc } from "@/app/format";
import { displayName, roleName, useIdentity } from "@/app/identity";
import { localizeCopy } from "@/app/localize";
import { Badge } from "@/app/ui";
import { signErrorMessage } from "@/features/compliance/errors";

export function nextMeaning(a: ApprovalView): string | null {
  if (a.status !== "pending") return null;
  if (a.next_meaning !== undefined) return a.next_meaning ?? null;
  const signed = new Set(a.signatures.map((s) => s.meaning));
  return a.required_meanings.find((m) => !signed.has(m as SignatureMeaning)) ?? null;
}

function meaningLabel(meaning: string): string {
  return t(meaning, ({ reviewed: "已审核", approved: "已批准", authored: "已编写" } as Record<string, string>)[meaning] ?? meaning);
}

function StatusChip({ status }: { status: ApprovalView["status"] }) {
  useTranslation();
  if (status === "approved") return <Badge tone="better">{t("✓ Approved", "✓ 已批准")}</Badge>;
  if (status === "rejected") return <Badge tone="worse">{t("✕ Rejected", "✕ 已拒绝")}</Badge>;
  return <Badge tone="caution">{t("◷ Pending approval", "◷ 待批准")}</Badge>;
}

function Validity({ sig }: { sig: SignatureView }) {
  useTranslation();
  if (sig.valid === true) return <Badge tone="better" title={t("The record still matches the hash that was signed", "记录仍与签名时的哈希值一致")}>{t("valid", "有效")}</Badge>;
  if (sig.valid === false) return <Badge tone="worse" title={sig.reason ?? undefined}>{t("invalid —", "无效 —")} {sig.reason ?? t("record changed", "记录已更改")}</Badge>;
  if (sig.valid === null) return <Badge tone="neutral" title={sig.reason ?? undefined}>{t("validity unknown", "有效性未知")}</Badge>;
  return null;
}

export function ApprovalPanel({ approval, onChange }: { approval: ApprovalView; onChange: (a: ApprovalView) => void }) {
  useTranslation();
  const me = useIdentity();
  const pinId = useId();
  const next = nextMeaning(approval);
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    setPin("");
  }, [me.user, approval.id]);

  const sign = async () => {
    if (!next) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.sign(approval.id, { meaning: next as SignatureMeaning, pin }, { silent: true });
      onChange(updated);
      setPin("");
    } catch (err) {
      setError(signErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-lg border border-ink-200 p-3" data-testid="approval-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-ink-900">{t("Approval", "审批")}</p>
        <span data-testid="approval-status">
          <StatusChip status={approval.status} />
        </span>
      </div>
      <p className="mt-1 text-xs text-ink-500">
        {t("Author", "作者")} {approval.author_name ?? displayName(approval.author)} {t("· required:", "· 需要：")} {approval.required_meanings.map(meaningLabel).join(" → ")}
      </p>
      {approval.record_changed && (
        <p className="mt-2 rounded-md bg-worse-50 px-2 py-1 text-xs font-medium text-worse-900">{t("Record changed · signatures invalid", "记录已更改 · 原签名失效")}</p>
      )}

      <ul className="mt-3 space-y-2" data-testid="signature-list">
        {approval.required_meanings.map((m) => {
          const sig = approval.signatures.find((s) => s.meaning === m);
          return (
            <li key={m} className="flex items-start gap-2 text-sm">
              <span aria-hidden className={sig ? "text-better-700" : "text-ink-400"}>
                {sig ? "✓" : "○"}
              </span>
              {sig ? (
                <span className="min-w-0">
                  <span className="font-semibold capitalize text-ink-900">{meaningLabel(sig.meaning)}</span> {t("by", "签署人")}{" "}
                  <span className="font-semibold">{sig.signer_name ?? displayName(sig.signer)}</span>
                  {sig.signer_name ? ` (${sig.signer}, ${roleName(sig.role)})` : ""} <Validity sig={sig} />
                  <span className="block text-xs tabular text-ink-500">{formatUtc(sig.signed_at)}</span>
                  <details className="text-xs text-ink-500"><summary>{t("Signature record", "签名记录")}</summary><code className="break-all font-mono">SHA256 {sig.record_hash}</code></details>
                </span>
              ) : (
                <span className="capitalize text-ink-500">{meaningLabel(m)} {t("· Pending", "· 待签署")}</span>
              )}
            </li>
          );
        })}
      </ul>
      {approval.status === "rejected" && approval.reject_reason && <p className="mt-2 text-sm text-worse-800">{t("Rejected:", "拒绝原因：")} {approval.reject_reason}</p>}

      {next && (
        <form
          className="mt-3 border-t border-ink-100 pt-3"
          onSubmit={(e) => {
            e.preventDefault();
            void sign();
          }}
        >
          <p className="text-sm text-ink-800">
            {t("Sign as", "签署身份")} <strong>{me.name}</strong> ({roleName(me.role)}) {t("with meaning", "签署含义")} <strong className="capitalize">{meaningLabel(next)}</strong>
          </p>
          <p className="mt-1 text-xs text-ink-500">
            {t("Signing confirms this action and records a signature against this version.", "签署即确认完成上述操作，并对当前版本留存签名记录。")}
          </p>
          <div className="mt-2 flex items-end gap-2">
            <div className="flex-1">
              <label htmlFor={pinId} className="label text-xs">
                {t("PIN", "PIN 码")}
              </label>
              <input
                id={pinId}
                type="password"
                inputMode="numeric"
                autoComplete="off"
                className="input mt-1"
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                data-testid="sign-pin"
                required
              />
            </div>
            <button type="submit" className="btn-primary" disabled={busy || pin.length === 0} data-testid="sign-button">
              {busy ? t("Signing…", "签署中…") : t(`Sign: ${next}`, `签署：${meaningLabel(next)}`)}
            </button>
          </div>
          {error && (
            <p role="alert" className="mt-2 rounded-md border border-worse-200 bg-worse-50 px-3 py-2 text-sm font-medium text-worse-900" data-testid="sign-error">
              {localizeCopy(error)}
            </p>
          )}
        </form>
      )}
    </div>
  );
}

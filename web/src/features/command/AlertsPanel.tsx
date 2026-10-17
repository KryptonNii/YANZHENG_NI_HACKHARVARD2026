import { displayText } from "./displayText";
import { useTranslation } from "@/app/i18n";
import { localizeCopy } from "@/app/localize";
import { useEffect, useState } from "react";
import type { Alert } from "@/app/contracts";
import { Badge, Modal } from "@/app/ui";
import { ApiError, getAlertOptions, patchAlert, createIntervention } from "./api";
import type { ActionOption, AlertOptions } from "./api";
import { IMPACT_KEYS, IMPACT_LABEL, impactText, predictedText, statusTone } from "./present";

const ACTIVE = new Set<Alert["status"]>(["open", "acknowledged", "action_planned"]);

function severityTone(severity: Alert["severity"]) {
  if (severity === "critical") return "worse" as const;
  if (severity === "warning") return "caution" as const;
  return "accent" as const;
}

export function AlertsPanel({
  trialId,
  alerts,
  owner,
  onChanged,
}: {
  trialId: string;
  alerts: Alert[];
  owner: string;
  onChanged: () => Promise<void> | void;
}) {
  const t = useTranslation();
  const [showAll, setShowAll] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dismissId, setDismissId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [planning, setPlanning] = useState<Alert | null>(null);

  const visible = showAll ? alerts : alerts.filter((a) => ACTIVE.has(a.status));

  const run = async (id: string, fn: () => Promise<unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      await fn();
      await onChanged();
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="card flex flex-col" data-testid="alerts-panel" aria-label={t("Alerts", "警报")}>
      <header className="flex items-center justify-between gap-2 border-b border-ink-200 px-4 py-3">
        <h2 className="card-title">{t("Alerts", "警报")}</h2>
        <button type="button" className="text-xs font-semibold text-accent-700" onClick={() => setShowAll((v) => !v)}>
          {showAll ? t("Active only", "仅显示活动警报") : t(`Show all (${alerts.length})`, `显示全部（${alerts.length}）`)}
        </button>
      </header>
      {error && (
        <p role="alert" className="mx-4 mt-3 rounded-md border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900">
          {localizeCopy(error)}
        </p>
      )}
      <ul className="max-h-[36rem] space-y-3 overflow-auto p-4">
        {visible.length === 0 && <li className="text-sm text-ink-500">{t("No active alerts.", "没有活动警报。")}</li>}
        {visible.map((alert) => (
          <li key={alert.id} className="rounded-lg border border-ink-200 p-3" data-testid={`alert-${alert.kind}`}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={severityTone(alert.severity)}>{displayText(alert.severity)}</Badge>
              <Badge tone={statusTone(alert.status === "open" ? "watch" : alert.status === "resolved" ? "on_track" : "unknown")}>{displayText(alert.status.replaceAll("_", " "))}</Badge>
              <span className="text-xs uppercase tracking-wide text-ink-400">{displayText(alert.kind.replaceAll("_", " "))}</span>
            </div>
            <p className="mt-2 text-sm text-ink-900">{displayText(alert.summary)}</p>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              {IMPACT_KEYS.map((key) => (
                <div key={key}>
                  <dt className="text-ink-500">{displayText(IMPACT_LABEL[key])}</dt>
                  <dd className="tabular font-medium text-ink-800">{impactText(alert.est_impact?.[key])}</dd>
                </div>
              ))}
            </dl>
            {alert.recommended_actions.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-ink-600">
                {alert.recommended_actions.map((action) => (
                  <li key={action}>{displayText(action)}</li>
                ))}
              </ul>
            )}
            {dismissId === alert.id ? (
              <form
                className="mt-3 space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!reason.trim()) {
                    setError(t("A reason is required.", "请填写原因。"));
                    return;
                  }
                  void run(alert.id, () => patchAlert(trialId, alert.id, "dismissed", reason.trim())).then((ok) => {
                    if (!ok) return;
                    setDismissId(null);
                    setReason("");
                  });
                }}
              >
                <label className="label text-xs" htmlFor={`dismiss-${alert.id}`}>
                  {t("Reason for dismissing (audited)", "解除原因（将记录审计）")}
                </label>
                <textarea id={`dismiss-${alert.id}`} className="input mt-1" required value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
                <div className="flex gap-2">
                  <button type="submit" className="btn-danger" disabled={busyId === alert.id}>
                    {t("Dismiss alert", "解除警报")}
                  </button>
                  <button type="button" className="btn-ghost" onClick={() => setDismissId(null)}>
                    {t("Cancel", "取消")}
                  </button>
                </div>
              </form>
            ) : (
              ACTIVE.has(alert.status) && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {alert.status === "open" && (
                    <button type="button" className="btn-secondary" disabled={busyId === alert.id} onClick={() => void run(alert.id, () => patchAlert(trialId, alert.id, "acknowledged"))}>
                      {t("Acknowledge", "确认收到")}
                    </button>
                  )}
                  <button type="button" className="btn-primary" disabled={busyId === alert.id} onClick={() => setPlanning(alert)}>
                    {t("Plan intervention", "规划干预")}
                  </button>
                  <button type="button" className="btn-ghost" disabled={busyId === alert.id} onClick={() => { setDismissId(alert.id); setReason(""); setError(null); }}>
                    {t("Dismiss", "解除")}
                  </button>
                </div>
              )
            )}
          </li>
        ))}
      </ul>
      <PlanDialog
        key={planning?.id ?? "none"}
        trialId={trialId}
        alert={planning}
        owner={owner}
        busy={busyId === planning?.id}
        onClose={() => setPlanning(null)}
        onSave={async (action) => {
          if (!planning) return;
          const ok = await run(planning.id, () =>
            createIntervention(trialId, {
              alert_id: planning.id,
              action,
              owner,
              target_site_ids: planning.site_id ? [planning.site_id] : [],
            }),
          );
          if (ok) setPlanning(null);
        }}
      />
    </section>
  );
}

function PlanDialog({
  trialId,
  alert,
  owner,
  busy,
  onClose,
  onSave,
}: {
  trialId: string;
  alert: Alert | null;
  owner: string;
  busy: boolean;
  onClose: () => void;
  onSave: (action: string) => Promise<void>;
}) {
  const t = useTranslation();
  const options = alert?.recommended_actions ?? [];
  const [action, setAction] = useState("");
  const [predicted, setPredicted] = useState<AlertOptions | null>(null);
  const selected = action || options[0] || "";
  useEffect(() => {
    if (!alert) return;
    let live = true;
    getAlertOptions(trialId, alert.id)
      .then((found) => { if (live) setPredicted(found); })
      .catch(() => undefined); // the predictions are extra context; planning works without them
    return () => { live = false; };
  }, [trialId, alert]);
  return (
    <Modal
      open={alert !== null}
      title={t("Plan intervention", "规划干预")}
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn-ghost" onClick={onClose}>
            {t("Cancel", "取消")}
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={busy || selected.trim().length === 0}
            onClick={() => void onSave(selected.trim())}
          >
            {busy ? t("Saving…", "正在保存…") : t("Save intervention", "保存干预")}
          </button>
        </>
      }
    >
      {alert && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (selected.trim()) void onSave(selected.trim());
          }}
        >
          <p className="text-sm text-ink-700">{displayText(alert.summary)}</p>
          {predicted && predicted.items.some((item) => item.quantified) && (
            <OptionsTable predicted={predicted} selected={selected} onPick={setAction} />
          )}
          <div>
            <label className="label" htmlFor="intervention-action">
              {t("Action", "操作")}
            </label>
            {options.length > 0 ? (
              <select
                id="intervention-action"
                className="input mt-1"
                value={selected}
                onChange={(e) => setAction(e.target.value)}
              >
                {options.map((opt) => (
                  <option key={opt} value={opt}>
                    {displayText(opt)}
                  </option>
                ))}
              </select>
            ) : (
              <input id="intervention-action" className="input mt-1" value={action} onChange={(e) => setAction(e.target.value)} required />
            )}
          </div>
          <p className="text-xs text-ink-500">
            {t("Owner", "负责人")} {owner}
            {alert.site_id ? t(` · site ${alert.site_id}`, ` · 中心 ${alert.site_id}`) : ""}{t(". The metric is taken from the alert. This is written to the audit trail.", "。指标取自警报，操作将写入审计记录。")}
          </p>
        </form>
      )}
    </Modal>
  );
}

/** What each recommended action is predicted to do, ranked by net value. The select below stays the source of truth. */
function OptionsTable({ predicted, selected, onPick }: { predicted: AlertOptions; selected: string; onPick: (action: string) => void }) {
  const t = useTranslation();
  const base = predicted.baseline;
  return (
    <section className="rounded-lg border border-ink-200 bg-ink-50 p-3" data-testid="action-options" aria-label={t("Predicted outcome of each action", "各行动的预测结果")}>
      <h3 className="text-xs font-semibold text-ink-800">{t("Predicted outcome of each action", "各行动的预测结果")}</h3>
      <p className="mt-1 text-[11px] leading-snug text-ink-500">
        {t(
          "Planning model with assumed parameters: a prediction, not an observed result. Ranked by net value (cost avoided minus the action's cost). It is saved when you plan the action and checked against the observed effect later.",
          "使用假设参数的规划模型：这是预测，不是观测结果。按净价值（避免的成本减去行动成本）排序。规划行动时会保存该预测，之后与实际观测效果对照。",
        )}
      </p>
      {base && (
        <p className="mt-2 text-xs text-ink-700" data-testid="option-baseline">
          {t("Do nothing", "不采取行动")}: {base.delay_days ? `${t("delay", "延迟")} ${predictedText(base.delay_days)} · ` : ""}
          {t("cost", "成本")} {predictedText(base.cost_usd)}
        </p>
      )}
      <ul className="mt-2 space-y-2">
        {predicted.items.map((item) =>
          item.quantified ? (
            <OptionRow key={item.code} item={item} chosen={selected === item.action} onPick={onPick} />
          ) : (
            <li key={item.code} className="text-[11px] text-ink-500" data-testid={`option-${item.code}`}>
              {displayText(item.label)} — {t("not ranked", "未排序")}: {displayText(item.reason ?? "")}
            </li>
          ),
        )}
      </ul>
      {predicted.note && <p className="mt-2 text-[11px] text-caution-900">{displayText(predicted.note)}</p>}
    </section>
  );
}

function OptionRow({ item, chosen, onPick }: { item: ActionOption; chosen: boolean; onPick: (action: string) => void }) {
  const t = useTranslation();
  return (
    <li data-testid={`option-${item.code}`}>
      <button
        type="button"
        aria-pressed={chosen}
        className={`w-full rounded-md border bg-white p-2 text-left ${chosen ? "border-accent-700" : "border-ink-200 hover:border-ink-400"}`}
        onClick={() => onPick(item.action)}
      >
        <span className="text-xs font-semibold text-ink-900">#{item.rank} {displayText(item.label)}</span>
        <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
          <div><dt className="text-ink-500">{t("Time saved", "节省时间")}</dt><dd className="tabular text-ink-800">{predictedText(item.delay_saved_days)}</dd></div>
          <div><dt className="text-ink-500">{t("Cost avoided", "避免的成本")}</dt><dd className="tabular text-ink-800">{predictedText(item.cost_avoided_usd)}</dd></div>
          <div><dt className="text-ink-500">{t("Action cost", "行动成本")}</dt><dd className="tabular text-ink-800">{predictedText(item.action_cost_usd)}</dd></div>
          <div><dt className="text-ink-500">{t("Net value", "净价值")}</dt><dd className="tabular font-semibold text-ink-900">{predictedText(item.net_usd)}</dd></div>
        </dl>
      </button>
      {(item.warnings ?? []).map((w) => (
        <p key={w} className="mt-1 text-[11px] text-caution-900">{displayText(w)}</p>
      ))}
      {item.reasoning && item.reasoning.length > 0 && (
        <details className="mt-1 text-[11px] text-ink-600">
          <summary className="cursor-pointer">{t("How is this predicted?", "预测依据")}</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-4">
            {item.reasoning.map((line) => <li key={line}>{displayText(line)}</li>)}
          </ul>
          {item.assumptions && item.assumptions.length > 0 && (
            <ul className="mt-1 list-disc space-y-0.5 pl-4 text-ink-500">
              {item.assumptions.map((line) => <li key={line}>{displayText(line)}</li>)}
            </ul>
          )}
        </details>
      )}
    </li>
  );
}

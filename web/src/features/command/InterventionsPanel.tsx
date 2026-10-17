import { displayText } from "./displayText";
import { useTranslation, translate } from "@/app/i18n";
import { localizeCopy } from "@/app/localize";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Intervention } from "@/app/contracts";
import { formatUtc, isNum } from "@/app/format";
import { Badge } from "@/app/ui";
import type { EffectDetail } from "./api";
import { startIntervention } from "./api";
import { VERDICT, predictedText, rangeText, reconcileLabel, reconcileTone } from "./present";

export function InterventionsPanel({ trialId, interventions, effects, onChanged }: { trialId: string; interventions: Intervention[]; effects: EffectDetail[]; onChanged: () => Promise<void> }) {
  const t = useTranslation();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const start = async (id: string) => {
    setBusy(id);
    setError(null);
    try { await startIntervention(trialId, id); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(null); }
  };
  const byId = new Map(effects.map((e) => [e.estimate.intervention_id, e]));
  return (
    <section className="card p-4" data-testid="intervention-list" aria-label={t("Interventions", "干预")}>
      <h2 className="card-title mb-3">{t("Interventions", "干预")}</h2>
      {error && <p role="alert" className="mb-3 text-sm text-worse-900">{localizeCopy(error)}</p>}
      {interventions.length === 0 && <p className="text-sm text-ink-500">{t("No interventions yet. Plan one from an alert.", "暂无干预。请从警报中规划干预。")}</p>}
      <ul className="space-y-4">
        {interventions.map((iv) => {
          const effect = byId.get(iv.id);
          const verdict = effect ? VERDICT[effect.estimate.verdict] : undefined;
          return (
            <li key={iv.id} className="rounded-lg border border-ink-200 p-3" data-testid={`intervention-${iv.id}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={iv.status === "done" ? "better" : iv.status === "in_progress" ? "accent" : "neutral"}>{displayText(iv.status.replaceAll("_", " "))}</Badge>
                <p className="text-sm font-semibold text-ink-900">{displayText(iv.action)}</p>
              </div>
              <p className="mt-1 text-xs text-ink-500">
                {t("Owner", "负责人")} {iv.owner} {t("· due", "· 到期")} {formatUtc(iv.due_date)} {t("· metric", "· 指标")} {displayText(iv.metric.replaceAll("_", " "))} {t("· sites", "· 中心")} {iv.target_site_ids.join(", ") || "—"}
              </p>
              {iv.status === "planned" && <button type="button" className="btn-secondary mt-2" disabled={busy !== null} onClick={() => void start(iv.id)}>{busy === iv.id ? t("Starting…", "正在启动…") : t("Start intervention", "启动干预")}</button>}
              {effect?.expectation && <PredictionCard effect={effect} />}
              {effect && verdict ? (
                <EffectCard effect={effect} />
              ) : (
                <p className="mt-2 text-xs text-ink-500">{t("Effect is estimated after the intervention has started and the clock moves forward.", "启动干预并推进时钟后，将估计干预效果。")}</p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function EffectCard({ effect }: { effect: EffectDetail }) {
  const t = useTranslation();
  const est = effect.estimate;
  const verdict = VERDICT[est.verdict] ?? { label: est.verdict, tone: "neutral" as const };
  const v = effect.values;
  const chart =
    v && isNum(v.treated_pre) && isNum(v.treated_post) && isNum(v.control_pre) && isNum(v.control_post)
      ? [
          { phase: t("Before", "干预前"), treated: v.treated_pre, control: v.control_pre },
          { phase: t("After", "干预后"), treated: v.treated_post, control: v.control_post },
        ]
      : null;
  return (
    <div className="mt-3 rounded-lg bg-ink-50 p-3" data-testid="effect-card">
      <div className="flex flex-wrap items-center gap-2">
        <span data-testid="effect-verdict">
          <Badge tone={verdict.tone}>{displayText(verdict.label)}</Badge>
        </span>
        <span className="text-xs text-ink-500">{t("Difference-in-differences · effect", "双重差分 · 效果")} {rangeText(est.effect)}</span>
      </div>
      <p className="mt-1 text-xs tabular text-ink-600">
        {t("Treated change", "干预组变化")} {formatSigned(est.treated_change)} {t("· control change", "· 对照组变化")} {formatSigned(est.control_change)}
      </p>
      <p className="mt-2 text-sm leading-relaxed text-ink-800">{displayText(est.explanation)}</p>
      {chart && (
        <div className="mt-3 h-36" role="img" aria-label={t("Before and after, treated sites and control sites", "干预前后，干预中心与对照中心")}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chart} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
              <CartesianGrid stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="phase" tick={{ fontSize: 12, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 11, fill: "#64748b" }} width={40} />
              <Tooltip />
              <Legend />
              <Line type="linear" dataKey="treated" name={t("Treated", "干预中心")} stroke="#0f766e" strokeWidth={2} dot isAnimationActive={false} />
              <Line type="linear" dataKey="control" name={t("Control sites", "对照中心")} stroke="#64748b" strokeWidth={2} strokeDasharray="4 3" dot isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {effect.control_units && effect.control_units.length > 0 && (
        <p className="mt-1 text-[11px] text-ink-500">
          {t("Controls (", "对照组（")}{displayText(effect.control_tier || t("matched", "匹配"))}): {effect.control_units.join(", ")}
        </p>
      )}
    </div>
  );
}

function formatSigned(n: number | null | undefined): string {
  if (!isNum(n)) return translate("unknown", "未知");
  const rounded = Math.abs(n) >= 10 ? Math.round(n) : Math.round(n * 10) / 10;
  if (rounded === 0) return "0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded)}`;
}

/** The prediction saved when the action was planned, and how the observed effect compares with it. */
function PredictionCard({ effect }: { effect: EffectDetail }) {
  const t = useTranslation();
  const exp = effect.expectation;
  const rec = effect.reconciliation;
  if (!exp) return null;
  const observed = rec?.observed;
  return (
    <div className="mt-3 rounded-lg border border-ink-200 p-3" data-testid="prediction-card">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-xs font-semibold text-ink-800">{t(`Prediction saved ${exp.computed_at}`, `预测保存于 ${exp.computed_at}`)}</h3>
        {rec && (
          <span data-testid="reconcile-verdict">
            <Badge tone={reconcileTone(rec.verdict)}>{reconcileLabel(rec.verdict)}</Badge>
          </span>
        )}
      </div>
      {rec?.needs_replan && (
        <p role="alert" className="mt-2 rounded-md border border-worse-200 bg-worse-50 px-3 py-2 text-xs text-worse-900" data-testid="replan-banner">
          {t(
            `Below its predicted effect after ${rec.post_weeks} weeks. The alert was reopened: plan a different action from it.`,
            `运行 ${rec.post_weeks} 周后低于预测效果。警报已重新打开，请从中规划其他行动。`,
          )}
        </p>
      )}
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        <div><dt className="text-ink-500">{t("Time saved", "节省时间")}</dt><dd className="tabular text-ink-800">{predictedText(exp.delay_saved_days)}</dd></div>
        <div><dt className="text-ink-500">{t("Cost avoided", "避免的成本")}</dt><dd className="tabular text-ink-800">{predictedText(exp.cost_avoided_usd)}</dd></div>
        <div><dt className="text-ink-500">{t("Action cost", "行动成本")}</dt><dd className="tabular text-ink-800">{predictedText(exp.action_cost_usd)}</dd></div>
        <div><dt className="text-ink-500">{t("Net value", "净价值")}</dt><dd className="tabular font-semibold text-ink-900">{predictedText(exp.net_usd)}</dd></div>
      </dl>
      {rec && (
        <div className="mt-2 border-t border-ink-100 pt-2 text-xs text-ink-700" data-testid="reconcile-detail">
          <p className="tabular">
            {displayText(rec.metric_label)}: {t("predicted", "预测")} {rec.predicted ? `${formatSigned(rec.predicted.p50)} (${formatSigned(rec.predicted.p10)} – ${formatSigned(rec.predicted.p90)})` : "—"}
            {" · "}
            {t("observed", "观测")} {observed ? `${formatSigned(observed.p50)} (${t("95% interval", "95% 区间")} ${formatSigned(observed.ci95[0])} – ${formatSigned(observed.ci95[1])})` : "—"}
            {rec.post_weeks > 0 ? ` · ${t(`${rec.post_weeks} weeks observed`, `已观测 ${rec.post_weeks} 周`)}` : ""}
          </p>
          <p className="mt-1 leading-relaxed">{displayText(rec.explanation)}</p>
          <p className="mt-1 text-[11px] text-ink-500">{displayText(rec.basis)} {displayText(rec.model_label)}</p>
        </div>
      )}
    </div>
  );
}

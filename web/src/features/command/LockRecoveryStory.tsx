import { displayText } from "./displayText";
import { useTranslation } from "@/app/i18n";
import { useReducer } from "react";
import { Badge } from "@/app/ui";
import {
  daysBetween, initialReplay, lockDate, lockEvidence, lockStory,
  replayEffect, replayForecast, replayReducer, type ReplayEffect,
} from "./lockStory";
import { VERDICT } from "./present";

export function LockRecoveryStory() {
  const t = useTranslation();
  const [state, dispatch] = useReducer(replayReducer, initialReplay);
  const forecast = replayForecast(state);
  const recovered = forecast.p50 <= lockStory.plan.p90;
  const pending = state.started.some((id) => !state.observed.includes(id));
  const complete = state.observed.length === lockStory.actions.length;
  const step = complete ? 2 : state.stage === "risk" ? 0 : 1;

  return (
    <section className="card overflow-hidden" aria-labelledby="lock-story-title" data-testid="lock-recovery-story" data-simulated={lockStory.simulated}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-200 bg-ink-50 p-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-accent-700">{t("Guided simulated replay ·", "引导式模拟演示 ·")} {lockEvidence.site_count} {t("sites · seed", "个中心 · 随机种子")} {lockEvidence.seed}</p>
          <h2 id="lock-story-title" className="mt-1 text-xl font-semibold text-ink-900">{displayText(lockStory.title)}</h2>
          <p className="mt-1 max-w-3xl text-sm text-ink-600">{t("A slipping lock date. Two actions. Check which improvement holds up against controls.", "锁库日期正在推迟。实施两项行动，并对照比较哪项改善经得起验证。")}</p>
        </div>
        {state.stage !== "risk" && <button type="button" className="btn-secondary" onClick={() => dispatch({ type: "reset" })}>{t("Replay from the start", "从头重新演示")}</button>}
      </header>

      <div className="space-y-4 p-4">
        <ol className="grid gap-2 text-sm sm:grid-cols-3" aria-label={t("Demo sequence", "演示步骤")}>
          {[t("See lock slip beyond the plan band", "查看锁库日期超出计划范围"), t("Run the two interventions", "实施两项干预"), t("Compare the two judgments", "比较两项效果判断")].map((label, index) => (
            <li key={label} aria-current={step === index ? "step" : undefined} className={`rounded-lg border px-3 py-2 ${step === index ? "border-accent-300 bg-accent-50 font-semibold text-accent-900" : "border-ink-200 text-ink-600"}`}>
              <span className="mr-2 tabular">{index + 1}.</span>{label}
            </li>
          ))}
        </ol>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,0.8fr)]">
          <div className="rounded-lg border border-ink-200 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-ink-500">{t("Database lock ·", "数据库锁定 ·")} {displayText(lockStory.forecast_source)}</p>
            <div className="mt-2 flex flex-wrap items-center gap-3" role="status" data-testid="story-lock-forecast">
              <p className="text-2xl font-semibold tabular text-ink-900">{lockDate(forecast.p50)}</p>
              <Badge tone={recovered ? "better" : "worse"}>{recovered ? t("Back inside planned range", "已回到计划范围") : t("Outside planned range", "超出计划范围")}</Badge>
            </div>
            <p className="mt-2 text-sm text-ink-700" data-testid="story-lock-shift">
              {recovered
                ? t(`${daysBetween(forecast.p50, lockStory.slipped.p50)} days recovered from the slipped forecast.`, `较推迟后的预测提前了 ${daysBetween(forecast.p50, lockStory.slipped.p50)} 天。`)
                : t(`${daysBetween(lockStory.plan.p90, forecast.p50)} days beyond the upper edge of the planned range.`, `超出计划范围上限 ${daysBetween(lockStory.plan.p90, forecast.p50)} 天。`)}
            </p>
            <LockTimeline forecast={forecast.p50} recovered={recovered} />
            <p className="text-xs text-ink-600">{t("Planned P10–P90:", "计划 P10–P90：")} {lockDate(lockStory.plan.p10)} – {lockDate(lockStory.plan.p90)}.</p>
            <p className="mt-1 text-xs text-ink-600">{t("Baseline P50", "基线 P50")} {lockDate(lockStory.plan.p50)} {t("→ slipped P50", "→ 推迟后 P50")} {lockDate(lockStory.slipped.p50)}{recovered ? t(` → recovered P50 ${lockDate(forecast.p50)}`, ` → 恢复后 P50 ${lockDate(forecast.p50)}`) : ""}.</p>
          </div>
          <div className="space-y-3 text-sm leading-relaxed text-ink-700">
            <h3 className="font-semibold text-ink-900">{t("Why lock is slipping", "锁库推迟的原因")}</h3>
            <p>{displayText(lockStory.risk)}</p>
            <p className="rounded-lg bg-ink-50 p-3 text-xs" data-testid="story-forecast-note">{displayText(lockStory.forecast_note)}</p>
            <p className="text-xs text-ink-500">{t("Replay actions reveal recorded evidence at the original intervention dates. This rehearsal has its own steps; it does not advance the operations feed clock.", "演示行动会展示原始干预日期记录的证据。本次演练使用独立步骤，不会推进运营数据流时钟。")}</p>
          </div>
        </div>

        {state.stage === "risk" ? (
          <button type="button" className="btn-primary" onClick={() => dispatch({ type: "review" })}>{t("Review two interventions", "查看两项干预")}</button>
        ) : (
          <section aria-labelledby="story-actions-title">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 id="story-actions-title" className="font-semibold text-ink-900">{complete ? t("Two improvements, different judgments", "两项改善，不同判断") : t("Choose an action, then inspect follow-up", "选择行动，然后查看随访结果")}</h3>
                <p className="mt-1 text-xs text-ink-600">{t("A falling metric alone is not enough. Compare treated sites with matched controls.", "仅凭指标下降不足以判断效果。请比较干预中心与匹配对照中心。")}</p>
              </div>
              <button type="button" className="btn-primary" disabled={!pending} onClick={() => dispatch({ type: "observe" })}>{t("Read follow-up evidence", "查看随访证据")}</button>
            </div>
            <div className="grid items-start gap-4 md:grid-cols-2" data-testid="story-comparison">
              {lockStory.actions.map((action) => {
                const item = lockEvidence.cases.find((c) => c.truth_id === action.id)!;
                const effect = replayEffect(state, item);
                const started = state.started.includes(action.id);
                const observed = state.observed.includes(action.id);
                const supportedResult = effect?.estimate.verdict ===
                  (action.id === lockStory.recovery_intervention_id ? "likely_worked" : "likely_coincidence");
                return (
                  <article key={action.id} className="min-w-0 rounded-lg border border-ink-200 p-4" aria-labelledby={`story-title-${action.id}`} data-testid={`story-intervention-${action.id}`}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h4 id={`story-title-${action.id}`} className="font-semibold text-ink-900">{displayText(action.title)}</h4>
                      <Badge tone={observed ? "accent" : "neutral"}>{observed ? t("Reviewed", "已查看") : started ? t("Observing", "观察中") : t("Planned", "已规划")}</Badge>
                    </div>
                    <p className="mt-2 text-xs text-ink-600">{t("Owner:", "负责人：")} {displayText(action.owner)} · {item.intervention.target_site_ids.length} {t("target sites", "个目标中心")}</p>
                    <p className="mt-2 text-sm text-ink-800">{displayText(action.task)}</p>
                    <p className="mt-2 text-xs text-ink-600">{displayText(action.hypothesis)}</p>
                    {!started && <button type="button" className="btn-secondary mt-3" onClick={() => dispatch({ type: "start", id: action.id })}>{displayText(action.button_label)}</button>}
                    {effect && <ReplayJudgment effect={effect} />}
                    {observed && supportedResult && <p className="mt-3 text-sm text-ink-800">{displayText(action.result)}</p>}
                  </article>
                );
              })}
            </div>
            {complete && recovered && <p role="status" className="mt-3 rounded-lg bg-accent-50 p-3 text-sm text-accent-900">{t("Under this scenario's cleaning assumption, the evidence for eCRF training supports bringing lock back into range. Check each judgment against its controls before assigning credit.", "根据此情景的数据清理假设，eCRF 培训证据支持将锁库日期恢复到计划范围。归因之前，请对照相应对照组验证每项判断。")}</p>}
          </section>
        )}
      </div>
    </section>
  );
}

function LockTimeline({ forecast, recovered }: { forecast: string; recovered: boolean }) {
  const t = useTranslation();
  const span = daysBetween(lockStory.plan.p10, lockStory.slipped.p90);
  const x = (date: string) => 18 + daysBetween(lockStory.plan.p10, date) / span * 324;
  return (
    <svg viewBox="0 0 360 64" className="my-3 h-16 w-full" role="img" aria-label={t(`Planned lock range ${lockDate(lockStory.plan.p10)} to ${lockDate(lockStory.plan.p90)}; current P50 ${lockDate(forecast)}, ${recovered ? "inside" : "outside"} the range`, `计划锁库范围 ${lockDate(lockStory.plan.p10)} 至 ${lockDate(lockStory.plan.p90)}；当前 P50 ${lockDate(forecast)}，${recovered ? "位于" : "超出"}范围`)}>
      <path d="M18 31H342" stroke="#cbd5e1" />
      <rect x={x(lockStory.plan.p10)} y="23" width={x(lockStory.plan.p90) - x(lockStory.plan.p10)} height="16" rx="4" fill="#cbd5e1" />
      <circle cx={x(lockStory.plan.p50)} cy="31" r="4" fill="#64748b" />
      <path d={`M${x(forecast)} 20l8 11-8 11-8-11Z`} fill={recovered ? "#0f766e" : "#b91c1c"} />
      <text x={x(lockStory.plan.p50)} y="57" fontSize="11" textAnchor="middle" fill="#475569">{t("Planned range", "计划范围")}</text>
      <text x={x(forecast)} y="12" fontSize="11" textAnchor="middle" fill={recovered ? "#0f766e" : "#b91c1c"}>{t("Current P50", "当前 P50")}</text>
    </svg>
  );
}

function ReplayJudgment({ effect }: { effect: ReplayEffect }) {
  const t = useTranslation();
  const verdict = VERDICT[effect.estimate.verdict];
  const values = effect.values;
  return (
    <div className="mt-3 border-t border-ink-200 pt-3" aria-live="polite">
      <span data-testid="story-verdict" data-verdict={effect.estimate.verdict}><Badge tone={verdict.tone}>{displayText(verdict.label)}</Badge></span>
      {values && values.treated_pre != null && values.treated_post != null && values.control_pre != null && values.control_post != null ? (
        <>
          <table className="mt-3 w-full text-left text-sm tabular">
            <caption className="mb-2 text-left text-xs font-semibold text-ink-700">{displayText(effect.metric_label ?? "")} {t("(%) · lower is better", "（%）· 越低越好")}</caption>
            <thead><tr className="text-xs text-ink-500"><th scope="col">{t("Sites", "中心")}</th><th scope="col">{t("Before", "干预前")}</th><th scope="col">{t("After", "干预后")}</th></tr></thead>
            <tbody>
              <tr><th scope="row" className="py-1 font-medium">{t("Treated", "干预中心")}</th><td>{values.treated_pre.toFixed(1)}%</td><td>{values.treated_post.toFixed(1)}%</td></tr>
              <tr><th scope="row" className="py-1 font-medium">{t("Matched controls", "匹配对照中心")}</th><td>{values.control_pre.toFixed(1)}%</td><td>{values.control_post.toFixed(1)}%</td></tr>
            </tbody>
          </table>
          <p className="mt-2 text-xs text-ink-600">{t("Difference-in-differences:", "双重差分：")} {values.did?.toFixed(1)} {t("percentage points", "个百分点")}{effect.ci95 ? t(` · 95% interval ${effect.ci95[0].toFixed(1)} to ${effect.ci95[1].toFixed(1)}`, ` · 95% 区间 ${effect.ci95[0].toFixed(1)} 至 ${effect.ci95[1].toFixed(1)}`) : ""}.</p>
          <p className="mt-1 text-xs text-ink-500">{effect.pre_window.weeks} {t("weeks before ·", "周干预前 ·")} {effect.post_window.weeks} {t("weeks after ·", "周干预后 ·")} {effect.control_units?.length} {t("controls", "个对照中心")}</p>
          <details className="mt-2 text-xs leading-relaxed text-ink-600">
            <summary className="cursor-pointer font-semibold">{t("Evidence and comparison window", "证据与比较时间窗口")}</summary>
            <p className="mt-2">{t("Before:", "干预前：")} {effect.pre_window.start} – {effect.pre_window.end}{t(". After:", "。干预后：")} {effect.post_window.start} – {effect.post_window.end}.</p>
            <p className="mt-2">{displayText(effect.estimate.explanation)}</p>
          </details>
        </>
      ) : <p className="mt-2 text-sm text-ink-600">{displayText(effect.estimate.explanation)}</p>}
    </div>
  );
}

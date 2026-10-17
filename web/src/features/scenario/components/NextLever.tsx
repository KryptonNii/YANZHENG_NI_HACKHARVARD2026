import { useTranslation, translate as t } from "@/app/i18n";
import { localizeCopy } from "@/app/localize";
import { useEffect, useId, useState } from "react";
import { isAbort, request } from "@/app/api/client";
import type { Levers, MetricRange, ProcedureEndpointRole } from "@/app/contracts";

// Advice owns its response types; it does not extend the shared trial contracts.
type AdviceMetrics = Record<"cost_usd" | "site_staff_hours" | "duration_months", MetricRange>;
export type CandidateKind = "lever" | "procedure_removal";
export interface ProcedureRef { code: string; label: string; endpoint_roles: ProcedureEndpointRole[] }

export interface LeverRecommendation {
  id: string;
  label: string;
  kind: CandidateKind;
  levers: Partial<Levers>;
  delta: AdviceMetrics;
  reason: string;
  stockout_probability: number | null;
  procedure: ProcedureRef | null;
}

export interface RejectedCandidate {
  id: string;
  label: string;
  kind: CandidateKind;
  levers: Partial<Levers>;
  reason: string;
  delta: AdviceMetrics | null;
  procedure: ProcedureRef | null;
}

export interface StressScenario {
  id: string;
  label: string;
  tag: "assumption";
  levers: Pick<Levers, "enrollment_rate_multiplier">;
  delta: AdviceMetrics | null;
  stockout_probability: number | null;
  reason: string;
}

export interface NextLeverData {
  design_id: string;
  design_version: number;
  design_hash: string;
  parameter_set_version: string;
  seed: number;
  /** Ranking draws for the baseline, every candidate and stress scenario. */
  draws: number;
  /** The formal scenario's own draw count; advice never changes it. */
  scenario_draws: number;
  sampling_note: string;
  delta_method: string;
  baseline: AdviceMetrics;
  current_levers: Levers;
  policy: { max_duration_increase_months: number; max_stockout_probability: number; max_recommendations: number; note: string };
  recommendations: LeverRecommendation[];
  rejected: RejectedCandidate[];
  stress_scenarios: StressScenario[];
  blocked: { code: string; endpoint_roles: ProcedureEndpointRole[]; reason: string }[];
  warnings: string[];
}

export interface NextLeverProps {
  designId: string;
  designVersion: number;
  currentLevers: Levers;
  onPreview?: (patch: Partial<Levers>) => void;
}

const MAX_RECOMMENDATIONS = 3;
function adviceLabel(label: string): string {
  const labels: Record<string, string> = {
    "50% remote monitoring": "50% 远程监查",
    "50% local laboratory testing": "50% 本地实验室检测",
    "On-demand drug supply": "按需药物供应",
    "Move eligible visits home": "将适合的访视改为上门访视",
    "Review visit schedule": "审核访视计划",
    "Forecast required": "需要预测结果",
  };
  if (labels[label]) return t(label, labels[label]);
  const countries = /^Add (\d+) assumed countr(?:y|ies)$/.exec(label);
  if (countries) return t(label, `添加 ${countries[1]} 个假设国家`);
  const enrollment = /^Enrollment (\d+)% slower than your current selection$/.exec(label);
  if (enrollment) return t(label, `入组速度比当前选择慢 ${enrollment[1]}%`);
  if (label.startsWith("Remove ")) return t(label, `移除 ${label.slice(7)}`);
  if (label.startsWith("Exclude ")) return t(label, `排除 ${label.slice(8)}`);
  return label;
}

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2, signDisplay: "exceptZero" });
const count = new Intl.NumberFormat("en-US");
const percent = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 2 });
const deltaText = (value: number | null) => value === null ? t("Not estimated", "未估算") : number.format(value);
const riskText = (value: number | null) => value === null ? t("Not estimated", "未估算") : percent.format(value);
const metrics = [
  ["cost_usd", "Cost (USD)"],
  ["site_staff_hours", "Site staff hours"],
  ["duration_months", "Duration (months)"],
] as const;

// Lever arrays are selections, so order does not change the scenario. Canonical keys also
// prevent object insertion order in a JSON response from producing a false mismatch.
function leverKey(levers: Levers): string {
  return JSON.stringify(Object.fromEntries(Object.entries(levers).sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => [key, Array.isArray(value) ? [...value].sort() : value])));
}

const addedRemovals = (patch: Partial<Levers>, current: Levers) =>
  (patch.removed_procedures ?? []).filter((code) => !current.removed_procedures.includes(code));

function describePatch(patch: Partial<Levers>, current: Levers): string {
  const changes: string[] = [];
  if (patch.remote_monitoring_share !== undefined) changes.push(t(`${percent.format(patch.remote_monitoring_share)} remote monitoring`, `${percent.format(patch.remote_monitoring_share)} 远程监查`));
  if (patch.local_lab_share !== undefined) changes.push(t(`${percent.format(patch.local_lab_share)} local laboratory testing`, `${percent.format(patch.local_lab_share)} 本地实验室检测`));
  if (patch.drug_supply_strategy !== undefined) changes.push(patch.drug_supply_strategy === "on_demand" ? t("on-demand drug supply", "按需药物供应") : t("upfront drug supply", "预先药物供应"));
  if (patch.home_visit_numbers !== undefined) changes.push(t(`home visits: ${patch.home_visit_numbers.join(", ") || "none"}`, `上门访视：${patch.home_visit_numbers.join("、") || "无"}`));
  if (patch.remote_visit_numbers !== undefined) changes.push(t(`telehealth visits: ${patch.remote_visit_numbers.join(", ") || "none"}`, `远程访视：${patch.remote_visit_numbers.join("、") || "无"}`));
  if (patch.excluded_site_ids !== undefined) changes.push(t(`excluded sites: ${patch.excluded_site_ids.join(", ") || "none"}`, `已排除研究中心：${patch.excluded_site_ids.join("、") || "无"}`));
  if (patch.added_country_count !== undefined) changes.push(t(`${patch.added_country_count} assumed added countries (assumptions, not registry sites)`, `新增 ${patch.added_country_count} 个假设国家（假设数据，非注册研究中心）`));
  for (const code of addedRemovals(patch, current)) changes.push(t(`remove procedure ${code}`, `移除检查项目 ${code}`));
  return changes.join("; ") || t("Update the selected scenario settings", "更新所选方案设置");
}

// Defense in depth: the server already screens candidates; never offer a preview that could slow
// enrollment, drop an existing choice, or remove anything but one unblocked not_linked procedure.
function isSafeRecommendation(item: LeverRecommendation, current: Levers, blocked: Set<string>): boolean {
  const { levers } = item;
  if (levers.enrollment_rate_multiplier !== undefined) return false;
  const keepsSelections = (["home_visit_numbers", "remote_visit_numbers", "excluded_site_ids"] as const).every((key) =>
    levers[key] === undefined || current[key].every((value) => levers[key]?.some((next) => next === value)));
  if (!keepsSelections) return false;
  const removed = levers.removed_procedures;
  if (removed === undefined) return item.kind !== "procedure_removal";
  const added = addedRemovals(levers, current);
  const roles = item.procedure?.endpoint_roles ?? [];
  return item.kind === "procedure_removal" && Object.keys(levers).length === 1 && added.length === 1 &&
    current.removed_procedures.every((code) => removed.includes(code)) && item.procedure?.code === added[0] &&
    roles.length > 0 && roles.every((role) => role === "not_linked") && !blocked.has(added[0]);
}

function useLeverAdvice(designId: string, designVersion: number, currentKey: string) {
  const [result, setResult] = useState<NextLeverData>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const valid = Number.isInteger(designVersion) && designVersion > 0;

  useEffect(() => {
    if (!valid) return;
    const controller = new AbortController();
    let active = true;
    const query = new URLSearchParams({ design_id: designId, design_version: String(designVersion), current_levers: currentKey });
    const timer = window.setTimeout(() => {
      request<NextLeverData>("GET", `/scenarios/advice?${query}`, { signal: controller.signal, silent: true })
      .then((data) => {
        if (!active) return;
        if (data.design_id !== designId || data.design_version !== designVersion) {
          throw new Error(t("The advice does not match the saved design version on screen.", "建议与当前显示的已保存设计版本不匹配。"));
        }
        if (!data.current_levers || leverKey(data.current_levers) !== currentKey) {
          throw new Error(t("The advice does not match the current scenario choices. Retry to compare these choices.", "建议与当前方案选择不匹配。请重试以比较当前选择。"));
        }
        if (![data.recommendations, data.rejected, data.stress_scenarios, data.blocked, data.warnings].every(Array.isArray)) {
          throw new Error(t("The advice response is incomplete. Retry advice.", "建议响应不完整。请重试。"));
        }
        setResult(data);
      })
      .catch((reason: unknown) => {
        if (active && !isAbort(reason)) setError(reason instanceof Error ? reason.message : t("Lever advice is unavailable.", "调整建议暂不可用。"));
      });
    }, 250);
    return () => { active = false; window.clearTimeout(timer); controller.abort(); };
  }, [designId, designVersion, currentKey, valid, attempt]);

  return { valid, result, error, retry: () => { setError(undefined); setAttempt((value) => value + 1); } };
}

export function NextLever(props: NextLeverProps) {
  useTranslation();
  const currentKey = leverKey(props.currentLevers);
  return <PinnedNextLever key={JSON.stringify([props.designId, props.designVersion, currentKey])} {...props} currentKey={currentKey} />;
}

function PinnedNextLever({ designId, designVersion, currentLevers, currentKey, onPreview }: NextLeverProps & { currentKey: string }) {
  useTranslation();
  const headingId = useId();
  const { valid, result, error, retry } = useLeverAdvice(designId, designVersion, currentKey);
  const blockedCodes = new Set(result?.blocked.map((item) => item.code));
  const recommendations = result?.recommendations
    .filter((item) => isSafeRecommendation(item, currentLevers, blockedCodes)).slice(0, MAX_RECOMMENDATIONS) ?? [];

  return (
    <section aria-labelledby={headingId} className="space-y-4 rounded-xl border border-ink-200 bg-white p-5">
      <h2 id={headingId} className="text-lg font-semibold">{t("Which lever could reduce cost next?", "下一步可通过哪项调整降低费用？")}</h2>
      <p className="text-sm text-ink-600">
        {t("Each candidate is one additional change to your current scenario on design v", "每个候选项都在当前设计版本的方案上增加一项调整，设计版本 v")}{designVersion}{t(". Ranked relative to your current scenario (the baseline) by median cost change, then site staff hours.", "。以当前方案为基线，先按费用变化中位数排序，再按研究中心人员工时排序。")}
      </p>
      {!valid && <p role="alert">{t("A saved design version is required (design_version_required).", "需要已保存的设计版本（design_version_required）。")}</p>}
      {valid && !result && !error && <p role="status">{t("Comparing existing levers…", "正在比较现有调整项…")}</p>}
      {error && <div role="alert">
        <p>{localizeCopy(error)}</p>
        <button type="button" onClick={retry}>{t("Retry advice", "重新获取建议")}</button>
      </div>}
      {result && <>
        <SamplingAndPolicy result={result} />
        {recommendations.length > 0 ? <ol aria-label={t("Recommended levers", "推荐调整项")} className="list-inside list-decimal space-y-4">
          {recommendations.map((item) => <RecommendationCard key={item.id} item={item} current={currentLevers} onPreview={onPreview} />)}
        </ol> : <p role="status">{t("No recommendation meets the model constraints for your current choices. Review the reasons below before changing the scenario.", "没有建议符合当前选择下的模型约束。更改方案前，请查看下方原因。")}</p>}
        {onPreview && <p className="text-xs text-ink-600">{t("Preview updates the scenario controls and recalculates the results. Save the scenario separately to keep it.", "预览会更新方案控制项并重新计算结果。需另行保存方案以保留更改。")}</p>}
        <StressScenarios items={result.stress_scenarios} />
        <RejectedList items={result.rejected} />
        <BlockedList items={result.blocked} />
        <AdviceWarnings items={result.warnings} />
      </>}
    </section>
  );
}

function SamplingAndPolicy({ result }: { result: NextLeverData }) {
  useTranslation();
  const { policy } = result;
  return <>
    <p className="text-sm">
      {t("Ranking uses seed", "排序使用随机种子")} {result.seed} {t("and", "及")} {count.format(result.draws)} {t("draws. The formal scenario results use their own draw count (", "次抽样。正式方案结果采用各自的抽样次数（")}{count.format(result.scenario_draws)}{t("), so they can differ.", "），因此结果可能不同。")}
    </p>
    <p className="text-xs text-ink-600">{localizeCopy(result.sampling_note)}</p>
    <div className="rounded-lg bg-ink-50 p-3 text-sm" aria-label={t("Recommendation policy", "推荐规则")}>
      <p>{t("Maximum duration P50 increase:", "持续时间 P50 最大增幅：")} {policy.max_duration_increase_months} {t("months.", "个月。")}
        {" "}{t("Maximum modeled stockout probability:", "模型允许的最高缺货概率：")} {percent.format(policy.max_stockout_probability)}.</p>
      <p>{localizeCopy(policy.note)}</p>
      <p>{t("These model constraints do not establish clinical safety or protocol acceptability.", "这些模型约束不代表已确认临床安全性或试验方案可接受性。")}</p>
    </div>
    <p className="text-sm">{t("Changes are candidate minus your current scenario; negative values are reductions.", "变化值为候选方案减去当前方案；负值表示减少。")}</p>
  </>;
}

function DeltaTable({ label, delta }: { label: string; delta: AdviceMetrics | null }) {
  useTranslation();
  if (!delta) return <p className="my-2 text-sm">{t("Changes from current scenario: Not estimated.", "相对于当前方案的变化：未估算。")}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{label}{t(": changes from current scenario", "：相对于当前方案的变化")}</caption>
        <thead><tr>
          <th scope="col">{t("Metric change", "指标变化")}</th><th scope="col">P10</th>
          <th scope="col">P50</th><th scope="col">P90</th>
        </tr></thead>
        <tbody>{metrics.map(([metric, name]) => <tr key={metric}>
          <th scope="row">{t(name, metric === "cost_usd" ? "费用（美元）" : metric === "site_staff_hours" ? "研究中心人员工时" : "持续时间（月）")}</th>
          {(["p10", "p50", "p90"] as const).map((percentile) => <td key={percentile}>{deltaText(delta[metric][percentile])}</td>)}
        </tr>)}</tbody>
      </table>
    </div>
  );
}

const NotClinicalApproval = ({ code }: { code: string }) => <span className="text-caution-900">
  <strong>{t("Not clinical approval:", "不代表临床批准：")}</strong> {t("removing", "移除")} <code>{code}</code> {t("still requires manual protocol review of safety, eligibility and treatment needs.", "仍需人工审核试验方案，评估安全性、入选资格及治疗需求。")}
</span>;

function RecommendationCard({ item, current, onPreview }: { item: LeverRecommendation; current: Levers; onPreview?: NextLeverProps["onPreview"] }) {
  useTranslation();
  return (
    <li className="rounded-lg border border-ink-200 p-4">
      <h3 className="inline font-semibold">{adviceLabel(item.label)}</h3>
      <p className="my-2 text-sm">{localizeCopy(item.reason)}</p>
      {item.kind === "procedure_removal" && item.procedure && <p className="my-2 text-sm"><NotClinicalApproval code={item.procedure.code} /></p>}
      <DeltaTable label={adviceLabel(item.label)} delta={item.delta} />
      <p className="mt-2 text-sm">{t("Modeled stockout probability:", "模型估算的缺货概率：")} {riskText(item.stockout_probability)}.</p>
      <p className="mt-2 text-sm">{t("Preview changes:", "预览更改：")} {describePatch(item.levers, current)}.</p>
      {onPreview && <button type="button" className="btn-secondary mt-2" onClick={() => onPreview(item.levers)}>{t("Preview this change", "预览此更改")}</button>}
    </li>
  );
}

// Slower enrollment is a pressure test of the current scenario: never ranked, never previewed.
function StressScenarios({ items }: { items: StressScenario[] }) {
  useTranslation();
  if (!items.length) return null;
  return (
    <div>
      <h3 className="font-semibold">{t("Stress test (assumption)", "压力测试（假设）")}</h3>
      <ul aria-label={t("Stress scenarios", "压力测试场景")} className="mt-2 space-y-4">
        {items.map((item) => <li key={item.id} className="rounded-lg border border-dashed border-caution-200 p-4">
          <h4 className="inline font-semibold">{adviceLabel(item.label)}</h4>{" "}
          <span className="inline-block rounded bg-caution-100 px-1.5 text-[11px] font-bold uppercase tracking-wide text-caution-900">{t("assumption", "假设")}</span>
          <p className="my-2 text-sm">{localizeCopy(item.reason)}</p>
          <p className="my-2 text-sm">
            {t("Assumed enrollment rate:", "假设入组速度：")} {percent.format(item.levers.enrollment_rate_multiplier)} {t("of plan. This tests your current scenario; it is not a recommendation.", "（相对于计划）。此项用于测试当前方案，不是推荐建议。")}
          </p>
          <DeltaTable label={adviceLabel(item.label)} delta={item.delta} />
          <p className="mt-2 text-sm">{t("Modeled stockout probability:", "模型估算的缺货概率：")} {riskText(item.stockout_probability)}.</p>
        </li>)}
      </ul>
    </div>
  );
}

function RejectedList({ items }: { items: RejectedCandidate[] }) {
  useTranslation();
  if (!items.length) return null;
  return (
    <div>
      <h3 className="font-semibold">{t("Why other changes were not recommended", "其他更改未被推荐的原因")}</h3>
      <ul aria-label={t("Rejected changes", "未推荐的更改")} className="mt-2 space-y-2 text-sm">
        {items.map((item) => <li key={item.id}>
          <strong>{adviceLabel(item.label)}:</strong> {localizeCopy(item.reason)}
          {item.kind === "procedure_removal" && item.procedure && <> <NotClinicalApproval code={item.procedure.code} /></>}
        </li>)}
      </ul>
    </div>
  );
}

function BlockedList({ items }: { items: NextLeverData["blocked"] }) {
  useTranslation();
  return (
    <div>
      <h3 className="font-semibold">{t("Blocked procedure removals", "禁止移除的检查项目")}</h3>
      {items.length ? <ul aria-label={t("Blocked procedures", "禁止移除的检查项目")} className="mt-2 space-y-2 text-sm">
        {items.map((item) => <li key={item.code}><code>{item.code}</code>: {localizeCopy(item.reason)}</li>)}
      </ul> : <p className="text-sm">
        {t("No procedure removal is blocked by endpoint linkage. Linkage alone does not show a procedure is unnecessary; any removal still requires manual protocol review of safety, eligibility and treatment needs.", "没有检查项目因终点关联而被禁止移除。仅凭关联信息无法判断检查项目是否必要；任何移除操作仍需人工审核试验方案，评估安全性、入选资格及治疗需求。")}
      </p>}
    </div>
  );
}

function AdviceWarnings({ items }: { items: string[] }) {
  useTranslation();
  if (!items.length) return null;
  return <ul aria-label={t("Advice warnings", "建议警告")} className="text-sm text-ink-600">
    {items.map((warning) => <li key={warning}>{localizeCopy(warning)}</li>)}
  </ul>;
}

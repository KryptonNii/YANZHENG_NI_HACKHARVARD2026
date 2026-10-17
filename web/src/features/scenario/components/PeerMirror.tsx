import { useTranslation, translate as t } from "@/app/i18n";
import { useEffect, useId, useState } from "react";
import { isAbort, request } from "@/app/api/client";

// Local response types: Peer Mirror does not extend the shared trial contracts.
type Metric = "primary_outcomes" | "total_outcomes" | "inclusion_criteria" |
  "exclusion_criteria" | "eligibility_criteria" | "countries" | "sites" | "enrollment_target";
type Counts = Record<Metric, number | null>;
type Range = { p10: number | null; p50: number | null; p90: number | null; unit: "usd" | "hours" };
type CostMetrics = { cost_usd: Range; site_staff_hours: Range };

export interface PeerRow {
  metric: Metric;
  label: string;
  own_count: number | null;
  cohort_n: number;
  available_n: number;
  phase: string | null;
  condition_group: string | null;
  source_file: string | null;
  peer_source_files: string[];
  status: "ok" | "insufficient_peers" | "not_reported" | "record_not_cached";
  peer_median: number | null;
  percentile: number | null;
  comparison: "more" | "fewer" | "same" | null;
  question: string;
  note: string;
}

export interface PeerMirrorData {
  design_id: string;
  design_version: number;
  design_hash: string;
  registry_id: string | null;
  phase: string | null;
  condition_group: string | null;
  cohort_n: number;
  source_file: string | null;
  peer_source_files: string[];
  own_counts: Counts;
  enrollment_reported: number | null;
  enrollment_type: string | null;
  rows: PeerRow[];
  methods: Record<string, string>;
  interpretation: string;
  available_procedures: { code: string; labels: string[]; occurrences: number; visit_numbers: number[] }[];
  cost_comparison: {
    design_id: string;
    design_version: number;
    design_hash: string;
    removed_procedures: string[];
    baseline: CostMetrics;
    counterfactual: CostMetrics;
    delta: CostMetrics;
    delta_method: string;
    parameter_set_version: string;
    seed: number;
    draws: number;
    warnings: string[];
  } | null;
  cost_reason: string | null;
}

export interface PeerMirrorProps {
  designId: string;
  designVersion: number;
  /** Controlled by the scenario's existing Design levers. */
  removedProcedures?: readonly string[];
}

const numeric = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });
const count = (value: number | null) => value === null ? t("Not reported", "未报告") : numeric.format(value);
const estimate = (value: number | null | undefined) => value == null ? t("Not calculated", "未计算") : numeric.format(value);
const direction = { get more() { return t("More than", "高于"); }, get fewer() { return t("Fewer than", "低于"); }, get same() { return t("Same as", "等于"); } };
const dimensionLabels: Record<Metric, string> = {
  primary_outcomes: "主要结局", total_outcomes: "全部结局", inclusion_criteria: "入选标准行数",
  exclusion_criteria: "排除标准行数", eligibility_criteria: "全部资格标准行数", countries: "国家",
  sites: "研究中心", enrollment_target: "目标入组人数",
};

function peerQuestion(row: PeerRow): string {
  const expected = `Does this record list more or fewer ${row.label.toLowerCase()} than the cached peers in this phase and condition?`;
  return row.question === expected
    ? t(row.question, `此记录的${dimensionLabels[row.metric]}，与相同分期和疾病的缓存同类试验相比更多还是更少？`)
    : row.question;
}
const hasEnoughPeers = (data: PeerMirrorData, row: PeerRow) =>
  data.cohort_n >= 5 && row.cohort_n >= 5 && row.available_n >= 5;

/** Read-only comparison of the saved design and the scenario's procedure removals. */
export function PeerMirror(props: PeerMirrorProps) {
  useTranslation();
  // A version switch clears local selections, responses and errors before the next paint.
  return <PinnedPeerMirror key={JSON.stringify([props.designId, props.designVersion])} {...props} />;
}

function PinnedPeerMirror({ designId, designVersion, removedProcedures }: PeerMirrorProps) {
  useTranslation();
  const headingId = useId();
  const [localRemoved, setRemoved] = useState<string[]>([]);
  const removed = removedProcedures ?? localRemoved;
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{ key: string; data?: PeerMirrorData; error?: string }>();
  const query = new URLSearchParams({ version: String(designVersion) });
  [...new Set(removed)].sort().forEach((code) => query.append("removed_procedures", code));
  const path = `/designs/${encodeURIComponent(designId)}/peers?${query}`;
  const requestKey = `${path}:${retry}`;
  const validVersion = Number.isInteger(designVersion) && designVersion > 0;

  useEffect(() => {
    if (!validVersion) return;
    const controller = new AbortController();
    let active = true;
    request<PeerMirrorData>("GET", path, { signal: controller.signal, silent: true })
      .then((data) => {
        if (!active) return;
        if (data.design_id !== designId || data.design_version !== designVersion) {
          throw new Error(t("The response does not match the saved design version on screen.", "响应与当前显示的已保存设计版本不匹配。"));
        }
        setResult({ key: requestKey, data });
      })
      .catch((error: unknown) => {
        if (active && !isAbort(error)) {
          setResult({ key: requestKey, error: error instanceof Error ? error.message : t("Peer comparison unavailable.", "同类试验比较暂不可用。") });
        }
      });
    return () => { active = false; controller.abort(); };
  }, [designId, designVersion, path, requestKey, validVersion]);

  const pending = validVersion && result?.key !== requestKey;
  const data = result?.data;
  // Never display an old cost estimate alongside a new procedure selection.
  const costs = pending ? null : data?.cost_comparison;

  return (
    <section aria-labelledby={headingId} className="space-y-4 rounded-xl border border-ink-200 bg-white p-5" data-testid="peer-mirror">
      <h2 id={headingId} className="text-lg font-semibold">{t("How does this record compare with cached peers?", "此记录与缓存的同类试验相比如何？")}</h2>
      <p className="text-sm text-ink-600">{t("Descriptive comparison for design v", "设计的描述性比较，版本 v")}{designVersion}{t(". Complexity can have scientific reasons.", "。复杂性可能有科学依据。")}</p>
      {!validVersion && <p role="alert">{t("A saved design version is required (design_version_required).", "需要已保存的设计版本（design_version_required）。")}</p>}
      {pending && <p role="status">{t("Loading cached peers and the engine comparison…", "正在加载缓存的同类试验及引擎比较结果…")}</p>}
      {result?.key === requestKey && result.error && (
        <div role="alert">
          <p>{result.error}</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)}>{t("Retry comparison", "重新比较")}</button>
        </div>
      )}
      {data && <>
        <p className="text-sm">
          {data.phase ?? t("Phase not reported", "未报告分期")} · {data.condition_group ?? t("Condition not reported", "未报告疾病")} · {data.cohort_n} {t("cached peers", "个缓存同类试验")}
          <br />{t("Record source:", "记录来源：")} {data.source_file ?? t("No matching cached registry file", "没有匹配的缓存注册文件")}
        </p>
        <p className="text-sm">{data.interpretation === "What might explain these differences? Complexity can have scientific reasons."
          ? t(data.interpretation, "哪些因素可能解释这些差异？复杂性可能有科学依据。") : data.interpretation}</p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{t("Registry counts and cached peer comparisons", "注册记录计数与缓存同类试验比较")}</caption>
            <thead><tr>
              <th scope="col">{t("Registry dimension", "注册维度")}</th><th scope="col">{t("This record", "此记录")}</th><th scope="col">{t("Reporting peers", "有报告的同类试验")}</th>
              <th scope="col">{t("Cached peer median", "缓存同类试验中位数")}</th><th scope="col">{t("Comparison", "比较")}</th>
            </tr></thead>
            <tbody>{data.rows.map((row) => (
              <tr key={row.metric} className="border-t border-ink-100" data-testid={`peer-${row.metric}`}>
                <th scope="row" className="py-3 pr-4 align-top font-normal">
                  <span className="font-medium">{t(row.label, dimensionLabels[row.metric])}</span>
                  <p className="mt-1 text-xs text-ink-600">{peerQuestion(row)}</p>
                  <details className="mt-1 text-xs text-ink-600">
                    <summary>{t("How was this compared?", "如何进行比较？")}</summary>
                    <p>{t("cohort_n:", "队列数量：")} {row.cohort_n}{t("; available_n:", "；可用数量：")} {row.available_n}{t("; phase:", "；分期：")} {row.phase ?? t("unknown", "未知")}{t("; condition_group:", "；疾病分组：")} {row.condition_group ?? t("unknown", "未知")}</p>
                    <p>{t("Source:", "来源：")} {row.source_file ?? t("not cached", "未缓存")}</p>
                    <p>{t("Peer files:", "同类试验文件：")} {row.peer_source_files.join(", ") || t("none", "无")}</p>
                    <p>{row.note}</p>
                  </details>
                </th>
                <td className="align-top py-3">{count(data.own_counts[row.metric])}</td>
                <td className="align-top py-3">{row.available_n} {t("of", "共")} {row.cohort_n} {t("cached peers", "个缓存同类试验")}</td>
                <td className="align-top py-3">{count(row.peer_median)}</td>
                <td className="align-top py-3">
                  <p>{row.comparison ? t(`${direction[row.comparison]} cached peer median`, `${direction[row.comparison]}缓存同类试验中位数`) : t("Comparison unavailable", "无法比较")}</p>
                  {row.status === "ok" && hasEnoughPeers(data, row) && row.percentile !== null
                    ? <p>{t("Within-cache percentile:", "缓存内百分位：")} {numeric.format(row.percentile)}</p>
                    : <p>{!hasEnoughPeers(data, row) || row.status === "insufficient_peers" ? t("insufficient_peers · no percentile", "同类试验不足 · 无百分位") : row.note}</p>}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {data.enrollment_reported !== null && (
          <p className="text-sm">{t("Reported enrollment:", "报告的入组人数：")} {count(data.enrollment_reported)} ({data.enrollment_type ?? t("type unknown", "类型未知")}).
            {data.enrollment_type === "ACTUAL" && t(" This is actual enrollment; a planned target is not reported.", " 这是实际入组人数；未报告计划目标。")}
          </p>
        )}
        <details className="text-sm">
          <summary>{t("How were counts and cohorts defined?", "计数与队列如何定义？")}</summary>
          <dl className="space-y-2 pt-2">{Object.entries(data.methods).map(([method, description]) => (
            <div key={method}><dt className="font-medium">{method}</dt><dd>{description}</dd></div>
          ))}</dl>
        </details>
        <h3 className="font-semibold">{t("What would removing selected procedure codes change?", "移除所选检查项目代码会带来哪些变化？")}</h3>
        <div className="space-y-2" data-testid="peer-p50-deltas">
          <h4 className="font-medium">{t("What are the estimated P50 changes in cost and site staff time?", "预计费用和研究中心人员工时的 P50 变化是多少？")}</h4>
          <p className="text-sm">{t("Counterfactual minus baseline, from the engine's per-draw differences.", "假设方案减去基线，基于引擎每次抽样的差值。")}</p>
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div><dt>{t("Cost (USD) P50 difference", "费用（美元）P50 差值")}</dt><dd data-testid="cost_usd-p50-difference">{estimate(costs?.delta.cost_usd.p50)}</dd></div>
            <div><dt>{t("Site staff (hours) P50 difference", "研究中心人员工时 P50 差值")}</dt><dd data-testid="site_staff_hours-p50-difference">{estimate(costs?.delta.site_staff_hours.p50)}</dd></div>
          </dl>
        </div>
        <p className="text-sm">{removedProcedures !== undefined
          ? t("Use Remove procedures in Design levers. This comparison isolates those removals against the baseline; other lever changes are reflected in the scenario results.", "请在设计调整项中使用“移除检查项目”。此比较仅衡量这些移除项相对于基线的影响；其他调整的影响体现在方案结果中。")
          : t("Choose codes for an engine comparison.", "选择代码以进行引擎比较。")} {t("Each selected code is removed from every visit in the counterfactual. The saved design stays unchanged.", "假设方案会从所有访视中移除所选代码对应的项目。已保存设计保持不变。")}</p>
        {removedProcedures === undefined && data.available_procedures.length > 0 && (
          <fieldset className="space-y-2" disabled={Boolean(data.cost_reason)}>
            <legend className="sr-only">{t("Procedure codes to remove in the counterfactual", "假设方案中要移除的检查项目代码")}</legend>
            {data.available_procedures.map((procedure) => (
              <label key={procedure.code} className="flex items-start gap-2 text-sm">
                <input type="checkbox" checked={removed.includes(procedure.code)} onChange={() => {
                  setRemoved((current) => current.includes(procedure.code)
                    ? current.filter((code) => code !== procedure.code)
                    : [...current, procedure.code].sort());
                }} />
                <span>{procedure.code}: {procedure.labels.join(" / ")} ({procedure.occurrences} {t("occurrences; visits", "次；访视")} {procedure.visit_numbers.join(", ")})</span>
              </label>
            ))}
          </fieldset>
        )}
        {!pending && data.cost_reason && <p>{data.cost_reason}</p>}
        {costs && <div data-testid="peer-costs" className="space-y-2">
          <p className="text-sm">{t("Design v", "设计 v")}{costs.design_version}{t("; removed_procedures:", "；已移除检查项目：")} {costs.removed_procedures.join(", ") || t("none (identical comparison)", "无（相同比较）")}.</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption>{t("Existing engine estimates · counterfactual minus baseline", "现有引擎估算 · 假设方案减去基线")}</caption>
              <thead><tr><th scope="col">{t("Metric / scenario", "指标 / 方案")}</th><th scope="col">P10</th><th scope="col">P50</th><th scope="col">P90</th></tr></thead>
              <tbody>{(["cost_usd", "site_staff_hours"] as const).flatMap((metric) =>
                (["baseline", "counterfactual", "delta"] as const).map((scenario) => {
                  const range = costs[scenario][metric];
                  return <tr key={`${metric}-${scenario}`} data-testid={`${metric}-${scenario}`}>
                    <th scope="row" className="font-normal">{metric === "cost_usd" ? t("Cost (USD)", "费用（美元）") : t("Site staff (hours)", "研究中心人员工时")} / {t(scenario, { baseline: "基线", counterfactual: "假设方案", delta: "差值" }[scenario])}</th>
                    <td>{estimate(range.p10)}</td><td>{estimate(range.p50)}</td><td>{estimate(range.p90)}</td>
                  </tr>;
                }),
              )}</tbody>
            </table>
          </div>
          <p className="text-xs text-ink-600">{costs.delta_method}</p>
          <p className="text-xs text-ink-600">{t("Parameter set:", "参数集：")} {costs.parameter_set_version}{t("; seed:", "；随机种子：")} {costs.seed}{t("; draws:", "；抽样次数：")} {costs.draws}.</p>
          {costs.warnings.length > 0 && <details><summary>{t("What assumptions does the engine use?", "引擎使用了哪些假设？")}</summary>
            <ul>{costs.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>
          </details>}
        </div>}
      </>}
    </section>
  );
}

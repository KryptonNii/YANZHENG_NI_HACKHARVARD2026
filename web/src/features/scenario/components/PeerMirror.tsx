import { useTranslation, translate as t } from "@/app/i18n";
import { localizeCopy } from "@/app/localize";
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
      <h2 id={headingId} className="text-lg font-semibold">{t("Peer benchmark", "同类试验对标")}</h2>
      {!validVersion && <p role="alert">{t("Save a design version to compare.", "请先保存设计版本。")}</p>}
      {pending && <p role="status">{t("Loading benchmark…", "对标数据加载中…")}</p>}
      {result?.key === requestKey && result.error && (
        <div role="alert">
          <p>{result.error}</p>
          <button type="button" onClick={() => setRetry((value) => value + 1)}>{t("Retry comparison", "重新比较")}</button>
        </div>
      )}
      {data && <>
        <p className="text-sm">
          {data.phase ?? t("Phase not reported", "未报告分期")} · {data.condition_group ?? t("Condition not reported", "未报告疾病")} · {data.cohort_n} {t("peer trials", "项同类试验")}
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">{t("Registry counts and peer benchmark", "注册数据与同类试验对标")}</caption>
            <thead><tr>
              <th scope="col">{t("Dimension", "维度")}</th><th scope="col">{t("This trial", "本试验")}</th><th scope="col">{t("Sample", "样本数")}</th>
              <th scope="col">{t("Peer median", "同类中位数")}</th><th scope="col">{t("Comparison", "对比")}</th>
            </tr></thead>
            <tbody>{data.rows.map((row) => (
              <tr key={row.metric} className="border-t border-ink-100" data-testid={`peer-${row.metric}`}>
                <th scope="row" className="py-3 pr-4 align-top font-normal">
                  <span className="font-medium">{t(row.label, dimensionLabels[row.metric])}</span>
                  <details className="mt-1 text-xs text-ink-600">
                    <summary>{t("Source & method", "来源与口径")}</summary>
                    <p>{t("cohort_n:", "队列数量：")} {row.cohort_n}{t("; available_n:", "；可用数量：")} {row.available_n}{t("; phase:", "；分期：")} {row.phase ?? t("unknown", "未知")}{t("; condition_group:", "；疾病分组：")} {row.condition_group ?? t("unknown", "未知")}</p>
                    <p>{t("Source:", "来源：")} {row.source_file ?? t("not cached", "未缓存")}</p>
                    <p>{t("Peer files:", "同类试验文件：")} {row.peer_source_files.join(", ") || t("none", "无")}</p>
                    <p>{row.note}</p>
                  </details>
                </th>
                <td className="align-top py-3">{count(data.own_counts[row.metric])}</td>
                <td className="align-top py-3">{row.available_n} / {row.cohort_n}</td>
                <td className="align-top py-3">{count(row.peer_median)}</td>
                <td className="align-top py-3">
                  <p>{row.comparison ? t(`${direction[row.comparison]} median`, `${direction[row.comparison]}中位数`) : t("Unavailable", "暂无对比")}</p>
                  {row.status === "ok" && hasEnoughPeers(data, row) && row.percentile !== null
                    ? <p className="text-xs text-ink-500">{t("Percentile", "百分位")} {numeric.format(row.percentile)}</p>
                    : <p className="text-xs text-ink-500">{!hasEnoughPeers(data, row) || row.status === "insufficient_peers" ? t("Insufficient sample", "样本不足") : t("Not reported", "未报告")}</p>}
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        {data.enrollment_reported !== null && (
          <p className="text-sm">{data.enrollment_type === "ACTUAL" ? t("Actual enrollment:", "实际入组：") : t("Reported enrollment:", "报告入组：")} {count(data.enrollment_reported)}
          </p>
        )}
        <details className="text-sm">
          <summary>{t("Source & methodology", "来源与方法")}</summary>
          <p className="mt-2">{t("Design v", "设计 v")}{designVersion} · {t("Record source:", "记录来源：")} {data.source_file ?? t("No matching registry record", "未匹配注册记录")}</p>
          <p className="mt-2">{data.interpretation === "What might explain these differences? Complexity can have scientific reasons."
            ? t("Descriptive benchmark; complexity can have scientific reasons.", "描述性对标；复杂性可能有科学依据。") : data.interpretation}</p>
          <dl className="space-y-2 pt-2">{Object.entries(data.methods).map(([method, description]) => (
            <div key={method}><dt className="font-medium">{method}</dt><dd>{description}</dd></div>
          ))}</dl>
        </details>
        <h3 className="font-semibold">{t("Procedure impact forecast", "检查项目影响测算")}</h3>
        <div className="space-y-2" data-testid="peer-p50-deltas">
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div><dt>{t("Cost (USD) P50 difference", "费用（美元）P50 差值")}</dt><dd data-testid="cost_usd-p50-difference">{estimate(costs?.delta.cost_usd.p50)}</dd></div>
            <div><dt>{t("Site staff (hours) P50 difference", "研究中心人员工时 P50 差值")}</dt><dd data-testid="site_staff_hours-p50-difference">{estimate(costs?.delta.site_staff_hours.p50)}</dd></div>
          </dl>
        </div>
        <details className="text-sm text-ink-600">
          <summary>{t("Calculation details", "测算口径")}</summary>
          <p>{removedProcedures !== undefined
          ? t("Use Remove procedures in Design levers. This comparison isolates those removals against the baseline; other lever changes are reflected in the scenario results.", "请在设计调整项中使用“移除检查项目”。此比较仅衡量这些移除项相对于基线的影响；其他调整的影响体现在方案结果中。")
          : t("Choose procedure codes to compare.", "选择检查项目代码进行测算。")} {t("Selected codes are removed across all visits in the forecast. Saved design is unchanged.", "测算从所有访视中移除所选项目。已保存设计保持不变。")}</p>
          <p>{t("Changes are calculated per draw against baseline.", "变化值按每次抽样相对基线计算。")}</p>
        </details>
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
        {costs && <details data-testid="peer-costs" className="space-y-2 text-sm">
          <summary>{t("Forecast detail", "测算明细")}</summary>
          <p>{t("Design v", "设计 v")}{costs.design_version}{t(" · Removed:", " · 移除项目：")} {costs.removed_procedures.join(", ") || t("None", "无")}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{t("Forecast · revised scenario minus baseline", "测算 · 调整方案相对基线")}</caption>
              <thead><tr><th scope="col">{t("Metric / scenario", "指标 / 方案")}</th><th scope="col">P10</th><th scope="col">P50</th><th scope="col">P90</th></tr></thead>
              <tbody>{(["cost_usd", "site_staff_hours"] as const).flatMap((metric) =>
                (["baseline", "counterfactual", "delta"] as const).map((scenario) => {
                  const range = costs[scenario][metric];
                  return <tr key={`${metric}-${scenario}`} data-testid={`${metric}-${scenario}`}>
                    <th scope="row" className="font-normal">{metric === "cost_usd" ? t("Cost (USD)", "费用（美元）") : t("Site staff (hours)", "研究中心人员工时")} / {t(scenario === "counterfactual" ? "Revised scenario" : scenario, { baseline: "基线", counterfactual: "调整方案", delta: "差值" }[scenario])}</th>
                    <td>{estimate(range.p10)}</td><td>{estimate(range.p50)}</td><td>{estimate(range.p90)}</td>
                  </tr>;
                }),
              )}</tbody>
            </table>
          </div>
          <p className="text-xs text-ink-600">{localizeCopy(costs.delta_method)}</p>
          <p className="text-xs text-ink-600">{t("Parameter set:", "参数集：")} {costs.parameter_set_version}{t("; seed:", "；随机种子：")} {costs.seed}{t("; draws:", "；抽样次数：")} {costs.draws}.</p>
          {costs.warnings.length > 0 && <details><summary>{t("Planning parameters", "规划参数")}</summary>
            <ul>{costs.warnings.map((warning, i) => <li key={i}>{localizeCopy(warning)}</li>)}</ul>
          </details>}
        </details>}
      </>}
    </section>
  );
}

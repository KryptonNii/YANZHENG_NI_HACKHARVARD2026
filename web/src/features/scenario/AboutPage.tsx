import { useTranslation } from "@/app/i18n";
import { useMemo, useState } from "react";
import type { Parameter } from "@/app/contracts";
import { AssumptionTag, Spinner } from "@/app/ui";
import { useParamLibrary } from "./hooks/useParamLibrary";
import { moduleLabel } from "./metrics";

const PAPER_URL = "https://bmjopen.bmj.com/content/14/1/e075755";
const MODULES = ["setup", "trial_management", "meetings_travel", "intervention", "data_collection", "supplies_equipment", "patient_assessments", "samples", "laboratory", "closeout", "drug_supply"];

function ParamTable({ params }: { params: Parameter[] }) {
  const tr = useTranslation();
  const [q, setQ] = useState("");
  const [onlyAssumptions, setOnlyAssumptions] = useState(false);
  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return params
      .filter((p) => (!onlyAssumptions || p.assumption) && (!s || `${p.id} ${p.label} ${p.source_title ?? ""}`.toLowerCase().includes(s)))
      .sort((a, b) => a.id.localeCompare(b.id));
  }, [params, q, onlyAssumptions]);
  const assumed = params.filter((p) => p.assumption).length;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <input type="search" className="input max-w-sm" placeholder={tr("Search parameters or sources", "搜索参数或来源")} aria-label={tr("Search parameters", "搜索参数")} value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="flex items-center gap-2 text-sm text-ink-700">
          <input type="checkbox" className="h-4 w-4 accent-accent-700" checked={onlyAssumptions} onChange={(e) => setOnlyAssumptions(e.target.checked)} />{tr("Only assumptions", "仅显示假设")}</label>
        <span className="text-sm text-ink-500">
          {params.length}{tr(" parameters · ", "个参数 ·")}{params.length - assumed}{tr(" sourced · ", "个有来源 ·")}{assumed}{tr(" labelled assumptions", "个已标注假设")}</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-ink-200">
        <table className="w-full text-sm" data-testid="param-table">
          <thead className="bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">{tr("Parameter", "参数")}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{tr("Low", "低值")}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{tr("Mid", "中值")}</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">{tr("High", "高值")}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{tr("Unit", "单位")}</th>
              <th scope="col" className="px-3 py-2 font-semibold">{tr("Source / rationale", "来源 / 依据")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className="border-t border-ink-100 align-top">
                <td className="px-3 py-2">
                  <p className="font-medium text-ink-900">{p.label}</p>
                  <code className="font-mono text-[11px] text-ink-500">{p.id} · v{p.version}{p.region ? ` · ${p.region}` : ""}</code>
                </td>
                <td className="px-3 py-2 text-right tabular">{p.value_low}</td>
                <td className="px-3 py-2 text-right tabular font-semibold">{p.value_mid}</td>
                <td className="px-3 py-2 text-right tabular">{p.value_high}</td>
                <td className="px-3 py-2 text-xs text-ink-600">{p.unit}</td>
                <td className="max-w-md px-3 py-2 text-xs text-ink-700">
                  {p.assumption ? (
                    <span className="flex items-start gap-2"><AssumptionTag /> <span className="pt-0.5">{p.rationale ?? tr("No rationale recorded.", "未记录依据。")}</span></span>
                  ) : p.source_url ? (
                    <a className="link" href={p.source_url} target="_blank" rel="noreferrer">{p.source_title ?? p.source_url}</a>
                  ) : (
                    p.source_title ?? <span className="text-caution-900">{tr("No source recorded", "未记录来源")}</span>
                  )}
                  {p.source_year ? ` (${p.source_year})` : ""}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={6} className="px-3 py-4 text-center text-ink-500">{tr("No parameters match.", "没有匹配的参数。")}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AboutPage() {
  const tr = useTranslation();
  const lib = useParamLibrary();
  return (
    <div className="space-y-6">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold tracking-tight text-ink-900">{tr("Method & sources", "方法与来源")}</h1>
        <p className="mt-2 text-ink-700">{tr("TrialPilot estimates what a clinical-trial design costs in money, site staff time, patient travel time, calendar time and carbon — and how those change when you move design levers. It is a planning aid, not a budget: every number is a range with its working shown.", "TrialPilot 估算临床试验设计所需的资金、研究中心人力、患者出行时间、日历时间和碳排放，并展示调整设计后的变化。它用于辅助规划而非制定预算：每个数值均以区间呈现，并附计算过程。")}</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <section className="card p-5">
          <h2 className="card-title">{tr("Activity × factor", "活动量 × 因子")}</h2>
          <p className="mt-2 text-sm text-ink-700">{tr("Each trial-specific activity (visits, monitoring trips, sample shipments, kits) is counted from the design, then multiplied by cost, staff-minute and emission factors from the parameter library. Carbon follows the Low Carbon Clinical Trials Group 10-module framework (", "根据设计统计各项试验活动（访视、监查差旅、样本运输、试剂盒），再乘以参数库中的成本、人力分钟数和排放因子。碳排放遵循低碳临床试验小组的十模块框架（")}<a className="link" href={PAPER_URL} target="_blank" rel="noreferrer">Griffiths, Fox, Williamson, BMJ Open 2024</a>).
          </p>
        </section>
        <section className="card p-5">
          <h2 className="card-title">{tr("Uncertainty", "不确定性")}</h2>
          <p className="mt-2 text-sm text-ink-700">{tr("Every parameter has a low, mid and high value. The engine samples each from a triangular distribution (2,000 seeded Monte Carlo draws) and reports P10, P50 and P90. The provenance drawer ranks the five parameters that drive most of the variance.", "每个参数均有低、中、高三个值。引擎从三角分布中抽样（使用固定随机种子进行 2,000 次蒙特卡洛抽样），并报告 P10、P50 和 P90。来源详情面板列出对方差贡献最大的五个参数。")}</p>
        </section>
        <section className="card p-5">
          <h2 className="card-title">{tr("Honesty rules", "透明性原则")}</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-700">
            <li>{tr("Every parameter has a source (URL and year) or is labelled an assumption with a rationale.", "每个参数都注明来源（链接和年份），或标注为假设并说明依据。")}</li>
            <li>{tr("Missing inputs are reported as missing and filled with labelled assumptions, never silently zeroed.", "缺失输入会明确标注，并使用已标注的假设值填补，不会默认为零。")}</li>
            <li>{tr("Simulated operational data is labelled “Simulated feed”.", "模拟运营数据标注为“模拟数据”。")}</li>
            <li>{tr("AI-extracted protocol data is a draft until a person accepts it.", "AI 提取的试验方案数据在人工接受前均为草稿。")}</li>
          </ul>
        </section>
      </div>

      <section className="card p-5">
        <h2 className="card-title">{tr("Modules", "模块")}</h2>
        <ol className="mt-3 grid gap-x-6 gap-y-1 text-sm text-ink-700 sm:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m, i) => (
            <li key={m}>
              <span className="tabular text-ink-500">{i + 1}.</span> {moduleLabel(m)}
              {m === "intervention" && <span className="text-xs text-ink-500">{tr(" — excluded by default", "— 默认排除")}</span>}
              {m === "drug_supply" && <span className="text-xs text-ink-500">{tr(" — extension beyond the published method", "— 已发表方法之外的扩展")}</span>}
            </li>
          ))}
        </ol>
      </section>

      <section className="card p-5">
        <h2 className="card-title mb-3">{tr("Parameter library", "参数库")}</h2>
        {lib.status === "loading" && <Spinner label={tr("Loading parameter library", "正在加载参数库")} />}
        {lib.status === "error" && <p className="text-sm text-worse-800">{tr("The parameter library could not be loaded: ", "无法加载参数库：")}{lib.message}</p>}
        {lib.status === "ready" && <ParamTable params={[...lib.byId.values()]} />}
      </section>
    </div>
  );
}

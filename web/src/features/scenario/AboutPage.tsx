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
          <input type="checkbox" className="h-4 w-4 accent-accent-700" checked={onlyAssumptions} onChange={(e) => setOnlyAssumptions(e.target.checked)} />{tr("To confirm", "待确认")}</label>
        <span className="text-sm text-ink-500">
          {params.length}{tr(" parameters · ", " 个参数 · ")}{params.length - assumed}{tr(" sourced · ", " 个有来源 · ")}{assumed}{tr(" to confirm", " 个待确认")}</span>
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
        <p className="mt-2 text-ink-700">{tr("Planning estimates for cost, workload, patient travel, timeline and carbon.", "成本、工作量、患者出行、周期与碳排放的规划估算。")}</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <section className="card p-5">
          <h2 className="card-title">{tr("Activity × factor", "活动量 × 因子")}</h2>
          <p className="mt-2 text-sm text-ink-700">{tr("Design activities × cost, staff-time and emission factors. Carbon method: ", "设计活动量 × 成本、工时及排放因子。碳排放方法：")}<a className="link" href={PAPER_URL} target="_blank" rel="noreferrer">BMJ Open 2024</a>.
          </p>
        </section>
        <section className="card p-5">
          <h2 className="card-title">{tr("Estimate ranges", "估算区间")}</h2>
          <p className="mt-2 text-sm text-ink-700">{tr("2,000 Monte Carlo draws from triangular parameter ranges. Results: P10 / P50 / P90.", "参数采用三角分布，进行 2,000 次蒙特卡洛抽样。结果以 P10 / P50 / P90 呈现。")}</p>
        </section>
        <section className="card p-5">
          <h2 className="card-title">{tr("Data controls", "数据管理")}</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-ink-700">
            <li>{tr("Sources and parameter rationale are recorded.", "记录参数来源与依据。")}</li>
            <li>{tr("Missing values require confirmation.", "缺失值标为待确认。")}</li>
            <li>{tr("Protocol extraction requires review.", "方案提取结果须审核。")}</li>
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

import { useTranslation, translate as tr } from "@/app/i18n";
import { localizeCopy } from "@/app/localize";
import { Fragment, useEffect, useState } from "react";
import { ApiError, api, isAbort } from "@/app/api/client";
import type {
  ScienceCheck,
  ScienceFinding,
  ScienceIndustryBand,
  ScienceModuleRow,
  ScienceRange,
  ScienceResults,
  ScienceRowStatus,
  ScienceTrial,
} from "@/app/api/types";
import type { MetricRange } from "@/app/contracts";
import { formatCo2e, formatRange } from "@/app/format";
import { Badge, EmptyState, ErrorPanel, Segmented, SimulatedBadge, Skeleton } from "@/app/ui";
import { moduleLabel } from "./metrics";

const PAPER_URL = "https://bmjopen.bmj.com/content/14/1/e075755";

const CHECK_ORDER = ["method", "corrected", "library", "engine_library", "engine_paper_factors"];
/** The hero comparison is our engine. Method stays first in the control so the paper arithmetic is one click away. */
const DEFAULT_CHECK = ["engine_library", "engine_paper_factors", "library", "corrected", "method"];

const CHECK_SHORT: Record<string, string> = {
  method: "Method",
  corrected: "Corrected",
  library: "Library",
  engine_library: "Engine",
  engine_paper_factors: "Engine, paper factors",
};

const STATUS_WORD: Record<ScienceRowStatus, string> = {
  match: "Match",
  close: "Close",
  gap: "Gap",
  not_reported: "Not reported",
  unavailable: "Unavailable",
};

function statusWord(status: ScienceRowStatus): string {
  const chinese: Record<ScienceRowStatus, string> = {
    match: "一致", close: "接近", gap: "偏差", not_reported: "未报告", unavailable: "不可用",
  };
  return tr(STATUS_WORD[status], chinese[status]);
}

function checkLabel(id: string, fallback: string): string {
  const chinese: Record<string, string> = {
    method: "原方法", corrected: "修正结果", library: "参数库", engine_library: "引擎", engine_paper_factors: "引擎（论文因子）",
  };
  return tr(CHECK_SHORT[id] ?? fallback, chinese[id] ?? fallback);
}

function statusTone(status: ScienceRowStatus): "better" | "caution" | "worse" | "neutral" {
  if (status === "match") return "better";
  if (status === "close") return "caution";
  if (status === "gap") return "worse";
  return "neutral";
}

function formatSciPct(p: number | null): string {
  if (p === null || !Number.isFinite(p)) return "—";
  const rounded = Math.round(p * 10) / 10;
  if (rounded === 0) return "0%";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded)}%`;
}

function asKg(r: ScienceRange): MetricRange {
  return { p10: r.p10, p50: r.p50, p90: r.p90, unit: "kg_co2e" };
}

/** Industry-band figures are tonnes as stored. The file's unit string is printed; the numbers are not rescaled. */
function formatTonnes(v: number): string {
  return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(v)} t`;
}

function formatTonneRange(r: ScienceRange): string {
  return `${formatTonnes(r.p10)} – ${formatTonnes(r.p90)}`;
}

function rowLabel(row: ScienceModuleRow): string {
  const labels: Record<string, string> = {
    "Trial set-up": "试验启动",
    "Trial management (CTU emissions)": "试验管理（临床试验单位排放）",
    "Meetings and travel": "会议与差旅",
    "Intervention (distribution only)": "干预（仅配送）",
    "Data collection and exchange": "数据采集与交换",
    "Supplies and equipment": "耗材与设备",
    "Patient assessments (incl. patient travel)": "患者评估（含患者出行）",
    "Samples": "样本",
    "Laboratory": "实验室",
    "Close-out and archiving": "收尾与归档",
    "Total": "总计",
  };
  return row.label ? tr(row.label, labels[row.label] ?? row.label) : moduleLabel(row.module);
}

function defaultCheckId(checks: ScienceCheck[]): string {
  for (const id of DEFAULT_CHECK) {
    const found = checks.find((c) => c.id === id && c.available);
    if (found) return found.id;
  }
  return checks.find((c) => c.available)?.id ?? checks[0]?.id ?? "";
}

function orderedChecks(checks: ScienceCheck[]): ScienceCheck[] {
  return [...checks].sort((a, b) => {
    const ia = CHECK_ORDER.indexOf(a.id);
    const ib = CHECK_ORDER.indexOf(b.id);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
  });
}

function hasSpread(r: ScienceRange | null): boolean {
  return !!r && r.p10 !== r.p90;
}

function ModuleTable({ rows }: { rows: ScienceModuleRow[] }) {
  const tr = useTranslation();
  const max = Math.max(...rows.flatMap((m) => [m.published_kg ?? 0, m.ours?.p90 ?? 0]), 1);
  const w = (v: number) => `${Math.max((v / max) * 100, 0.6)}%`;
  return (
    <table className="w-full text-sm" data-testid="science-modules">
      <caption className="sr-only">{tr("Per-module carbon, published versus this check", "各模块碳排放：发表值与本次检验比较")}</caption>
      <thead>
        <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
          <th scope="col" className="w-44 pb-1 font-semibold">{tr("Module", "模块")}</th>
          <th scope="col" className="pb-1 font-semibold">
            <span className="mr-3 inline-flex items-center gap-1">
              <span className="inline-block h-2 w-3 rounded-sm bg-ink-400" aria-hidden />{tr(" Published", "发表值")}</span>
            <span className="inline-flex items-center gap-1">
              <span className="inline-block h-2 w-3 rounded-sm bg-accent-600" aria-hidden />{tr(" This check, P50", "本次检验，P50")}</span>
          </th>
          <th scope="col" className="w-36 pb-1 text-right font-semibold">{tr("Result", "结果")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((m) => (
          <Fragment key={m.module}>
          <tr className="border-t border-ink-100 align-middle">
            <th scope="row" className="py-2 pr-2 text-left font-medium text-ink-800">
              {rowLabel(m)}
            </th>
            <td className="py-2">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <div
                    className="h-2.5 rounded-sm bg-ink-400"
                    style={{ width: m.published_kg !== null ? w(m.published_kg) : 0 }}
                    aria-hidden
                  />
                  <span className="whitespace-nowrap text-xs tabular text-ink-600">
                    {m.published_kg !== null ? formatCo2e(m.published_kg) : tr("not reported", "未报告")}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {m.ours ? (
                    <div className="relative h-2.5" style={{ width: w(m.ours.p90) }} aria-hidden>
                      <div
                        className="absolute inset-y-0 left-0 rounded-sm bg-accent-600"
                        style={{ width: `${(m.ours.p50 / Math.max(m.ours.p90, 1e-9)) * 100}%` }}
                      />
                      <div
                        className="absolute top-1/2 h-px bg-accent-900"
                        style={{ left: `${(m.ours.p10 / Math.max(m.ours.p90, 1e-9)) * 100}%`, right: 0 }}
                      />
                    </div>
                  ) : null}
                  <span className="whitespace-nowrap text-xs tabular text-ink-600">
                    {m.ours ? `${formatCo2e(m.ours.p50)} (${formatRange(asKg(m.ours))})` : tr("not computed", "未计算")}
                  </span>
                </div>
              </div>
            </td>
            <td className="py-2 text-right">
              <Badge tone={statusTone(m.status)}>{statusWord(m.status)}</Badge>
              <span className="mt-1 block text-sm font-semibold tabular text-ink-800">{formatSciPct(m.diff_pct)}</span>
            </td>
          </tr>
          {m.explanation && (
            <tr>
              <td colSpan={3} className="pb-2 text-xs leading-snug text-ink-600">
                <details><summary className="cursor-pointer">{tr("Basis", "依据")}</summary><p className="mt-1">{localizeCopy(m.explanation)}</p></details>
              </td>
            </tr>
          )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

function TotalStrip({ row }: { row: ScienceModuleRow }) {
  const tr = useTranslation();
  const inside =
    row.published_within_range === true
      ? tr("Published total is inside the P10–P90 range.", "发表总量位于 P10–P90 区间内。")
      : row.published_within_range === false && hasSpread(row.ours)
        ? tr("Published total is outside the P10–P90 range.", "发表总量位于 P10–P90 区间外。")
        : null;
  return (
    <div className="mt-4">
      <dl className="grid grid-cols-3 gap-3 rounded-lg bg-ink-50 p-3">
        <div>
          <dt className="text-xs text-ink-500">{tr("Published total", "发表总量")}</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{row.published_kg !== null ? formatCo2e(row.published_kg) : "—"}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-500">{tr("This check (P50)", "本次检验（P50）")}</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{row.ours ? formatCo2e(row.ours.p50) : "—"}</dd>
          {row.ours && <dd className="text-xs tabular text-ink-500">P10–P90 {formatRange(asKg(row.ours))}</dd>}
        </div>
        <div>
          <dt className="text-xs text-ink-500">{tr("Difference", "差异")}</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{formatSciPct(row.diff_pct)}</dd>
          <dd className="mt-1">
            <Badge tone={statusTone(row.status)}>{statusWord(row.status)}</Badge>
          </dd>
        </div>
      </dl>
      {inside && <p className="mt-2 text-sm text-ink-700">{inside}</p>}
      {row.explanation && <details className="mt-2 text-sm text-ink-700"><summary className="cursor-pointer">{tr("Basis", "依据")}</summary><p className="mt-1">{localizeCopy(row.explanation)}</p></details>}
    </div>
  );
}

const SEVERITY_TONE: Record<string, "worse" | "caution" | "neutral"> = {
  large: "worse",
  medium: "caution",
  info: "neutral",
};

function effectText(kg: number | null): string | null {
  if (kg === null) return null;
  if (kg === 0) return tr("No change to the published total", "发表总量无变化");
  const sign = kg > 0 ? "+" : "−";
  return tr(`${sign}${formatCo2e(Math.abs(kg))} versus the published arithmetic`, `相较论文计算值 ${sign}${formatCo2e(Math.abs(kg))}`);
}

function Findings({ findings }: { findings: ScienceFinding[] }) {
  const tr = useTranslation();
  if (findings.length === 0) return null;
  const order = { large: 0, medium: 1, info: 2 };
  const rows = [...findings].sort((a, b) => (order[a.severity as keyof typeof order] ?? 3) - (order[b.severity as keyof typeof order] ?? 3));
  return (
    <section className="mt-4" data-testid="science-findings" aria-label={tr("Findings", "发现")}>
      <h3 className="text-sm font-semibold text-ink-800">{tr("Findings in the paper", "论文中的发现")}</h3>
      <ul className="mt-2 space-y-2">
        {rows.map((f) => (
          <li key={f.id} className="rounded-lg border border-ink-100 px-3 py-2">
            <p className="text-sm text-ink-800">
              <Badge tone={SEVERITY_TONE[f.severity] ?? "neutral"} className="mr-2 align-middle">
                {tr(f.severity, ({ large: "较大", medium: "中等", info: "信息" } as Record<string, string>)[f.severity] ?? f.severity)}
              </Badge>
              {localizeCopy(f.summary)}
            </p>
            {f.detail && <p className="mt-1 text-xs leading-snug text-ink-600">{localizeCopy(f.detail)}</p>}
            {effectText(f.effect_kg) && <p className="mt-1 text-xs tabular text-ink-500">{effectText(f.effect_kg)}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function TrialResultCard({ trial, paperUrl }: { trial: ScienceTrial; paperUrl: string }) {
  const tr = useTranslation();
  const [checkId, setCheckId] = useState(() => defaultCheckId(trial.checks));
  const check = trial.checks.find((c) => c.id === checkId) ?? trial.checks[0];
  const assumptions = trial.design_inputs.filter((d) => d.origin === "assumption");
  const facts = [
    trial.phase,
    trial.patients !== null ? tr(`${trial.patients.toLocaleString("en-US")} patients`, `${trial.patients.toLocaleString("en-US")} 名患者`) : null,
    trial.sites !== null ? tr(`${trial.sites.toLocaleString("en-US")} sites`, `${trial.sites.toLocaleString("en-US")} 个研究中心`) : null,
    trial.countries.length ? trial.countries.join(", ") : null,
  ].filter(Boolean);

  return (
    <article className="card p-5" aria-labelledby={`sci-${trial.id}`} data-testid="science-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 id={`sci-${trial.id}`} className="text-xl font-bold text-ink-900">
            {trial.name}
          </h2>
          {trial.registry_id && <p className="text-xs text-ink-500">{trial.registry_id}</p>}
          {facts.length > 0 && <p className="mt-1 text-sm text-ink-600">{facts.join(" · ")}</p>}
        </div>
        {trial.published.total_kg !== null && <Badge tone="neutral">{tr("Published ", "发表值")}{formatCo2e(trial.published.total_kg)}</Badge>}
      </div>

      {trial.summary.length > 0 && (
        <details className="mt-3 text-sm text-ink-600">
          <summary className="cursor-pointer">{tr("Study summary", "研究概况")}</summary>
          <div className="mt-2 space-y-2">{trial.summary.map((s) => <p key={s}>{localizeCopy(s)}</p>)}</div>
        </details>
      )}

      {trial.checks.length > 1 && (
        <div className="mt-4">
          <Segmented
            label={tr(`${trial.name} check`, `${trial.name} 检验`)}
            size="sm"
            value={check?.id ?? checkId}
            onChange={setCheckId}
            options={orderedChecks(trial.checks).map((c) => ({
              value: c.id,
              label: checkLabel(c.id, c.title),
              title: c.title,
            }))}
          />
        </div>
      )}

      {check && (
        <div className="mt-3" data-testid="science-check">
          <h3 className="text-sm font-semibold text-ink-900">{localizeCopy(check.title)}</h3>
          {check.description && <details className="mt-1 text-sm text-ink-600"><summary className="cursor-pointer">{tr("Method", "计算方法")}</summary><p className="mt-1">{localizeCopy(check.description)}</p></details>}
          {!check.available ? (
            <p className="mt-3 text-sm text-ink-700" role="status">{tr("This check is unavailable. ", "此项检验不可用。")}{check.unavailable_reason ? localizeCopy(check.unavailable_reason) : tr("The reproduction did not produce it.", "复现过程未生成此结果。")}
            </p>
          ) : (
            <>
              {check.total && <TotalStrip row={check.total} />}
              {check.modules.length > 0 && (
                <div className="mt-4">
                  <ModuleTable rows={check.modules} />
                </div>
              )}
              {check.notes.length > 0 && (
                <details className="mt-3 text-xs text-ink-600">
                  <summary className="cursor-pointer">{tr("Calculation notes", "计算说明")}</summary>
                  <ul className="mt-2 list-disc space-y-1 pl-5">{check.notes.map((n) => <li key={n}>{localizeCopy(n)}</li>)}</ul>
                </details>
              )}
              {check.line_changes.length > 0 && (
                <details className="mt-3">
                  <summary className="cursor-pointer text-sm font-semibold text-ink-800">{tr("Line-by-line factor changes (", "逐行因子变化（")}{check.line_changes.length})
                  </summary>
                  <ul className="mt-2 space-y-2">
                    {check.line_changes.map((line) => (
                      <li key={line.line_id} className="rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-700">
                        <p className="font-semibold text-ink-800">
                          {moduleLabel(line.module)} — {line.item}
                        </p>
                        <p className="mt-0.5 tabular">{tr("Paper ", "论文")}{line.paper_kg !== null ? formatCo2e(line.paper_kg) : "—"}
                          {line.library_kg ? tr(` · library P50 ${formatCo2e(line.library_kg.p50)}`, ` · 参数库 P50 ${formatCo2e(line.library_kg.p50)}`) : ""}
                          {` · ${localizeCopy(line.kind.replace(/_/g, " "))}`}
                        </p>
                        {line.note && <p className="mt-0.5">{localizeCopy(line.note)}</p>}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </>
          )}
        </div>
      )}

      {trial.checks.length === 0 && <p className="mt-3 text-sm text-ink-600">{tr("This result has no checks.", "此结果没有检验项目。")}</p>}

      <Findings findings={trial.findings} />

      {assumptions.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-semibold text-ink-800">{tr("Design inputs to confirm (", "待确认设计参数（")}{assumptions.length})
          </summary>
          <ul className="mt-2 space-y-1 text-xs text-ink-600">
            {assumptions.map((a) => (
              <li key={a.field}>
                <span className="font-semibold text-ink-800">{a.field.replace(/_/g, " ")}</span>: {a.value}
                {a.ref ? ` — ${a.ref}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="mt-3 text-xs text-ink-500">{tr("Source:", "来源：")}{" "}
        <a className="link" href={paperUrl} target="_blank" rel="noreferrer">
          Griffiths, Fox, Williamson et al., BMJ Open 2024
        </a>
        {trial.source ? `. ${trial.source}` : ""}
      </p>
    </article>
  );
}

function bandName(title: string, registryId: string | null): string {
  const head = title.split(":")[0]?.trim() ?? "";
  if (head && head.length <= 20 && head === head.toUpperCase()) return head;
  return registryId ?? (title.length > 48 ? `${title.slice(0, 45)}…` : title);
}

function IndustryBand({ band }: { band: ScienceIndustryBand }) {
  const tr = useTranslation();
  const fileUnits = [...new Set(band.demo_trials.map((t) => t.total_t?.unit).filter((u): u is string => !!u))];
  return (
    <section className="card p-5" aria-labelledby="industry-band-title" data-testid="science-band">
      <h2 id="industry-band-title" className="text-lg font-bold text-ink-900">{tr("Industry band", "行业区间")}</h2>
      <p className="mt-1 text-sm text-ink-700">
        {band.low_t !== null && band.high_t !== null
          ? `${formatTonnes(band.low_t)} – ${formatTonnes(band.high_t)} CO₂e`
          : tr("Band not reported", "未报告区间")}
        {band.trials_t.length > 0 ? tr(` (published trials ${band.trials_t.map((t) => formatTonnes(t)).join(", ")})`, `（已发表试验 ${band.trials_t.map((t) => formatTonnes(t)).join("、")}）`) : ""}</p>
      <details className="mt-2 text-xs text-ink-500">
        <summary className="cursor-pointer">{tr("Comparison basis", "比较口径")}</summary>
        <p className="mt-1">{tr("Reference band uses a different method and includes drug manufacture.", "参考区间采用不同方法，包含药物制造。")}</p>
        {band.note && <p className="mt-1">{localizeCopy(band.note)}</p>}
      {fileUnits.length > 0 && (
        <p className="mt-2" data-testid="science-band-unit">{tr("Displayed unit: t · source unit: ", "显示单位：吨 · 源单位：")}{fileUnits.join(", ")}{fileUnits.includes("kg_co2e") ? tr(" · unit conflict; stored figures unchanged", " · 单位冲突，按原数值展示") : ""}
        </p>
      )}
      </details>
      {band.demo_trials.length > 0 && (
        <table className="mt-4 w-full text-sm">
          <caption className="sr-only">{tr("Demo trials against the industry carbon band", "演示试验与行业碳排放区间比较")}</caption>
          <thead>
            <tr className="text-left text-xs uppercase tracking-wide text-ink-500">
              <th scope="col" className="pb-1 font-semibold">{tr("Trial", "试验")}</th>
              <th scope="col" className="pb-1 text-right font-semibold">P50</th>
              <th scope="col" className="pb-1 text-right font-semibold">P10–P90</th>
              <th scope="col" className="pb-1 text-right font-semibold">{tr("Versus band", "与区间比较")}</th>
            </tr>
          </thead>
          <tbody>
            {band.demo_trials.map((t) => (
              <tr key={t.design_id} className="border-t border-ink-100">
                <th scope="row" className="py-2 pr-2 text-left font-medium text-ink-800">
                  {bandName(t.title, t.registry_id)}
                  {!t.available && t.reason && <span className="mt-0.5 block text-xs font-normal text-ink-500">{localizeCopy(t.reason)}</span>}
                </th>
                <td className="py-2 text-right tabular">{t.total_t ? formatTonnes(t.total_t.p50) : "—"}</td>
                <td className="py-2 text-right tabular text-ink-600">{t.total_t ? formatTonneRange(t.total_t) : "—"}</td>
                <td className="py-2 text-right">
                  {t.within_band === true && <Badge tone="better">{tr("Inside the band", "区间内")}</Badge>}
                  {t.within_band === false && <Badge tone="caution">{tr("Outside the band", "区间外")}</Badge>}
                  {t.within_band === null && <span className="text-ink-500">—</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {band.source && <p className="mt-3 text-xs text-ink-500">{localizeCopy(band.source)}</p>}
    </section>
  );
}

export function SciencePage() {
  const tr = useTranslation();
  const [data, setData] = useState<ScienceResults | null>(null);
  const [error, setError] = useState<ApiError | Error | null>(null);
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    api
      .science({ signal: ctrl.signal, silent: true })
      .then(setData)
      .catch((err) => {
        if (!isAbort(err)) setError(err);
      })
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, [reload]);

  const notReady = error instanceof ApiError && (error.status === 404 || error.status === 501);
  const paperUrl = data?.paper.url || data?.paper.full_text || PAPER_URL;
  const matchPct = data?.thresholds_pct.match ?? 1;
  const closePct = data?.thresholds_pct.close ?? 10;

  return (
    <div className="space-y-5">
      <div className="max-w-3xl">
        <h1 className="text-2xl font-bold tracking-tight text-ink-900">{tr("Science check", "科学验证")}</h1>
        <p className="mt-1 text-sm text-ink-600">{tr("CASPS and PRIMETIME carbon estimates against published results · ", "CASPS 与 PRIMETIME 碳排放估算对照 · ")}
          <a className="link" href={paperUrl} target="_blank" rel="noreferrer">
            BMJ Open 2024
          </a></p>
        <p className="mt-2 text-xs text-ink-500">{tr("Match ≤ ", "一致 ≤ ")}{matchPct}{tr("% · close ≤ ", "% · 接近 ≤ ")}{closePct}{tr("% · gap above this", "% · 其余为偏差")}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {data?.simulated ? <SimulatedBadge /> : data?.data_label ? <Badge tone="neutral">{tr("Published data", "已发表数据")}</Badge> : null}
          {data?.engine && (
            <Badge tone={data.engine.available ? "better" : "caution"}>
              {data.engine.available ? tr("Engine check available", "引擎检验可用") : tr("Engine check unavailable", "引擎检验不可用")}
            </Badge>
          )}
        </div>
        {(data?.parameter_set_version || data?.draws) && (
          <details className="mt-2 text-xs text-ink-500">
            <summary className="cursor-pointer">{tr("Run details", "运行详情")}</summary>
            <p className="mt-1">{tr("Drug supply excluded from published total.", "药物供应不计入论文总量。")}</p>
            <p className="mt-1">
            {data.parameter_set_version ? tr(`Parameter set ${data.parameter_set_version}`, `参数集 ${data.parameter_set_version}`) : ""}
            {data.seed !== null && data.draws !== null ? tr(` · seed ${data.seed}, ${data.draws.toLocaleString("en-US")} draws`, ` · 随机种子 ${data.seed}，${data.draws.toLocaleString("en-US")} 次抽样`) : ""}
            {data.how_to_reproduce ? tr(` · reproduce with ${data.how_to_reproduce}`, ` · 复现命令 ${data.how_to_reproduce}`) : ""}
            </p>
          </details>
        )}
      </div>
      {loading ? (
        <div className="space-y-5">
          <Skeleton className="h-96" />
          <Skeleton className="h-96" />
        </div>
      ) : notReady ? (
        <EmptyState title={tr("Validation results unavailable", "验证结果暂不可用")} />
      ) : error ? (
        <ErrorPanel title={tr("Could not load the science results", "无法加载科学验证结果")} message={error.message} onRetry={() => setReload((r) => r + 1)} />
      ) : data && data.trials.length > 0 ? (
        <>
          {data.engine && !data.engine.available && data.engine.reason && (
            <p className="text-sm text-ink-700" role="status">{tr("Engine checks were not run. ", "尚未运行引擎检验。")}{localizeCopy(data.engine.reason)}
            </p>
          )}
          <div className="space-y-5">
            {data.trials.map((t) => (
              <TrialResultCard key={t.id} trial={t} paperUrl={paperUrl} />
            ))}
          </div>
          {data.industry_band && <IndustryBand band={data.industry_band} />}
        </>
      ) : (
        <EmptyState title={tr("No trials in the results file", "结果文件中没有试验")} />
      )}
    </div>
  );
}

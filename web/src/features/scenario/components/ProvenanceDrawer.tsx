import { useTranslation, translate as t } from "@/app/i18n";
import { useEffect, useMemo, useState } from "react";
import type { Levers, MetricRange, Parameter, ProvenanceItem } from "@/app/contracts";
import { api, isAbort } from "@/app/api/client";
import type { Driver, ScenarioResultX } from "@/app/api/types";
import { formatRange, formatUtc, formatValue } from "@/app/format";
import { AssumptionTag, Badge, Drawer, Spinner } from "@/app/ui";
import { useParamLibrary } from "../hooks/useParamLibrary";
import { allProvenance, findModule, isExtensionModule, METRIC_BY_KEY, metricLabel, moduleLabel, provenanceForMetric, type MetricKey } from "../metrics";

export type ProvenanceTarget =
  | { kind: "metric"; key: MetricKey }
  | { kind: "module"; module: string }
  | { kind: "waste" };

type Item = ProvenanceItem & { module: string };

function fmtInput(v: number | string): string {
  if (typeof v === "string") return v;
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  return v.toLocaleString("en-US", { maximumSignificantDigits: 4 });
}

function isWellToTank(formulaId: string): boolean {
  return /_wtt(?:\.|$)/.test(formulaId);
}

function FormulaCard({ item }: { item: Item }) {
  useTranslation();
  const inputs = Object.entries(item.inputs);
  const wtt = isWellToTank(item.formula_id);
  return (
    <li className="rounded-lg border border-ink-200 p-3" data-testid="provenance-formula">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <code className="rounded bg-ink-100 px-1.5 py-0.5 font-mono text-xs text-ink-800">{item.formula_id}</code>
        <span className="flex items-center gap-1.5 text-xs text-ink-500">
          {wtt && (
            <span className="chip border-accent-300 bg-accent-50 text-accent-800" data-testid="wtt-label">
              {t("Well-to-tank", "燃料上游排放")}
            </span>
          )}
          {moduleLabel(item.module)}
        </span>
      </div>
      {wtt && (
        <p className="mt-2 text-xs text-ink-600">
          {t("Upstream fuel production and distribution, kept as its own term beside the direct emissions. A missing well-to-tank factor stays unknown and is not added as zero.", "燃料生产和配送产生的上游排放，与直接排放分项列示。缺失的上游排放因子保留为未知，不按零计入。")}
        </p>
      )}
      <p className="mt-2 text-sm text-ink-800">{item.description}</p>
      {inputs.length > 0 && (
        <table className="mt-2 w-full text-xs">
          <caption className="sr-only">{t("Resolved inputs", "已解析输入")}</caption>
          <tbody>
            {inputs.map(([k, v]) => (
              <tr key={k} className="border-t border-ink-100">
                <th scope="row" className="py-1 pr-3 text-left font-mono font-normal text-ink-600">{k}</th>
                <td className={`py-1 text-right tabular ${typeof v === "string" && v.toLowerCase().includes("unknown") ? "font-semibold text-caution-900" : "text-ink-900"}`}>{fmtInput(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {item.assumptions.length > 0 && <AssumptionList assumptions={item.assumptions} />}
    </li>
  );
}

/** Many assumptions differ only by a country code; collapse beyond the first few. */
function AssumptionList({ assumptions }: { assumptions: string[] }) {
  useTranslation();
  const unique = [...new Set(assumptions)];
  const [open, setOpen] = useState(false);
  const shown = open ? unique : unique.slice(0, 3);
  return (
    <div className="mt-2">
      <ul className="space-y-1">
        {shown.map((a) => (
          <li key={a} className="flex items-start gap-2 text-xs text-ink-700">
            <AssumptionTag /> <span className="pt-0.5">{a}</span>
          </li>
        ))}
      </ul>
      {unique.length > 3 && (
        <button type="button" className="link mt-1 text-xs" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? t("Collapse", "收起") : t(`All ${unique.length} planning inputs`, `全部 ${unique.length} 项规划输入`)}
        </button>
      )}
    </div>
  );
}

function ParameterRow({ id, param }: { id: string; param: Parameter | undefined }) {
  useTranslation();
  if (!param) {
    return (
      <li className="rounded-lg border border-caution-300 bg-caution-50 p-3 text-sm" data-testid="provenance-param">
        <code className="font-mono text-xs">{id}</code>
        <p className="mt-1 text-caution-900">{t("Parameter missing", "参数待补充")}</p>
      </li>
    );
  }
  return (
    <li className="rounded-lg border border-ink-200 p-3" data-testid="provenance-param">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-ink-900">{param.label}</p>
          <code className="font-mono text-[11px] text-ink-500">
            {param.id} · v{param.version}
            {param.region ? ` · ${param.region}` : ""}
          </code>
        </div>
        {param.assumption && <AssumptionTag title={param.rationale ?? undefined} />}
      </div>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-center">
        {(
          [
            [t("Low", "低值"), param.value_low],
            [t("Mid", "中值"), param.value_mid],
            [t("High", "高值"), param.value_high],
          ] as const
        ).map(([k, v]) => (
          <div key={k} className="rounded-md bg-ink-50 py-1">
            <dt className="text-[11px] uppercase tracking-wide text-ink-500">{k}</dt>
            <dd className="text-sm font-semibold tabular text-ink-900">
              {fmtInput(v)} <span className="text-xs font-normal text-ink-500">{param.unit}</span>
            </dd>
          </div>
        ))}
      </dl>
      <div className="mt-2 text-xs text-ink-700">
        {param.source_url || param.source_title ? (
          <p>
            {t("Source:", "来源：")}{" "}
            {param.source_url ? (
              <a className="link" href={param.source_url} target="_blank" rel="noreferrer">
                {param.source_title ?? param.source_url}
              </a>
            ) : (
              param.source_title
            )}
            {param.source_year ? ` (${param.source_year})` : ""}
          </p>
        ) : (
          !param.assumption && <p className="text-caution-900">{t("No source recorded.", "未记录来源。")}</p>
        )}
        {param.id.startsWith("ef.wtt.") && (
          <p className="mt-1 text-ink-600">{t("Well-to-tank factor. The source line above is the library entry; it is not a modelled default.", "燃料上游排放因子。上方来源行对应参数库条目，并非模型默认值。")}</p>
        )}
        {param.assumption && (
          <p className="mt-1">
            <span className="font-semibold">{t("Rationale:", "依据：")}</span> {param.rationale ?? t("No rationale recorded.", "未记录依据。")}
          </p>
        )}
      </div>
    </li>
  );
}

function Drivers({ drivers, library }: { drivers: Driver[]; library: Map<string, Parameter> | null }) {
  useTranslation();
  const max = Math.max(...drivers.map((d) => d.share), 0.0001);
  return (
    <ol className="space-y-2" data-testid="provenance-drivers">
      {drivers.map((d, i) => (
        <li key={d.parameter_id} className="text-sm">
          <div className="flex justify-between gap-2">
            <span className="text-ink-800">
              <span className="tabular text-ink-500">{i + 1}.</span> {d.label ?? library?.get(d.parameter_id)?.label ?? d.parameter_id}
            </span>
            <span className="tabular font-semibold text-ink-900">{Math.round(d.share * 100)}%</span>
          </div>
          <div className="mt-1 h-1.5 rounded-full bg-ink-100" aria-hidden>
            <div className="h-full rounded-full bg-accent-600" style={{ width: `${(d.share / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ol>
  );
}

const DRIVER_METRIC: Record<string, string> = {
  cost_usd: "cost_usd",
  site_staff_hours: "site_staff_hours",
  patient_travel_hours: "patient_travel_hours",
  duration_months: "duration_months",
  co2e_kg: "co2e_kg",
};

export function ProvenanceDrawer({
  target,
  result,
  designId,
  designVersion,
  levers,
  onClose,
}: {
  target: ProvenanceTarget | null;
  result: ScenarioResultX | null;
  /** design + levers of the shown result, for the top-drivers ranking */
  designId: string | null;
  designVersion: number | null;
  levers: Levers | null;
  onClose: () => void;
}) {
  const currentTranslation = useTranslation();
  const lib = useParamLibrary();
  const library = lib.status === "ready" ? lib.byId : null;

  const view = useMemo(() => {
    if (!target || !result) return null;
    if (target.kind === "metric") {
      const def = METRIC_BY_KEY[target.key];
      const { items, matched } = provenanceForMetric(result, target.key);
      return { title: def.label, range: result[target.key] as MetricRange, items, matched, metric: target.key as string };
    }
    if (target.kind === "waste") {
      const items = allProvenance(result).filter((p) => p.formula_id.startsWith("supply.") || p.module === "drug_supply");
      return { title: t("Drug waste share", "药物浪费比例"), range: result.drug_waste_share, items, matched: items.length > 0, metric: "drug_waste_share" };
    }
    const mod = findModule(result, target.module);
    const items: Item[] = (mod?.provenance ?? []).map((p) => ({ ...p, module: target.module }));
    return { title: moduleLabel(target.module), range: mod?.cost_usd ?? null, carbon: mod?.co2e_kg ?? null, items, matched: true, metric: null };
  }, [target, result, currentTranslation]);

  const [drivers, setDrivers] = useState<Driver[] | null>(null);
  const [driversState, setDriversState] = useState<"idle" | "loading" | "error">("idle");
  const metricForDrivers = view?.metric ? DRIVER_METRIC[view.metric] : undefined;
  const leversKey = JSON.stringify(levers);

  useEffect(() => {
    setDrivers(null);
    if (!metricForDrivers || !designId || !levers) return;
    const ctrl = new AbortController();
    setDriversState("loading");
    api
      .drivers(designId, levers, metricForDrivers, { signal: ctrl.signal, silent: true, designVersion })
      .then((d) => {
        setDrivers(d);
        setDriversState("idle");
      })
      .catch((err) => {
        if (!isAbort(err)) setDriversState("error");
      });
    return () => ctrl.abort();
    // leversKey stands in for the levers object
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metricForDrivers, designId, designVersion, leversKey]);

  const paramIds = useMemo(() => [...new Set((view?.items ?? []).flatMap((i) => i.parameter_ids))], [view]);

  return (
    <Drawer
      open={target !== null && view !== null}
      onClose={onClose}
      title={view ? t(`Calculation: ${view.title}`, `测算明细：${target?.kind === "metric" ? metricLabel(target.key) : view.title}`) : ""}
      subtitle={
        view?.range ? (
          <span className="tabular">
            P50 <strong className="text-ink-800">{formatValue(view.range.p50, view.range.unit)}</strong> · P10–P90 {formatRange(view.range)}
            {"carbon" in view && view.carbon ? t(` · carbon ${formatValue(view.carbon.p50, "kg_co2e")}`, ` · 碳排放 ${formatValue(view.carbon.p50, "kg_co2e")}`) : ""}
          </span>
        ) : undefined
      }
    >
      {view && result && (
        <div className="space-y-6" data-testid="provenance-drawer">
          {target?.kind === "module" && isExtensionModule(target.module) && (
            <p className="rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-700">
              <Badge tone="neutral">{t("Extension", "扩展")}</Badge> {t("This module goes beyond the published Low Carbon Clinical Trials Group method.", "此模块超出已发表的低碳临床试验组方法范围。")}
            </p>
          )}
          <section>
            <h3 className="card-title mb-2">{t("Formula", "公式")}{t(view.items.length === 1 ? "" : "s", "")}</h3>
            {!view.matched && view.items.length > 0 && (
              <p className="mb-2 text-xs text-ink-500">{t("No metric-specific formula; all result formulas shown.", "暂无指标专属公式，展示全部结果公式。")}</p>
            )}
            {view.items.length === 0 ? (
              <p className="text-sm text-ink-500">{t("Calculation source unavailable", "暂无计算来源")}</p>
            ) : (
              <ul className="space-y-2">
                {view.items.map((it, i) => (
                  <FormulaCard key={`${it.formula_id}-${it.module}-${i}`} item={it} />
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3 className="card-title mb-2">{t("Parameters (", "参数（")}{paramIds.length}{t(")", "）")}</h3>
            {lib.status === "loading" && <Spinner label={t("Loading parameter library", "正在加载参数库")} />}
            {lib.status === "error" && <p className="text-sm text-worse-800">{t("Parameter library unavailable:", "参数库不可用：")} {lib.message}</p>}
            {library && (
              <ul className="space-y-2">
                {paramIds.map((id) => (
                  <ParameterRow key={id} id={id} param={library.get(id)} />
                ))}
              </ul>
            )}
          </section>

          {view.metric && (
            <section>
              <h3 className="card-title mb-2">{t("Sensitivity drivers", "敏感性因素")}</h3>
              {drivers && drivers.length > 0 ? (
                <Drivers drivers={drivers} library={library} />
              ) : driversState === "loading" ? (
                <Spinner label={t("Ranking parameters", "正在排序参数")} />
              ) : driversState === "error" ? (
                <p className="text-sm text-worse-800">{t("Could not load the top drivers.", "无法加载主要影响因素。")}</p>
              ) : (
                <p className="text-sm text-ink-500">{t("No driver ranking returned.", "未返回影响因素排序。")}</p>
              )}
            </section>
          )}

          {result.warnings.length > 0 && (
            <section>
              <h3 className="card-title mb-2">{t("Items to confirm", "待确认事项")}</h3>
              <ul className="list-disc space-y-1 pl-5 text-sm text-ink-700">
                {result.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </section>
          )}

          <p className="border-t border-ink-100 pt-3 text-xs text-ink-500">
            {t("Parameter set", "参数集")} <code className="font-mono">{result.parameter_set_version}</code> {t("· computed", "· 计算于")} {formatUtc(result.computed_at)} {t("· Monte Carlo, triangular(low, mid, high) per parameter.", "· 蒙特卡洛模拟，各参数采用三角分布（低值、中值、高值）。")}
          </p>
        </div>
      )}
    </Drawer>
  );
}

import { useTranslation, translate as t } from "@/app/i18n";
import type { MetricRange } from "@/app/contracts";
import { formatRange, formatSignedPct, formatSignedValue, formatValue, splitValue } from "@/app/format";
import { Skeleton } from "@/app/ui";
import { delta, isKnownRange, metricLabel, metricDescription, type KnownRange, type MetricDef } from "../metrics";

/** Delta vs baseline with sign, arrow and words — never colour alone. */
export function DeltaText({ current, baseline, testId }: { current: MetricRange; baseline: MetricRange; testId?: string }) {
  useTranslation();
  if (!isKnownRange(current) || !isKnownRange(baseline)) {
    return (
      <span data-testid={testId} className="text-sm font-medium text-ink-500">
        {t("Change unavailable", "暂无变化数据")}
      </span>
    );
  }
  const d = delta(current, baseline);
  if (d.direction === "same") {
    return (
      <span data-testid={testId} className="inline-flex items-center gap-1 text-sm font-semibold text-ink-500">
        <span aria-hidden>●</span> {t("No change vs baseline", "较基线无变化")}
      </span>
    );
  }
  const better = d.direction === "lower";
  return (
    <span
      data-testid={testId}
      className={`inline-flex flex-wrap items-center gap-x-1 text-sm font-semibold ${better ? "text-better-700" : "text-worse-700"}`}
    >
      <span aria-hidden>{better ? "▼" : "▲"}</span>
      <span>{formatSignedPct(d.pct)}</span>
      <span className="font-medium">
        ({formatSignedValue(d.abs, current.unit)}) {better ? t("lower", "降低") : t("higher", "升高")}
      </span>
    </span>
  );
}

/** A small P10–P90 bar with the P50 tick; baseline band drawn faintly behind it. */
function RangeBar({ current, baseline }: { current: KnownRange; baseline: KnownRange | null }) {
  useTranslation();
  const lo = Math.min(current.p10, baseline?.p10 ?? current.p10);
  const hi = Math.max(current.p90, baseline?.p90 ?? current.p90);
  const span = hi - lo || 1;
  const pos = (v: number) => `${((v - lo) / span) * 100}%`;
  const width = (a: number, b: number) => `${Math.max(((b - a) / span) * 100, 1)}%`;
  return (
    <div className="relative mt-3 h-2.5 rounded-full bg-ink-100" aria-hidden>
      {baseline && (
        <div className="absolute top-0 h-full rounded-full bg-ink-300/60" style={{ left: pos(baseline.p10), width: width(baseline.p10, baseline.p90) }} />
      )}
      <div className="absolute top-0 h-full rounded-full bg-accent-500/70" style={{ left: pos(current.p10), width: width(current.p10, current.p90) }} />
      <div className="absolute -top-1 h-[18px] w-[3px] -translate-x-1/2 rounded bg-accent-900" style={{ left: pos(current.p50) }} />
    </div>
  );
}

export function MetricCard({
  def,
  current,
  baseline,
  computing,
  onOpen,
}: {
  def: MetricDef;
  current: MetricRange | null;
  baseline: MetricRange | null;
  computing: boolean;
  onOpen: () => void;
}) {
  useTranslation();
  const known = isKnownRange(current);
  const big = current && known ? splitValue(current.p50, current.unit) : null;
  return (
    <section className="card relative flex flex-col p-4" aria-labelledby={`metric-${def.key}-label`} data-testid={`metric-${def.key}`}>
      <div className="flex items-start justify-between gap-2">
        <h3 id={`metric-${def.key}-label`} className="card-title" title={metricDescription(def.key)}>
          {metricLabel(def.key)}
        </h3>
        {computing && current && (
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-ink-200 border-t-accent-700" role="status" aria-label={t("Recomputing", "重新计算中")} />
        )}
      </div>
      {current && big ? (
        <>
          <button
            type="button"
            onClick={onOpen}
            className="num-button -mx-1 mt-1 px-1"
            aria-label={t(`${def.label}: median ${formatValue(current.p50, current.unit)}, P10 to P90 ${formatRange(current)}. Show how this is calculated.`, `${metricLabel(def.key)}：中位数 ${formatValue(current.p50, current.unit)}，P10 至 P90 ${formatRange(current)}。查看计算方式。`)}
            data-testid={`metric-${def.key}-value`}
          >
            <span className={`flex items-baseline gap-1.5 whitespace-nowrap text-metric tabular text-ink-900 transition-opacity ${computing ? "opacity-60" : ""}`}>
              {big.num}
              {big.unit && <span className="text-base font-semibold text-ink-500">{big.unit}</span>}
            </span>
            <span className="mt-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">{t("P10–P90 range", "P10–P90 区间")}</span>
            <span className="block whitespace-nowrap text-sm text-ink-700 tabular">{formatRange(current)}</span>
          </button>
          {isKnownRange(current) && <RangeBar current={current} baseline={isKnownRange(baseline) ? baseline : null} />}
          <div className="mt-3 min-h-[2.5rem]">
            {baseline ? <DeltaText current={current} baseline={baseline} testId={`metric-${def.key}-delta`} /> : <Skeleton className="h-4 w-40" />}
          </div>
          <button type="button" onClick={onOpen} className="link mt-auto self-start pt-1 text-xs">
            {t("Calculation details", "测算明细")}
          </button>
        </>
      ) : current && !known ? (
        <button type="button" onClick={onOpen} className="num-button -mx-1 mt-1 px-1 text-left" data-testid={`metric-${def.key}-value`}>
          <span className="block text-metric text-ink-500">{t("Unknown", "未知")}</span>
          <span className="mt-1 block text-sm text-ink-600">{t("Input required", "待补充输入")}</span>
        </button>
      ) : (
        <div className="mt-2 space-y-2" aria-busy="true">
          <Skeleton className="h-9 w-32" />
          <Skeleton className="h-4 w-44" />
          <Skeleton className="mt-3 h-2.5 w-full" />
          <Skeleton className="h-4 w-36" />
        </div>
      )}
    </section>
  );
}

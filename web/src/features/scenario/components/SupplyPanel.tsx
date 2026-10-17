import { useTranslation, translate as t } from "@/app/i18n";
import type { MetricRange } from "@/app/contracts";
import { formatBare, formatPercent, formatRange, formatValue } from "@/app/format";
import type { ScenarioResultX } from "@/app/api/types";
import { Badge, Skeleton } from "@/app/ui";
import { isKnownRange } from "../metrics";
import { DeltaText } from "./MetricCard";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  useTranslation();
  return (
    <div>
      <dt className="text-xs text-ink-500">{label}</dt>
      <dd className="text-lg font-bold tabular text-ink-900">{value}</dd>
      {sub && <dd className="text-xs tabular text-ink-500">{sub}</dd>}
    </div>
  );
}

const fmtRange = (r: MetricRange | null) => (r && isKnownRange(r) ? formatValue(r.p50, r.unit) : r ? t("unknown", "未知") : "—");
const subRange = (r: MetricRange | null) => (r && isKnownRange(r) ? `P10–P90 ${formatRange(r)}` : r ? t("unknown — not zero", "未知，而非零") : t("not reported", "未报告"));

/** Drug supply: kits produced / wasted, waste share, stockout risk (A3 supply simulation). */
export function SupplyPanel({
  result,
  baseline,
  strategy,
  onOpen,
}: {
  result: ScenarioResultX | null;
  baseline: ScenarioResultX | null;
  strategy: "upfront" | "on_demand";
  onOpen: () => void;
}) {
  useTranslation();
  if (!result) {
    return (
      <section className="card p-4">
        <h2 className="card-title mb-3">{t("Drug supply", "药物供应")}</h2>
        <Skeleton className="h-40 w-full" />
      </section>
    );
  }
  const s = result.supply;
  const stockout = s?.stockout_probability ?? null;
  return (
    <section className="card p-4" aria-labelledby="supply-title" data-testid="supply-panel">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="supply-title" className="card-title">
          {t("Drug supply", "药物供应")}
        </h2>
        <Badge tone="neutral">{strategy === "upfront" ? t("Upfront stocking", "预先备货") : t("On-demand resupply", "按需补货")}</Badge>
      </div>
      {s && <p className="mb-2 text-xs text-ink-500" data-testid="supply-sampling">
        {t("Supply draws:", "供应抽样次数：")} {s.draws_used ?? t("unknown", "未知")} {t("of", "共")} {s.draws_requested ?? t("unknown", "未知")} {t("requested.", "次请求。")}
      </p>}
      <button type="button" className="num-button -mx-1 block w-[calc(100%+0.5rem)] px-1 py-1" onClick={onOpen} aria-label={t("Show how drug waste is calculated", "查看药物浪费的计算方式")}>
        <span className="text-xs text-ink-500">{t("Kits wasted (share of produced)", "浪费药包（占生产总量比例）")}</span>
        <span className="block text-2xl font-bold tabular text-ink-900">{formatPercent(result.drug_waste_share.p50)}</span>
        <span className="block text-xs tabular text-ink-500">P10–P90 {formatRange(result.drug_waste_share)}</span>
      </button>
      {baseline && (
        <div className="mt-1">
          <DeltaText current={result.drug_waste_share} baseline={baseline.drug_waste_share} />
        </div>
      )}
      {s ? (
      <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-ink-100 pt-3">
        <Stat label={t("Kits produced", "已生产药包")} value={fmtRange(s?.kits_produced ?? null)} sub={subRange(s?.kits_produced ?? null)} />
        <Stat label={t("Kits wasted", "已浪费药包")} value={fmtRange(s?.kits_wasted ?? null)} sub={subRange(s?.kits_wasted ?? null)} />
        <Stat
          label={t("Kit shipments", "药包运输次数")}
          value={s?.shipments ? formatBare(s.shipments.p50, s.shipments.unit === "count" ? "count" : s.shipments.unit) : "—"}
          sub={
            s?.shipments
              ? isKnownRange(s.shipments)
                ? `P10–P90 ${formatBare(s.shipments.p10, s.shipments.unit)} – ${formatBare(s.shipments.p90, s.shipments.unit)}`
                : t("unknown — not zero", "未知，而非零")
              : t("not reported", "未报告")
          }
        />
        <div>
          <dt className="text-xs text-ink-500">{t("Stockout risk", "缺货风险")}</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{stockout === null ? "—" : formatPercent(stockout * 100)}</dd>
          <dd className="text-xs text-ink-500">
            {stockout === null ? t("not reported", "未报告") : stockout >= 0.05 ? t("⚠ share of simulations with any stockout", "⚠ 出现缺货的模拟占比") : t("share of simulations with any stockout", "出现缺货的模拟占比")}
          </dd>
        </div>
      </dl>
      ) : (
        <p className="mt-4 border-t border-ink-100 pt-3 text-xs text-ink-500" data-testid="supply-missing">
          {t("Kit counts, shipment counts and stockout risk were not in this compute response. The waste share above is the only supply figure returned. No kit series is estimated.", "此次计算结果未包含药包数量、运输次数及缺货风险。上方浪费比例是唯一返回的供应指标，未估算药包序列。")}
        </p>
      )}
    </section>
  );
}

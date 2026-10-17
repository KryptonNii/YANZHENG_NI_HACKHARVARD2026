import type { MetricRange } from "@/app/contracts";
import { formatBare, formatPercent, formatRange, formatValue } from "@/app/format";
import type { ScenarioResultX } from "@/app/api/types";
import { Badge, Skeleton } from "@/app/ui";
import { DeltaText } from "./MetricCard";

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <dt className="text-xs text-ink-500">{label}</dt>
      <dd className="text-lg font-bold tabular text-ink-900">{value}</dd>
      {sub && <dd className="text-xs tabular text-ink-500">{sub}</dd>}
    </div>
  );
}

const fmtRange = (r: MetricRange | null) => (r ? formatValue(r.p50, r.unit) : "—");
const subRange = (r: MetricRange | null) => (r ? `P10–P90 ${formatRange(r)}` : "not reported");

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
  if (!result) {
    return (
      <section className="card p-4">
        <h2 className="card-title mb-3">Drug supply</h2>
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
          Drug supply
        </h2>
        <Badge tone="neutral">{strategy === "upfront" ? "Upfront stocking" : "On-demand resupply"}</Badge>
      </div>
      <button type="button" className="num-button -mx-1 block w-[calc(100%+0.5rem)] px-1 py-1" onClick={onOpen} aria-label="Show how drug waste is calculated">
        <span className="text-xs text-ink-500">Kits wasted (share of produced)</span>
        <span className="block text-2xl font-bold tabular text-ink-900">{formatPercent(result.drug_waste_share.p50)}</span>
        <span className="block text-xs tabular text-ink-500">P10–P90 {formatRange(result.drug_waste_share)}</span>
      </button>
      {baseline && (
        <div className="mt-1">
          <DeltaText current={result.drug_waste_share} baseline={baseline.drug_waste_share} />
        </div>
      )}
      <dl className="mt-4 grid grid-cols-2 gap-3 border-t border-ink-100 pt-3">
        <Stat label="Kits produced" value={fmtRange(s?.kits_produced ?? null)} sub={subRange(s?.kits_produced ?? null)} />
        <Stat label="Kits wasted" value={fmtRange(s?.kits_wasted ?? null)} sub={subRange(s?.kits_wasted ?? null)} />
        <Stat
          label="Kit shipments"
          value={s?.shipments ? formatBare(s.shipments.p50, "count") : "—"}
          sub={s?.shipments ? `P10–P90 ${formatBare(s.shipments.p10, "count")} – ${formatBare(s.shipments.p90, "count")}` : "not reported"}
        />
        <div>
          <dt className="text-xs text-ink-500">Stockout risk</dt>
          <dd className="text-lg font-bold tabular text-ink-900">{stockout === null ? "—" : formatPercent(stockout * 100)}</dd>
          <dd className="text-xs text-ink-500">
            {stockout === null ? "not reported" : stockout >= 0.05 ? "⚠ share of simulations with any stockout" : "share of simulations with any stockout"}
          </dd>
        </div>
      </dl>
      {!s && <p className="mt-2 text-xs text-ink-500">Kit counts and stockout risk were not returned by the API for this scenario.</p>}
    </section>
  );
}

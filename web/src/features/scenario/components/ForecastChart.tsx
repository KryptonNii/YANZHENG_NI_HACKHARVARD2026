import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatRange, formatValue, humanize } from "@/app/format";
import type { ScenarioResultX } from "@/app/api/types";
import { Skeleton } from "@/app/ui";

const MILESTONE_LABELS: Record<string, string> = {
  first_patient_in: "First patient in",
  last_patient_in: "Last patient in",
  last_patient_last_visit: "Last patient, last visit",
  database_lock: "Database lock",
};

/** Enrollment forecast: P10–P90 ribbon + P50 line (A3), with milestone ranges. */
export function ForecastChart({ result, target }: { result: ScenarioResultX | null; target: number }) {
  if (!result) {
    return (
      <section className="card p-4">
        <h2 className="card-title mb-3">Enrollment forecast</h2>
        <Skeleton className="h-48 w-full" />
      </section>
    );
  }
  const curve = result.forecast?.enrollment_curve ?? [];
  const data = curve.map(([month, p10, p50, p90]) => ({ month, base: p10, band: p90 !== null && p10 !== null ? p90 - p10 : null, p10, p50, p90 }));
  const hasCurve = data.filter((row) => row.p50 !== null).length > 1;
  const milestones = Object.entries(result.forecast?.milestone_dates ?? {});

  return (
    <section className="card p-4" aria-labelledby="forecast-title" data-testid="forecast-chart">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="forecast-title" className="card-title">
          Enrollment forecast
        </h2>
        <span className="text-xs text-ink-500">Cumulative patients · P10–P90 band, P50 line · target {target.toLocaleString("en-US")}</span>
      </div>
      {result.forecast && <p className="mb-2 text-xs text-ink-500" data-testid="forecast-sampling">
        Forecast draws: {result.forecast.draws_used ?? "unknown"} of {result.forecast.draws_requested ?? "unknown"} requested. Curve draws: {result.forecast.curve_draws_used ?? "unknown"}.
      </p>}
      {hasCurve ? (
        <div className="h-48" role="img" aria-label={`Enrollment forecast. Time to full enrollment ${result.forecast?.months_to_full_enrollment ? formatRange(result.forecast.months_to_full_enrollment) : "not reported"}.`}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={data} margin={{ left: 0, right: 12, top: 6, bottom: 0 }}>
              <CartesianGrid stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="month" type="number" domain={["dataMin", "dataMax"]} tick={{ fontSize: 12, fill: "#64748b" }} tickFormatter={(m: number) => `${m} mo`} />
              <YAxis tick={{ fontSize: 12, fill: "#64748b" }} width={44} />
              <Tooltip
                formatter={(_v: number, name: string, item: { payload?: { p10: number | null; p50: number | null; p90: number | null } }) => {
                  const p = item.payload;
                  if (!p || p.p10 === null || p.p50 === null || p.p90 === null) return ["unknown", name];
                  if (name === "band") return [`${Math.round(p.p10)} – ${Math.round(p.p90)}`, "P10–P90"];
                  if (name === "p50") return [Math.round(p.p50), "P50"];
                  return [null, null];
                }}
                labelFormatter={(m: number) => `Month ${m}`}
              />
              <Area dataKey="base" stackId="r" stroke="none" fill="transparent" isAnimationActive={false} legendType="none" tooltipType="none" />
              <Area dataKey="band" stackId="r" stroke="none" fill="#14b8a6" fillOpacity={0.22} isAnimationActive={false} />
              <Line dataKey="p50" stroke="#0f766e" strokeWidth={2.5} dot={false} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="rounded-lg bg-ink-50 px-4 py-3 text-sm text-ink-600" data-testid="forecast-missing">
          <p>
            Duration (P50) <strong className="tabular text-ink-900">{formatValue(result.duration_months.p50, "months")}</strong>, P10–P90{" "}
            <span className="tabular">{formatRange(result.duration_months)}</span>.
          </p>
          <p className="mt-1 text-xs text-ink-500">
            {result.forecast
              ? "The compute response included a forecast, but no enrollment curve. Nothing is drawn from the duration alone."
              : "This compute response has no enrollment forecast. The duration above is the only timeline figure. No curve is estimated."}
          </p>
        </div>
      )}
      {milestones.length > 0 && (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
          {milestones.map(([k, r]) => (
            <div key={k}>
              <dt className="text-xs text-ink-500">{MILESTONE_LABELS[k] ?? humanize(k)}</dt>
              <dd className="tabular font-semibold text-ink-800">
                {formatValue(r.p50, "months")} <span className="text-xs font-normal text-ink-500">({formatRange(r)})</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

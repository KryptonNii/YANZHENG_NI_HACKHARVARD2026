import type { Band, CountryRow, SiteRow, WeeklyEnrollment } from "./api";

/** Sum aligned site bounds, only where every constituent has that week's data. */
export function countryEnrollment(country: CountryRow, sites: SiteRow[]): WeeklyEnrollment | null {
  const members = sites.filter((s) => s.country === country.country);
  if (!members.length || members.length !== country.n_sites || members.some((s) => !s.weekly_enrollment)) return null;
  const series = members.map((s) => s.weekly_enrollment).filter((s): s is WeeklyEnrollment => s !== null && s !== undefined);
  const length = Math.max(...series.map((s) => s.actual_cumulative.length));
  return {
    actual_cumulative: Array.from({ length }, (_, i) => {
      const values = series.map((s) => s.actual_cumulative[i]);
      if (!values.every((v): v is number => v !== null && v !== undefined)) return null;
      return values.reduce((sum, v) => sum + v, 0);
    }),
    plan: Array.from({ length }, (_, i) => {
      const bands = series.map((s) => s.plan[i]);
      if (!bands.every((b): b is Band => b !== null && b !== undefined)) return null;
      return bands.reduce<Band>((sum, b) => ({ p10: sum.p10 + b.p10, p50: sum.p50 + b.p50, p90: sum.p90 + b.p90 }), { p10: 0, p50: 0, p90: 0 });
    }),
  };
}

function segments<T>(values: (T | null)[]): { value: T; index: number }[][] {
  const runs: { value: T; index: number }[][] = [];
  values.forEach((value, index) => {
    if (value === null) return;
    if (index === 0 || values[index - 1] === null) runs.push([]);
    runs[runs.length - 1].push({ value, index });
  });
  return runs;
}

export function EnrollmentChart({ series }: { series: WeeklyEnrollment | null }) {
  if (!series) return <span className="text-xs text-ink-500">Weekly history unavailable</span>;
  const n = series.actual_cumulative.length;
  if (!n) return <span className="text-xs text-ink-500">No complete weeks yet</span>;
  const max = Math.max(1, ...series.actual_cumulative.filter((v): v is number => v !== null), ...series.plan.flatMap((b) => b ? [b.p90] : []));
  const x = (i: number) => 6 + (n === 1 ? 84 : i / (n - 1) * 168);
  const y = (v: number) => 40 - v / max * 35;
  const last = series.actual_cumulative[n - 1];
  const b = series.plan[n - 1];
  const gaps = series.actual_cumulative.some((v) => v === null) || series.plan.some((v) => v === null);
  const label = `${n} complete weeks; last cumulative ${last ?? "unknown"}; plan P10–P90 ${b ? `${Math.round(b.p10)}–${Math.round(b.p90)}` : "unknown"}${gaps ? "; gaps in weekly data" : ""}`;
  return (
    <svg viewBox="0 0 180 54" className="h-14 w-44 shrink-0" role="img" aria-label={label} data-testid="weekly-enrollment">
      <title>{label}</title>
      <path d="M6 40H174" stroke="#cbd5e1" />
      {segments(series.plan).map((run) => (
        <g key={run[0].index}>
          <polygon points={[...run.map(({ value, index }) => `${x(index)},${y(value.p90)}`), ...[...run].reverse().map(({ value, index }) => `${x(index)},${y(value.p10)}`)].join(" ")} fill="#cbd5e1" fillOpacity="0.65" />
          <polyline points={run.map(({ value, index }) => `${x(index)},${y(value.p50)}`).join(" ")} fill="none" stroke="#64748b" strokeDasharray="3 2" />
          {run.length === 1 && <path d={`M${x(run[0].index)} ${y(run[0].value.p10)}V${y(run[0].value.p90)}`} stroke="#64748b" />}
        </g>
      ))}
      {segments(series.actual_cumulative).map((run) => <polyline key={run[0].index} points={run.map(({ value, index }) => `${x(index)},${y(value)}`).join(" ")} fill="none" stroke="#0f766e" strokeWidth="2" />)}
      {series.actual_cumulative.map((value, i) => {
        const band = series.plan[i];
        return value !== null && (
        <circle key={i} cx={x(i)} cy={y(value)} r="1.7" fill="#0f766e">
          <title>Week {i + 1} · day {7 * (i + 1)}: actual {value}; plan {band ? `${band.p10.toFixed(1)} / ${band.p50.toFixed(1)} / ${band.p90.toFixed(1)}` : "unknown"}</title>
        </circle>
      ); })}
      <text x="6" y="52" fontSize="8" fill="#64748b">W1</text>
      <text x="174" y="52" textAnchor="end" fontSize="8" fill="#64748b">W{n} · {max.toFixed(0)} max</text>
    </svg>
  );
}

import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Intervention } from "@/app/contracts";
import { formatUtc, isNum } from "@/app/format";
import { Badge } from "@/app/ui";
import type { EffectDetail } from "./api";
import { startIntervention } from "./api";
import { VERDICT, rangeText } from "./present";

export function InterventionsPanel({ trialId, interventions, effects, onChanged }: { trialId: string; interventions: Intervention[]; effects: EffectDetail[]; onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const start = async (id: string) => {
    setBusy(id);
    setError(null);
    try { await startIntervention(trialId, id); await onChanged(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(null); }
  };
  const byId = new Map(effects.map((e) => [e.estimate.intervention_id, e]));
  return (
    <section className="card p-4" data-testid="intervention-list" aria-label="Interventions">
      <h2 className="card-title mb-3">Interventions</h2>
      {error && <p role="alert" className="mb-3 text-sm text-worse-900">{error}</p>}
      {interventions.length === 0 && <p className="text-sm text-ink-500">No interventions yet. Plan one from an alert.</p>}
      <ul className="space-y-4">
        {interventions.map((iv) => {
          const effect = byId.get(iv.id);
          const verdict = effect ? VERDICT[effect.estimate.verdict] : undefined;
          return (
            <li key={iv.id} className="rounded-lg border border-ink-200 p-3" data-testid={`intervention-${iv.id}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={iv.status === "done" ? "better" : iv.status === "in_progress" ? "accent" : "neutral"}>{iv.status.replaceAll("_", " ")}</Badge>
                <p className="text-sm font-semibold text-ink-900">{iv.action}</p>
              </div>
              <p className="mt-1 text-xs text-ink-500">
                Owner {iv.owner} · due {formatUtc(iv.due_date)} · metric {iv.metric.replaceAll("_", " ")} · sites {iv.target_site_ids.join(", ") || "—"}
              </p>
              {iv.status === "planned" && <button type="button" className="btn-secondary mt-2" disabled={busy !== null} onClick={() => void start(iv.id)}>{busy === iv.id ? "Starting…" : "Start intervention"}</button>}
              {effect && verdict ? (
                <EffectCard effect={effect} />
              ) : (
                <p className="mt-2 text-xs text-ink-500">Effect is estimated after the intervention has started and the clock moves forward.</p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function EffectCard({ effect }: { effect: EffectDetail }) {
  const est = effect.estimate;
  const verdict = VERDICT[est.verdict] ?? { label: est.verdict, tone: "neutral" as const };
  const v = effect.values;
  const chart =
    v && isNum(v.treated_pre) && isNum(v.treated_post) && isNum(v.control_pre) && isNum(v.control_post)
      ? [
          { phase: "Before", treated: v.treated_pre, control: v.control_pre },
          { phase: "After", treated: v.treated_post, control: v.control_post },
        ]
      : null;
  return (
    <div className="mt-3 rounded-lg bg-ink-50 p-3" data-testid="effect-card">
      <div className="flex flex-wrap items-center gap-2">
        <span data-testid="effect-verdict">
          <Badge tone={verdict.tone}>{verdict.label}</Badge>
        </span>
        <span className="text-xs text-ink-500">Difference-in-differences · effect {rangeText(est.effect)}</span>
      </div>
      <p className="mt-1 text-xs tabular text-ink-600">
        Treated change {formatSigned(est.treated_change)} · control change {formatSigned(est.control_change)}
      </p>
      <p className="mt-2 text-sm leading-relaxed text-ink-800">{est.explanation}</p>
      {chart && (
        <div className="mt-3 h-36" role="img" aria-label="Before and after, treated sites and control sites">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chart} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
              <CartesianGrid stroke="#e2e8f0" vertical={false} />
              <XAxis dataKey="phase" tick={{ fontSize: 12, fill: "#64748b" }} />
              <YAxis tick={{ fontSize: 11, fill: "#64748b" }} width={40} />
              <Tooltip />
              <Legend />
              <Line type="linear" dataKey="treated" name="Treated" stroke="#0f766e" strokeWidth={2} dot isAnimationActive={false} />
              <Line type="linear" dataKey="control" name="Control sites" stroke="#64748b" strokeWidth={2} strokeDasharray="4 3" dot isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {effect.control_units && effect.control_units.length > 0 && (
        <p className="mt-1 text-[11px] text-ink-500">
          Controls ({effect.control_tier || "matched"}): {effect.control_units.join(", ")}
        </p>
      )}
    </div>
  );
}

function formatSigned(n: number | null | undefined): string {
  if (!isNum(n)) return "unknown";
  const rounded = Math.abs(n) >= 10 ? Math.round(n) : Math.round(n * 10) / 10;
  if (rounded === 0) return "0";
  return `${rounded > 0 ? "+" : "−"}${Math.abs(rounded)}`;
}

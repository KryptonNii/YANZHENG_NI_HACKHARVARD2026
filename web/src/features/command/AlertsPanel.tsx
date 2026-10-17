import { useState } from "react";
import type { Alert } from "@/app/contracts";
import { Badge, Modal } from "@/app/ui";
import { ApiError, patchAlert, createIntervention } from "./api";
import { IMPACT_KEYS, IMPACT_LABEL, impactText, statusTone } from "./present";

const ACTIVE = new Set<Alert["status"]>(["open", "acknowledged", "action_planned"]);

function severityTone(severity: Alert["severity"]) {
  if (severity === "critical") return "worse" as const;
  if (severity === "warning") return "caution" as const;
  return "accent" as const;
}

export function AlertsPanel({
  trialId,
  alerts,
  owner,
  onChanged,
}: {
  trialId: string;
  alerts: Alert[];
  owner: string;
  onChanged: () => Promise<void> | void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dismissId, setDismissId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [planning, setPlanning] = useState<Alert | null>(null);

  const visible = showAll ? alerts : alerts.filter((a) => ACTIVE.has(a.status));

  const run = async (id: string, fn: () => Promise<unknown>) => {
    setBusyId(id);
    setError(null);
    try {
      await fn();
      await onChanged();
      return true;
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
      return false;
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="card flex flex-col" data-testid="alerts-panel" aria-label="Alerts">
      <header className="flex items-center justify-between gap-2 border-b border-ink-200 px-4 py-3">
        <h2 className="card-title">Alerts</h2>
        <button type="button" className="text-xs font-semibold text-accent-700" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "Active only" : `Show all (${alerts.length})`}
        </button>
      </header>
      {error && (
        <p role="alert" className="mx-4 mt-3 rounded-md border border-worse-200 bg-worse-50 px-3 py-2 text-sm text-worse-900">
          {error}
        </p>
      )}
      <ul className="max-h-[36rem] space-y-3 overflow-auto p-4">
        {visible.length === 0 && <li className="text-sm text-ink-500">No active alerts.</li>}
        {visible.map((alert) => (
          <li key={alert.id} className="rounded-lg border border-ink-200 p-3" data-testid={`alert-${alert.kind}`}>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={severityTone(alert.severity)}>{alert.severity}</Badge>
              <Badge tone={statusTone(alert.status === "open" ? "watch" : alert.status === "resolved" ? "on_track" : "unknown")}>{alert.status.replaceAll("_", " ")}</Badge>
              <span className="text-xs uppercase tracking-wide text-ink-400">{alert.kind.replaceAll("_", " ")}</span>
            </div>
            <p className="mt-2 text-sm text-ink-900">{alert.summary}</p>
            <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
              {IMPACT_KEYS.map((key) => (
                <div key={key}>
                  <dt className="text-ink-500">{IMPACT_LABEL[key]}</dt>
                  <dd className="tabular font-medium text-ink-800">{impactText(alert.est_impact?.[key])}</dd>
                </div>
              ))}
            </dl>
            {alert.recommended_actions.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-ink-600">
                {alert.recommended_actions.map((action) => (
                  <li key={action}>{action}</li>
                ))}
              </ul>
            )}
            {dismissId === alert.id ? (
              <form
                className="mt-3 space-y-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!reason.trim()) {
                    setError("A reason is required.");
                    return;
                  }
                  void run(alert.id, () => patchAlert(trialId, alert.id, "dismissed", reason.trim())).then((ok) => {
                    if (!ok) return;
                    setDismissId(null);
                    setReason("");
                  });
                }}
              >
                <label className="label text-xs" htmlFor={`dismiss-${alert.id}`}>
                  Reason for dismissing (audited)
                </label>
                <textarea id={`dismiss-${alert.id}`} className="input mt-1" required value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
                <div className="flex gap-2">
                  <button type="submit" className="btn-danger" disabled={busyId === alert.id}>
                    Dismiss alert
                  </button>
                  <button type="button" className="btn-ghost" onClick={() => setDismissId(null)}>
                    Cancel
                  </button>
                </div>
              </form>
            ) : (
              ACTIVE.has(alert.status) && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {alert.status === "open" && (
                    <button type="button" className="btn-secondary" disabled={busyId === alert.id} onClick={() => void run(alert.id, () => patchAlert(trialId, alert.id, "acknowledged"))}>
                      Acknowledge
                    </button>
                  )}
                  <button type="button" className="btn-primary" disabled={busyId === alert.id} onClick={() => setPlanning(alert)}>
                    Plan intervention
                  </button>
                  <button type="button" className="btn-ghost" disabled={busyId === alert.id} onClick={() => { setDismissId(alert.id); setReason(""); setError(null); }}>
                    Dismiss
                  </button>
                </div>
              )
            )}
          </li>
        ))}
      </ul>
      <PlanDialog
        key={planning?.id ?? "none"}
        alert={planning}
        owner={owner}
        busy={busyId === planning?.id}
        onClose={() => setPlanning(null)}
        onSave={async (action) => {
          if (!planning) return;
          const ok = await run(planning.id, () =>
            createIntervention(trialId, {
              alert_id: planning.id,
              action,
              owner,
              target_site_ids: planning.site_id ? [planning.site_id] : [],
            }),
          );
          if (ok) setPlanning(null);
        }}
      />
    </section>
  );
}

function PlanDialog({
  alert,
  owner,
  busy,
  onClose,
  onSave,
}: {
  alert: Alert | null;
  owner: string;
  busy: boolean;
  onClose: () => void;
  onSave: (action: string) => Promise<void>;
}) {
  const options = alert?.recommended_actions ?? [];
  const [action, setAction] = useState("");
  const selected = action || options[0] || "";
  return (
    <Modal
      open={alert !== null}
      title="Plan intervention"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={busy || selected.trim().length === 0}
            onClick={() => void onSave(selected.trim())}
          >
            {busy ? "Saving…" : "Save intervention"}
          </button>
        </>
      }
    >
      {alert && (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (selected.trim()) void onSave(selected.trim());
          }}
        >
          <p className="text-sm text-ink-700">{alert.summary}</p>
          <div>
            <label className="label" htmlFor="intervention-action">
              Action
            </label>
            {options.length > 0 ? (
              <select
                id="intervention-action"
                className="input mt-1"
                value={selected}
                onChange={(e) => setAction(e.target.value)}
              >
                {options.map((opt) => (
                  <option key={opt} value={opt}>
                    {opt}
                  </option>
                ))}
              </select>
            ) : (
              <input id="intervention-action" className="input mt-1" value={action} onChange={(e) => setAction(e.target.value)} required />
            )}
          </div>
          <p className="text-xs text-ink-500">
            Owner {owner}
            {alert.site_id ? ` · site ${alert.site_id}` : ""}. The metric is taken from the alert. This is written to the audit trail.
          </p>
        </form>
      )}
    </Modal>
  );
}

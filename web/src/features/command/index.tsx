import { displayText } from "./displayText";
import { useTranslation } from "@/app/i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { Alert, Intervention, OpsEvent, ProvenanceItem } from "@/app/contracts";
import { formatUtc } from "@/app/format";
import { useIdentity } from "@/app/identity";
import { EmptyState, ErrorPanel, SimulatedBadge, Spinner } from "@/app/ui";
import {
  ApiError,
  DEMO_TRIAL_ID,
  advanceClock,
  getHealth,
  listAlerts,
  listEffects,
  listEvents,
  listInterventions,
  simulate,
  type ClockInfo,
  type EffectDetail,
  type HealthSnapshot,
} from "./api";
import { AlertsPanel } from "./AlertsPanel";
import { EventTicker } from "./EventTicker";
import { Drilldown, HealthBoard, ProvenanceDrawer } from "./HealthBoard";
import { InterventionsPanel } from "./InterventionsPanel";
import { LockRecoveryStory } from "./LockRecoveryStory";

interface Snapshot {
  health: HealthSnapshot;
  alerts: Alert[];
  interventions: Intervention[];
  effects: EffectDetail[];
  events: OpsEvent[];
}

function isOpsEvent(data: unknown): data is OpsEvent {
  return !!data && typeof data === "object" && "type" in data && "source_system" in data && "occurred_at" in data;
}

export default function CommandPage() {
  const t = useTranslation();
  const { trialId = DEMO_TRIAL_ID } = useParams();
  const me = useIdentity();
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [clock, setClock] = useState<ClockInfo | null>(null);
  const [phase, setPhase] = useState<"loading" | "idle" | "ready" | "error">("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [provenance, setProvenance] = useState<{ item: ProvenanceItem; title: string } | null>(null);
  const seq = useRef(0);
  const reloadRef = useRef<() => Promise<void>>(async () => {});

  const load = useCallback(async () => {
    const token = ++seq.current;
    const health = await getHealth(trialId);
    const [alerts, interventions, effects, events] = await Promise.all([
      listAlerts(trialId),
      listInterventions(trialId),
      listEffects(trialId),
      listEvents(trialId, 20),
    ]);
    if (token !== seq.current) return;
    setSnapshot({ health, alerts, interventions, effects, events });
    setClock(health.clock ?? null);
    setPhase("ready");
    setMessage(null);
  }, [trialId]);

  const refresh = useCallback(async () => {
    try {
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.code === "not_simulated") {
        setSnapshot(null);
        setClock(null);
        setPhase("idle");
        setMessage(null);
        return;
      }
      setPhase("error");
      setMessage(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    }
  }, [load]);

  useEffect(() => {
    reloadRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    setPhase("loading");
    setSnapshot(null);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (phase !== "ready" || typeof EventSource === "undefined") return;
    const source = new EventSource(`/api/ops/${encodeURIComponent(trialId)}/stream`);
    let timer = 0;
    const schedule = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void reloadRef.current(), 400);
    };
    const onEvent = (ev: Event) => {
      const data = (ev as MessageEvent).data;
      let parsed: unknown = data;
      try {
        parsed = JSON.parse(String(data));
      } catch {
        parsed = data;
      }
      if ((ev as MessageEvent).type === "ops_event" && isOpsEvent(parsed)) {
        setSnapshot((cur) => (cur ? { ...cur, events: [parsed, ...cur.events].slice(0, 20) } : cur));
        return;
      }
      schedule();
    };
    for (const kind of ["ops_event", "alert_new", "alert_update", "effect_update", "clock", "simulation_reset"]) {
      source.addEventListener(kind, onEvent);
    }
    return () => {
      window.clearTimeout(timer);
      source.close();
    };
  }, [phase, trialId]);

  const start = async () => {
    setBusy("start");
    setMessage(null);
    try {
      const info = await simulate(trialId);
      setClock(info);
      await load();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
      setPhase((p) => (p === "loading" ? "error" : p));
    } finally {
      setBusy(null);
    }
  };

  const advance = async (days: number) => {
    setBusy("clock");
    setMessage(null);
    try {
      const info = await advanceClock(trialId, days);
      setClock(info);
      await load();
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const title = snapshot?.health.trial_title ?? "Command center";
  const running = phase === "ready";

  return (
    <div className="space-y-4" data-testid="command-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight text-ink-900">{displayText(title)}</h1>
            <span data-testid="simulated-badge">
              <SimulatedBadge />
            </span>
          </div>
          <p className="mt-1 text-sm text-ink-500" data-testid="sim-clock">
            {clock ? (
              <>
                {formatUtc(clock.now)} {t("· day", "· 天")} {Math.round(clock.clock_day)}
                {clock.scenario ? ` · ${clock.scenario}` : ""}
              </>
            ) : (
              t("Not started", "未启动")
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="btn-secondary" data-testid="start-simulation" disabled={busy !== null} onClick={() => void start()}>
            {busy === "start" ? t("Starting…", "启动中…") : running ? t("Restart", "重新运行") : t("Start", "运行")}
          </button>
          <button type="button" className="btn-secondary" data-testid="advance-1-week" disabled={!running || busy !== null} onClick={() => void advance(7)}>
            {t("Advance 1 week", "推进 1 周")}
          </button>
          <button type="button" className="btn-primary" data-testid="advance-6-weeks" disabled={!running || busy !== null} onClick={() => void advance(42)}>
            {t("Advance 6 weeks", "推进 6 周")}
          </button>
        </div>
      </header>

      {trialId === DEMO_TRIAL_ID && <LockRecoveryStory key={trialId} />}

      {message && (
        <ErrorPanel title={t("Operation failed", "操作失败")} message={message} onRetry={() => void refresh()} />
      )}

      {phase === "loading" && <Spinner label={t("Loading operations", "加载运营数据")} />}

      {phase === "idle" && (
        <EmptyState
          title={t("No operations data", "暂无运营数据")}
          action={
            trialId !== DEMO_TRIAL_ID ? (
              <Link className="btn-secondary" to={`/command/${DEMO_TRIAL_ID}`}>
                {t("Open sample study", "打开示例研究")}
              </Link>
            ) : undefined
          }
        >
          {trialId !== DEMO_TRIAL_ID && t("Save a study design to continue.", "请先保存研究设计。")}
        </EmptyState>
      )}

      {phase === "error" && !snapshot && !message && <ErrorPanel title={t("Couldn't load the command center", "无法加载指挥中心")} onRetry={() => void refresh()} />}

      {snapshot && (
        <>
          <HealthBoard health={snapshot.health} onOpenProvenance={(item, label) => setProvenance({ item, title: label })} />
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,0.8fr)]">
            <Drilldown health={snapshot.health} />
            <AlertsPanel trialId={trialId} alerts={snapshot.alerts} owner={me.user} onChanged={load} />
          </div>
          <InterventionsPanel trialId={trialId} interventions={snapshot.interventions} effects={snapshot.effects} onChanged={load} />
          {(snapshot.health.plan_notes ?? []).length > 0 && (
            <details className="text-sm text-ink-600">
              <summary className="cursor-pointer font-semibold">{t("Plan notes", "方案说明")}</summary>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                {snapshot.health.plan_notes?.map((note) => (
                  <li key={note}>{displayText(note)}</li>
                ))}
              </ul>
            </details>
          )}
          <EventTicker events={snapshot.events} />
        </>
      )}

      <ProvenanceDrawer item={provenance?.item ?? null} title={provenance?.title ?? ""} onClose={() => setProvenance(null)} />
    </div>
  );
}

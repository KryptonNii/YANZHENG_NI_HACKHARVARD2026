import { translate } from "@/app/i18n";
import type { Intervention } from "@/app/contracts";
import evidence from "../../../../data/fixtures/ops/lock_recovery_evidence.json";
import story from "../../../../data/fixtures/ops/lock_recovery_story.json";
import type { EffectDetail } from "./api";

// The answer key stays in tests. These are recorded estimator outputs, not verdicts
// inferred from action names or from the direction of a before/after change.
export interface ReplayEffect extends EffectDetail {
  ci95: number[] | null;
  pre_window: { start: string; end: string; weeks: number };
  post_window: { start: string; end: string; weeks: number };
}

export interface ReplayCase {
  truth_id: string;
  intervention: Intervention;
  early: ReplayEffect;
  follow_up: ReplayEffect;
}

export const lockStory = story;
export const lockEvidence = evidence as Omit<typeof evidence, "cases"> & { cases: ReplayCase[] };

export interface ReplayState {
  stage: "risk" | "actions" | "results";
  started: string[];
  observed: string[];
}

export const initialReplay: ReplayState = { stage: "risk", started: [], observed: [] };
export type ReplayAction = { type: "review" | "observe" | "reset" } | { type: "start"; id: string };

export function replayReducer(state: ReplayState, action: ReplayAction): ReplayState {
  switch (action.type) {
    case "reset": return initialReplay;
    case "review": return state.stage === "risk" ? { ...state, stage: "actions" } : state;
    case "start":
      if (state.stage === "risk" || state.started.includes(action.id) || !story.actions.some((a) => a.id === action.id)) return state;
      return { ...state, started: [...state.started, action.id] };
    case "observe":
      if (!state.started.length) return state;
      return { ...state, stage: "results", observed: [...state.started] };
  }
}

export function replayEffect(state: ReplayState, item: ReplayCase): ReplayEffect | null {
  if (!state.started.includes(item.truth_id)) return null;
  return state.observed.includes(item.truth_id) ? item.follow_up : item.early;
}

export function replayForecast(state: ReplayState) {
  const recovery = lockEvidence.cases.find((item) => item.truth_id === story.recovery_intervention_id);
  const supported = recovery && state.observed.includes(recovery.truth_id)
    && replayEffect(state, recovery)?.estimate.verdict === "likely_worked";
  return supported ? story.recovered : story.slipped;
}

export function daysBetween(start: string, end: string) {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / 86_400_000);
}

export function lockDate(date: string) {
  return new Intl.DateTimeFormat(translate("en-GB", "zh-CN"), { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })
    .format(new Date(`${date}T00:00:00Z`));
}

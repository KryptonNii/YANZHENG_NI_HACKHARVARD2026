import { useEffect, useState } from "react";
import type { Levers } from "@/app/contracts";
import { api, isAbort } from "@/app/api/client";
import { DEFAULT_LEVERS } from "@/app/api/normalize";
import type { ScenarioResultX } from "@/app/api/types";

export const RECOMPUTE_DEBOUNCE_MS = 150;

export function leversEqual(a: Levers, b: Levers): boolean {
  return JSON.stringify(normalizeForCompare(a)) === JSON.stringify(normalizeForCompare(b));
}

function normalizeForCompare(l: Levers) {
  const sorted = <T,>(xs: T[]) => [...xs].sort();
  return {
    ...l,
    home_visit_numbers: sorted(l.home_visit_numbers),
    remote_visit_numbers: sorted(l.remote_visit_numbers),
    removed_procedures: sorted(l.removed_procedures),
    excluded_site_ids: sorted(l.excluded_site_ids),
  };
}

export interface ComputeState {
  baseline: ScenarioResultX | null;
  current: ScenarioResultX | null;
  /** a recompute is in flight; the previous result stays on screen meanwhile */
  computing: boolean;
  baselineError: string | null;
  currentError: string | null;
  retry: () => void;
}

/**
 * Baseline (default levers) once per design; current levers recomputed 150 ms after the last
 * change. In-flight requests are aborted when superseded, so sliders never wait on the network.
 */
export function useScenarioCompute(designId: string | undefined, levers: Levers, enabled = true, designVersion: number | null = null): ComputeState {
  type Result = { designKey: string; leverKey: string; value: ScenarioResultX };
  type Failure = { key: string; message: string };
  const [baselineState, setBaseline] = useState<Result | null>(null);
  const [currentState, setCurrent] = useState<Result | null>(null);
  const [baselineFailure, setBaselineError] = useState<Failure | null>(null);
  const [currentFailure, setCurrentError] = useState<Failure | null>(null);
  const [attempt, setAttempt] = useState(0);
  const designKey = JSON.stringify([designId, designVersion, attempt]);
  const key = JSON.stringify(normalizeForCompare(levers));
  const requestKey = JSON.stringify([designKey, key]);
  const active = enabled && !!designId && designVersion !== null;
  const baseline = active && baselineState?.designKey === designKey ? baselineState.value : null;
  const atBaseline = leversEqual(levers, DEFAULT_LEVERS);
  const current = atBaseline && baseline ? baseline : active && currentState?.designKey === designKey ? currentState.value : null;
  const baselineError = baselineFailure?.key === designKey ? baselineFailure.message : null;
  const currentError = currentFailure?.key === requestKey ? currentFailure.message : null;
  const ready = (atBaseline && !!baseline) || (currentState?.designKey === designKey && currentState.leverKey === key);
  const computing = active && !ready && !currentError;

  useEffect(() => {
    if (!designId || !active) return;
    const ctrl = new AbortController();
    setBaseline(null);
    setBaselineError(null);
    api
      .compute(designId, DEFAULT_LEVERS, { signal: ctrl.signal, silent: true, designVersion })
      .then((value) => {
        if (!ctrl.signal.aborted) setBaseline({ designKey, leverKey: JSON.stringify(normalizeForCompare(DEFAULT_LEVERS)), value });
      })
      .catch((err) => {
        if (!ctrl.signal.aborted && !isAbort(err)) setBaselineError({ key: designKey, message: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, [designId, designVersion, designKey, active]);

  useEffect(() => {
    if (!designId || !active || (atBaseline && baseline)) return;
    const ctrl = new AbortController();
    setCurrentError(null);
    const timer = window.setTimeout(() => {
      api
        .compute(designId, levers, { signal: ctrl.signal, designVersion })
        .then((r) => {
          if (ctrl.signal.aborted) return;
          setCurrent({ designKey, leverKey: key, value: r });
          setCurrentError(null);
        })
        .catch((err) => {
          if (ctrl.signal.aborted || isAbort(err)) return;
          setCurrentError({ key: requestKey, message: err instanceof Error ? err.message : String(err) });
        });
    }, RECOMPUTE_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      ctrl.abort();
    };
    // `key` captures every lever value; `levers` identity changes on each render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [designId, designVersion, designKey, key, requestKey, baseline, active, atBaseline]);

  return { baseline, current, computing, baselineError, currentError, retry: () => setAttempt((n) => n + 1) };
}

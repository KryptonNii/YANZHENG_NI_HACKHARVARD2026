import { useEffect, useRef, useState } from "react";
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
}

/**
 * Baseline (default levers) once per design; current levers recomputed 150 ms after the last
 * change. In-flight requests are aborted when superseded, so sliders never wait on the network.
 */
export function useScenarioCompute(designId: string | undefined, levers: Levers, enabled = true): ComputeState {
  const [baseline, setBaseline] = useState<ScenarioResultX | null>(null);
  const [current, setCurrent] = useState<ScenarioResultX | null>(null);
  const [computing, setComputing] = useState(false);
  const [baselineError, setBaselineError] = useState<string | null>(null);
  const [currentError, setCurrentError] = useState<string | null>(null);
  const inflight = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!designId || !enabled) return;
    const ctrl = new AbortController();
    setBaseline(null);
    setBaselineError(null);
    api
      .compute(designId, DEFAULT_LEVERS, { signal: ctrl.signal, silent: true })
      .then(setBaseline)
      .catch((err) => {
        if (!isAbort(err)) setBaselineError(err instanceof Error ? err.message : String(err));
      });
    return () => ctrl.abort();
  }, [designId, enabled]);

  const key = JSON.stringify(normalizeForCompare(levers));
  useEffect(() => {
    if (!designId || !enabled) return;
    if (leversEqual(levers, DEFAULT_LEVERS) && baseline) {
      inflight.current?.abort();
      setCurrent(baseline);
      setComputing(false);
      setCurrentError(null);
      return;
    }
    setComputing(true);
    const timer = window.setTimeout(() => {
      inflight.current?.abort();
      const ctrl = new AbortController();
      inflight.current = ctrl;
      api
        .compute(designId, levers, { signal: ctrl.signal })
        .then((r) => {
          if (ctrl.signal.aborted) return;
          setCurrent(r);
          setCurrentError(null);
          setComputing(false);
        })
        .catch((err) => {
          if (isAbort(err)) return;
          setCurrentError(err instanceof Error ? err.message : String(err));
          setComputing(false);
        });
    }, RECOMPUTE_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
    // `key` captures every lever value; `levers` identity changes on each render
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [designId, key, baseline, enabled]);

  useEffect(() => () => inflight.current?.abort(), []);

  return { baseline, current, computing, baselineError, currentError };
}

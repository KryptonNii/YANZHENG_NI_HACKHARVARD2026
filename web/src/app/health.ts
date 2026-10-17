import { useEffect, useState } from "react";
import { api } from "./api/client";

export type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; offline: boolean; version?: string }
  | { kind: "unreachable" };

/** Polls GET /api/health (30 s) for the header's offline / unreachable badges. */
export function useHealth(intervalMs = 30_000): HealthState {
  const [state, setState] = useState<HealthState>({ kind: "loading" });
  useEffect(() => {
    let cancelled = false;
    const ctrl = new AbortController();
    const check = async () => {
      try {
        const h = await api.health(ctrl.signal);
        if (!cancelled) setState({ kind: "ok", offline: h.offline === true, version: h.version });
      } catch {
        if (!cancelled) setState({ kind: "unreachable" });
      }
    };
    void check();
    const t = window.setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      ctrl.abort();
      window.clearInterval(t);
    };
  }, [intervalMs]);
  return state;
}

export const MOCK_API = import.meta.env.VITE_MOCK_API === "1";

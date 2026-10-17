import { useEffect, useState } from "react";
import type { Parameter } from "@/app/contracts";
import { api } from "@/app/api/client";

let cache: Promise<Map<string, Parameter>> | null = null;

/** Loads GET /api/params once per page session (the library is immutable per version). */
export function loadParamLibrary(): Promise<Map<string, Parameter>> {
  if (!cache) {
    cache = api
      .params({ silent: true })
      .then((ps) => new Map(ps.map((p) => [p.id, p])))
      .catch((err) => {
        cache = null; // allow a retry on next open
        throw err;
      });
  }
  return cache;
}

/** Test hook: forget the cached library. */
export function resetParamLibrary(): void {
  cache = null;
}

export type ParamLibraryState =
  | { status: "loading" }
  | { status: "ready"; byId: Map<string, Parameter> }
  | { status: "error"; message: string };

export function useParamLibrary(): ParamLibraryState {
  const [state, setState] = useState<ParamLibraryState>({ status: "loading" });
  useEffect(() => {
    let alive = true;
    loadParamLibrary()
      .then((byId) => alive && setState({ status: "ready", byId }))
      .catch((err) => alive && setState({ status: "error", message: err instanceof Error ? err.message : String(err) }));
    return () => {
      alive = false;
    };
  }, []);
  return state;
}

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { onApiError } from "./api/client";
import { useTranslation } from "./i18n";
import { localizeCopy } from "./localize";

export type ToastKind = "error" | "success" | "info";

interface Toast {
  id: number;
  kind: ToastKind;
  title: string;
  message?: string;
}

interface ToastApi {
  push: (kind: ToastKind, title: string, message?: string) => void;
}

const ToastContext = createContext<ToastApi>({ push: () => undefined });

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

const KIND_LABEL: Record<ToastKind, string> = { error: "Error", success: "Done", info: "Note" };
const KIND_STYLE: Record<ToastKind, string> = {
  error: "border-worse-300 bg-white",
  success: "border-better-300 bg-white",
  info: "border-ink-300 bg-white",
};
const KIND_BAR: Record<ToastKind, string> = {
  error: "bg-worse-600",
  success: "bg-better-600",
  info: "bg-accent-600",
};

/** Toasts for API errors (plain-English message from the API) and confirmations. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const tr = useTranslation();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Set<number>());

  useEffect(() => () => {
    timers.current.forEach((timer) => window.clearTimeout(timer));
    timers.current.clear();
  }, []);

  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const push = useCallback(
    (kind: ToastKind, title: string, message?: string) => {
      const id = nextId.current++;
      setToasts((t) => {
        // collapse identical messages (e.g. several requests failing because the API is down)
        if (t.some((x) => x.title === title && x.message === message)) return t;
        return [...t.slice(-3), { id, kind, title, message }];
      });
      const timer = window.setTimeout(() => {
        timers.current.delete(timer);
        dismiss(id);
      }, kind === "error" ? 8000 : 4000);
      timers.current.add(timer);
    },
    [dismiss],
  );

  useEffect(
    () =>
      onApiError((err) => {
        push("error", err.message, err.code && err.status ? `${err.code} · HTTP ${err.status}` : undefined);
      }),
    [push],
  );

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[24rem] max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.kind === "error" ? "alert" : "status"}
            className={`pointer-events-auto flex overflow-hidden rounded-lg border shadow-card animate-fade-in ${KIND_STYLE[t.kind]}`}
          >
            <span className={`w-1.5 shrink-0 ${KIND_BAR[t.kind]}`} aria-hidden />
            <div className="flex-1 px-3 py-2.5">
              <p className="text-sm font-semibold text-ink-900">
                <span className="sr-only">{tr(KIND_LABEL[t.kind], { error: "错误", success: "完成", info: "提示" }[t.kind])}: </span>
                {localizeCopy(t.title)}
              </p>
              {t.message && <p className="mt-0.5 text-xs text-ink-500">{t.message}</p>}
            </div>
            <button
              type="button"
              onClick={() => dismiss(t.id)}
              className="px-3 text-ink-400 hover:text-ink-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-600"
              aria-label={tr("Dismiss notification", "关闭通知")}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/**
 * Small shared UI kit (A8). A9's pages may import from "@/app/ui" for a consistent look.
 */
import { useEffect, useId, useRef, type ReactNode } from "react";
import { useTranslation } from "../i18n";
import { localizeCopy } from "../localize";

// ---------------------------------------------------------------- badges
type Tone = "neutral" | "accent" | "caution" | "better" | "worse" | "dark";

const TONES: Record<Tone, string> = {
  neutral: "border-ink-300 bg-ink-100 text-ink-700",
  accent: "border-accent-300 bg-accent-50 text-accent-800",
  caution: "border-caution-300 bg-caution-50 text-caution-900",
  better: "border-better-300 bg-better-50 text-better-800",
  worse: "border-worse-300 bg-worse-50 text-worse-800",
  dark: "border-ink-800 bg-ink-800 text-white",
};

export function Badge({ tone = "neutral", children, title, className = "" }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span className={`chip ${TONES[tone]} ${className}`} title={title}>
      {children}
    </span>
  );
}

/** §2 rule 4: simulated data is visibly labelled. */
export function SimulatedBadge() {
  const t = useTranslation();
  return (
    <Badge tone="caution" title={t("Simulated operations data", "模拟运营数据")}>
      <Dot className="bg-caution-500" /> {t("Simulated", "模拟")}
    </Badge>
  );
}

export function AssumptionTag({ title }: { title?: string }) {
  const t = useTranslation();
  return (
    <Badge tone="caution" title={title ?? t("Planning input awaiting confirmation", "规划输入，待审核")}>
      {t("To confirm", "待确认")}
    </Badge>
  );
}

export function DraftStamp({ children }: { children?: ReactNode }) {
  const t = useTranslation();
  return (
    <span className="inline-flex items-center rounded border-2 border-dashed border-caution-500 px-2 py-0.5 text-xs font-bold uppercase tracking-wide text-caution-800">
      {children === undefined ? t("Pending review", "待审核") : children}
    </span>
  );
}

export function Dot({ className = "" }: { className?: string }) {
  return <span className={`inline-block h-2 w-2 rounded-full ${className}`} aria-hidden />;
}

// ---------------------------------------------------------------- loading
export function Skeleton({ className = "" }: { className?: string }) {
  return <span className={`block animate-pulse rounded bg-ink-200 ${className}`} aria-hidden />;
}

export function Spinner({ label, className = "" }: { label?: string; className?: string }) {
  const t = useTranslation();
  return (
    <span role="status" className={`inline-flex items-center gap-2 text-sm text-ink-500 ${className}`}>
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-300 border-t-accent-700" aria-hidden />
      <span>{label ?? t("Loading", "正在加载")}</span>
    </span>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-ink-300 bg-white/60 px-6 py-8 text-center">
      <p className="font-semibold text-ink-800">{title}</p>
      {children && <div className="mx-auto mt-1 max-w-prose text-sm text-ink-500">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorPanel({ title, message, onRetry }: { title: string; message?: string; onRetry?: () => void }) {
  const t = useTranslation();
  return (
    <div role="alert" className="rounded-xl border border-worse-200 bg-worse-50 px-5 py-4">
      <p className="font-semibold text-worse-900">{title}</p>
      {message && <p className="mt-1 text-sm text-worse-800">{localizeCopy(message)}</p>}
      {onRetry && (
        <button type="button" className="btn-secondary mt-3" onClick={onRetry}>
          {t("Try again", "重试")}
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- segmented control
export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  title?: string;
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = "md",
}: {
  value: T;
  options: SegmentOption<T>[];
  onChange: (v: T) => void;
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex shrink-0 rounded-lg border border-ink-300 bg-ink-100 p-0.5">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={`rounded-md font-semibold transition-colors ${size === "sm" ? "px-2 py-0.5 text-xs" : "px-3 py-1.5 text-sm"} ${
              active ? "bg-white text-ink-900 shadow-sm ring-1 ring-ink-300" : "text-ink-600 hover:text-ink-900"
            }`}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------- overlays
function useEscape(onClose: () => void, active: boolean) {
  useEffect(() => {
    if (!active) return;
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose, active]);
}

/** Right-hand drawer (provenance). Focus moves into it; Escape closes it. */
export function Drawer({ open, title, subtitle, onClose, children, width = "w-[36rem]" }: {
  open: boolean;
  title: ReactNode;
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  width?: string;
}) {
  const t = useTranslation();
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEscape(onClose, open);
  useEffect(() => {
    if (open) panel.current?.focus();
  }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-ink-900/25 animate-fade-in" onClick={onClose} aria-hidden />
      <aside
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        tabIndex={-1}
        className={`absolute right-0 top-0 flex h-full max-w-full flex-col bg-white shadow-drawer outline-none animate-slide-in ${width}`}
      >
        <header className="flex items-start justify-between gap-4 border-b border-ink-200 px-6 py-4">
          <div>
            <h2 id={`${id}-title`} className="text-lg font-semibold text-ink-900">
              {title}
            </h2>
            {subtitle && <div className="mt-0.5 text-sm text-ink-500">{subtitle}</div>}
          </div>
          <button type="button" onClick={onClose} className="btn-ghost -mr-2 px-2" aria-label={t("Close panel", "关闭面板")}>
            <span aria-hidden className="text-xl leading-none">×</span>
          </button>
        </header>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
      </aside>
    </div>
  );
}

export function Modal({ open, title, onClose, children, footer }: {
  open: boolean;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const id = useId();
  const panel = useRef<HTMLDivElement>(null);
  useEscape(onClose, open);
  useEffect(() => {
    if (open) {
      const first = panel.current?.querySelector<HTMLElement>("input, select, textarea, button");
      (first ?? panel.current)?.focus();
    }
  }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink-900/30 animate-fade-in" onClick={onClose} aria-hidden />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        tabIndex={-1}
        className="relative w-full max-w-lg rounded-xl bg-white shadow-drawer outline-none animate-fade-in"
      >
        <header className="border-b border-ink-200 px-5 py-3.5">
          <h2 id={`${id}-title`} className="text-base font-semibold">
            {title}
          </h2>
        </header>
        <div className="px-5 py-4">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-ink-200 px-5 py-3">{footer}</footer>}
      </div>
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-3 flex items-center justify-between gap-3">
      <h2 className="card-title">{children}</h2>
      {aside}
    </div>
  );
}

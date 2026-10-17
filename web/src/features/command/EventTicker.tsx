import type { OpsEvent } from "@/app/contracts";
import { formatUtc } from "@/app/format";
import { SOURCE_LABEL } from "./present";

export function EventTicker({ events }: { events: OpsEvent[] }) {
  return (
    <details className="card" data-testid="event-ticker">
      <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-ink-800">Live events ({events.length})</summary>
      <ol className="max-h-64 space-y-1 overflow-auto border-t border-ink-100 px-4 py-2">
        {events.length === 0 && <li className="py-2 text-sm text-ink-500">No events yet.</li>}
        {events.map((event) => (
          <li key={event.id} className="flex items-baseline gap-2 py-1 text-sm">
            <span className="inline-flex w-16 shrink-0 justify-center rounded bg-ink-100 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink-600" title={event.source_system}>
              {SOURCE_LABEL[event.source_system] ?? event.source_system}
            </span>
            <span className="font-medium text-ink-800">{event.type.replaceAll("_", " ")}</span>
            <span className="text-xs text-ink-500">{event.site_id ?? "study"}</span>
            <span className="ml-auto shrink-0 text-xs tabular text-ink-400">{formatUtc(event.occurred_at)}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}

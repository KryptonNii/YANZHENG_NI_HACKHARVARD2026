import type { ImportNote } from "@/app/api/types";
import { humanize } from "@/app/format";
import { EmptyState } from "@/app/ui";

const FIELD_HELP: Record<string, { why: string; fix: "protocol" | "edit" | null }> = {
  visits: { why: "Registries don't publish the visit schedule. A phase-based template (marked as an assumption) is used until you apply a protocol extraction.", fix: "protocol" },
  enrollment_target: { why: "No enrollment figure in the source.", fix: "edit" },
  duration_months: { why: "Start or completion dates missing; duration is estimated.", fix: "edit" },
  drug_type: { why: "Intervention type unclear in the registry.", fix: "edit" },
  phase: { why: "Phase not stated in the source.", fix: "edit" },
};

/** "Missing & assumed": what the importer could not get and what fills the gap (§2: unknown ≠ zero). */
export function MissingAssumed({
  missing,
  notes,
  onEdit,
  onProtocol,
}: {
  missing: string[];
  notes: ImportNote[];
  onEdit: () => void;
  onProtocol: () => void;
}) {
  if (missing.length === 0 && notes.length === 0) {
    return <EmptyState title="Nothing missing">Every field came from the source.</EmptyState>;
  }
  return (
    <ul className="divide-y divide-ink-100" data-testid="missing-assumed">
      {missing.map((f) => {
        const help = FIELD_HELP[f];
        const lat = f.startsWith("site") && f.includes("coord");
        return (
          <li key={f} className="flex flex-wrap items-start justify-between gap-3 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="text-sm font-semibold text-ink-900">
                <span className="mr-1.5 inline-block rounded bg-caution-100 px-1.5 text-[11px] font-bold uppercase tracking-wide text-caution-900">
                  assumed
                </span>
                {humanize(f)}
              </p>
              <p className="mt-0.5 text-sm text-ink-600">
                {help?.why ?? (lat ? "Coordinates resolved from an offline geocoder." : "Not available from the source; filled with a labelled assumption.")}
              </p>
            </div>
            {help?.fix === "protocol" && (
              <button type="button" className="btn-secondary py-1.5 text-xs" onClick={onProtocol}>
                Upload protocol
              </button>
            )}
            {help?.fix === "edit" && (
              <button type="button" className="btn-secondary py-1.5 text-xs" onClick={onEdit}>
                Edit value
              </button>
            )}
          </li>
        );
      })}
      {notes.map((note) => {
        const counted = note.assumption && (!note.field || !missing.includes(note.field));
        return (
          <li key={`${note.field ?? ""}:${note.text}`} className="py-2.5 text-sm text-ink-700">
            <span className={`mr-1.5 inline-block rounded px-1.5 text-[11px] font-bold uppercase tracking-wide ${counted ? "bg-caution-100 text-caution-900" : "bg-ink-100 text-ink-700"}`}>
              {counted ? "assumed" : "note"}
            </span>
            {note.text}
          </li>
        );
      })}
    </ul>
  );
}

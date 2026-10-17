/** A4 import notes. String notes stay facts unless A4 tags them, or they are the visit-template sentence. */
import type { ImportNote } from "@/app/api/types";

export type { ImportNote };

const VISIT_TEMPLATE = /^Visit schedule is not in the registry/i;

function asNote(value: unknown, field: string | null): ImportNote | null {
  if (typeof value === "string") {
    const text = value.trim();
    if (!text) return null;
    const aboutVisits = VISIT_TEMPLATE.test(text);
    return { text, field: field ?? (aboutVisits ? "visits" : null), assumption: aboutVisits };
  }
  if (!value || typeof value !== "object") return null;
  const row = value as { text?: unknown; note?: unknown; field?: unknown; assumption?: unknown; clears_when_present?: unknown };
  const text = typeof row.text === "string" ? row.text : typeof row.note === "string" ? row.note : null;
  if (!text?.trim()) return null;
  const taggedField = typeof row.field === "string" && row.field.trim() ? row.field.trim() : field;
  const aboutVisits = VISIT_TEMPLATE.test(text.trim());
  return {
    text: text.trim(),
    field: taggedField ?? (aboutVisits ? "visits" : null),
    assumption: row.assumption === true || (row.assumption !== false && aboutVisits),
    clears_when_present: row.clears_when_present === true,
  };
}

function pushUnique(out: ImportNote[], note: ImportNote | null) {
  if (!note) return;
  const existing = out.findIndex((n) => n.text === note.text);
  if (existing >= 0) { if (note.field) out[existing] = note; return; }
  out.push(note);
}

/** Accept A4's `notes` (strings or `{text, field, assumption}`) and `notes_by_field`. */
export function parseImportNotes(notes: unknown, notesByField: unknown): ImportNote[] {
  const out: ImportNote[] = [];
  if (Array.isArray(notes)) {
    for (const item of notes) pushUnique(out, asNote(item, null));
  }
  if (notesByField && typeof notesByField === "object" && !Array.isArray(notesByField)) {
    for (const [field, value] of Object.entries(notesByField)) {
      const items = Array.isArray(value) ? value : [value];
      for (const item of items) pushUnique(out, asNote(item, field));
    }
  }
  return out;
}

/** Drop notes whose field was filled in (the visit-template sentence once `visits` leaves missing_fields). */
export function visibleNotes(missing: string[], notes: ImportNote[]): ImportNote[] {
  return notes.filter((note) => {
    if (note.clears_when_present && note.field && !missing.includes(note.field)) return false;
    if (note.field && !missing.includes(note.field) && (note.field === "visits" || note.assumption)) {
      if (note.field === "visits" || VISIT_TEMPLATE.test(note.text)) return false;
    }
    if (!missing.includes("visits") && (note.field === "visits" || VISIT_TEMPLATE.test(note.text))) return false;
    return true;
  });
}

/**
 * Badge = missing fields, plus assumption notes whose field is not already in that list.
 * Plain notes (enrollment is ACTUAL, dates, drug-type basis) are shown and not counted.
 */
export function assumptionCount(missing: string[], notes: ImportNote[]): number {
  const extra = visibleNotes(missing, notes).filter((note) => note.assumption && (!note.field || !missing.includes(note.field)));
  return missing.length + extra.length;
}

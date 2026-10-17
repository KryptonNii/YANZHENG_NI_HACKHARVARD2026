# A4 — contract change proposals (for A1)

## 1. Allow deterministic UUIDv5 ids for imported records (status: proposal; A4 already does this)
- **Now (§3):** "IDs: UUID4 strings."
- **A4 does:** `TrialDesign.id = uuid5(NS, "ctgov:<NCT>")` and `Site.id = uuid5(NS, "ctgov:<NCT>:site:<key>#<n>")`
  (`api/trialpilot_api/importers/ctgov.py`, namespace `6f1c3c3e-8a43-4d0e-9b55-1f2a5e0c7a11`). Extraction ids are uuid5 in a
  second namespace, `0b8f5d0e-5a3c-4c55-9f7e-2c1d7a9e4b21` (`protocol_extract.py`): `"{pdf_sha256}:{method}:{model}"` for a
  live extract, and `"{pdf_sha256}:transcription:{model}"` for the BOREAS build-time cache. Not the sha256 alone.
- **Why:** re-importing the same study (online, offline, or after a refresh) gives the same design and site ids. Lever settings
  (`excluded_site_ids`), saved scenarios and audit entries keep pointing at the same objects, and golden fixtures stay stable.
- **Proposed wording:** "IDs are UUID strings: UUID4 for records created in the app, UUIDv5 (fixed namespace) for records
  derived from an external identifier such as an NCT id."
- **Impact:** none on validation; both pass `uuid.UUID(...)`. No consumer checks the version nibble (searched `api/`, `engine/`,
  `web/src`, `contracts/`, `validation/` on 2026-10-16; the only `version=4` is A6's id generator, which creates ids and
  doesn't check them).

## 2. Additive response fields (status: informational, no change needed)
`POST /api/import/ctgov/{nct_id}` and `POST /api/import/protocol` return the §9 keys plus extra keys (notes, field sources,
attribution, document info, `auto_applied: false`). Additional endpoints: `GET /api/import/ctgov`, `POST /api/import/protocol/apply`,
`POST /api/import/protocol/review`, `GET /api/import/protocol/review/stats`. Listed in `handoffs/A4.md`.

## 3. More additive fields for the import UI (status: informational, 2026-10-16; shared models unchanged)
No change to `TrialDesign`, `Visit`, `Procedure`, or `Levers`. The strings already on `notes` stay, in the same order.

- `POST /api/import/ctgov/{nct_id}` also returns `field_notes`, `notes_by_field`, and `procedure_group_labels`.
  Each note is `{field, kind, assumption, text, clears_when_present}` with `kind` one of `fact`,
  `missing`, `assumption`. `assumption` is true only for `kind: "assumption"`.
  A note that is not about one design field has `field: null` and is grouped under `notes_by_field._unscoped`.
- `GET /api/import/procedure-codes` returns `{version, note, codes: [{code, group_label, ships_sample, in_param_library}]}`.
  The same map is `procedure_group_labels` on the ctgov and protocol responses. `group_label` is the category,
  not one assessment that happens to use the code. `Procedure.label` on a visit row is unchanged.
- `POST /api/import/protocol` also returns `procedure_group_labels`, `llm_accuracy: "unmeasured"`, and
  `llm_accuracy_note: "Real LLM accuracy was not measured."` Candidates, the `DRAFT` notice, quotes, and
  `auto_applied: false` are unchanged.
- `POST /api/import/protocol/apply` also returns `cleared_fields` (`["visits"]` when that entry was in
  `missing_fields`).
- `POST /api/import/protocol/review` accepts optional `bulk_accepted` (integer, `<= accepted`). Omit it, or
  send null, when the caller cannot tell; that is not stored as zero. Stats add `bulk_accepted`,
  `individually_accepted`, `accepted_unchanged_share_status` (`no_reviews` | `unknown` | `no_individual_review` |
  `review_log_only`), `accuracy_unknown_reviews`, `llm_accuracy`, and `llm_accuracy_note`.
  `accepted_unchanged_share` is null unless every log line recorded `bulk_accepted` and at least one row was
  judged one by one. Bulk-accepted rows are not in that share. Old lines are not rewritten.

Exact JSON is in `handoffs/A4.md`, section "Fields for A8".

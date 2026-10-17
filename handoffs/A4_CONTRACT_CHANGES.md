# A4 — contract change proposals (for A1)

## 1. Allow deterministic UUIDv5 ids for imported records (status: proposal; A4 already does this)
- **Now (§3):** "IDs: UUID4 strings."
- **A4 does:** `TrialDesign.id = uuid5(NS, "ctgov:<NCT>")` and `Site.id = uuid5(NS, "ctgov:<NCT>:site:<key>#<n>")`
  (`api/trialpilot_api/importers/ctgov.py`, namespace `6f1c3c3e-8a43-4d0e-9b55-1f2a5e0c7a11`). Extraction ids are uuid5 of the
  PDF sha256.
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

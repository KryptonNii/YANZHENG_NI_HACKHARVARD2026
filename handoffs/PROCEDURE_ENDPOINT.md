# Procedure endpoint annotations

Implemented on 2026-10-17. No commit was created.

## Fields and compatibility

`Procedure` has three defaulted fields:

| Field | Values | Default |
| --- | --- | --- |
| `endpoint_role` | `supports_primary`, `supports_secondary`, `not_linked`, `unknown` | `unknown` |
| `endpoint_note` | string | empty string |
| `link_basis` | `outcome_title`, `human`, `unmatched` | `unmatched` |

Existing designs and extraction caches without these fields still validate. Pydantic
supplies defaults when reading them; no stored records or fixture files were migrated.
The two UI components also display missing legacy fields as Unknown / Unmatched.

## Matching and human decisions

`api/trialpilot_api/importers/endpoints.py` matches the **entire procedure label** as
a contiguous token phrase against `protocolSection.outcomesModule` entries' `measure`
(registry outcome title), optionally followed by `timeFrame`. Normalization is Unicode
NFKC, case folding, punctuation separation and whitespace folding. Word boundaries
prevent partial-word matches. A match cannot come solely from the time frame.

Only `primaryOutcomes` and `secondaryOutcomes` participate; primary takes precedence
when both match. The note records the matched title and its time frame. There are no
synonyms, abbreviation expansion, procedure-code/category matching, description-text
matching, LLM decisions, clinical inference or visit-time interpretation. For example,
`SGRQ` can match a title containing `SGRQ`; `Spirometry` is not inferred from `FEV1`.
The time frame is textual evidence, not proof that every collection visit is an endpoint
measurement visit. Unmatched procedures remain `unknown` / `unmatched`; automatic
matching never produces `not_linked`.

Annotations are applied to registry-imported visits, returned protocol candidates
(including copies of old cached extractions), and confirmed visits returned by
`/protocol/apply`. Protocol imports use an available registry cache, identified by the
NCT ID or the stored design. Uploads without an available registry record remain unknown.
Extraction cache files are not rewritten.

In **protocol review**, Edit visit exposes a role selector and note field for each
procedure. Changing either sets `link_basis=human`; changing an automatic role clears
its previous automatic note. Done counts a metadata change as an edited visit. Merely
accepting a candidate does not mark its annotation as human. Applying uses the existing
design-save/version/conflict handling.

Reimport preserves saved human role, note and basis for the same visit number, procedure
code and normalized label, even if the visit week was corrected. A newly submitted human
choice wins over the previous human choice. Different labels sharing a code and different
visit numbers are not conflated. Renamed procedures or renumbered visits cannot be reliably
identified as the same occurrence with this contract and require review again; unrelated
procedures do not inherit a judgment merely because they share a code.

## Removal and calculations

The existing **Remove procedures** control retains its checkbox semantics (checked means
removed), default selection, code-wide removal, and reset behavior. Each row displays the
individual labels' roles, basis, notes and visit numbers. Editing is in protocol review;
the lever row displays the saved annotations. When removed, the affected annotations show:

- Primary: `This procedure is tied to a primary outcome.`
- Not linked: `No primary or secondary outcome in the registry record matches this procedure.`

Warnings are informational and do not block removal. Unknown is never described as optional
or non-core. No cost, staff-time, carbon or delta formulas were added or changed; the existing
scenario compute path remains responsible for every metric.

## Old data and scope limits

- Existing saved designs opened without reimport/review are not backfilled with registry
  matches. Their new fields default to unknown, empty note and unmatched.
- Old protocol caches acquire annotations only in the import response, with available
  registry data. Missing registry data, synonyms and unmatched labels remain unknown.
- The only changed generated file is `web/src/contracts.ts`. To avoid writing the other
  generated files in this checkout, `make gen` and `make gen-check` ran in a temporary mirror
  containing the current contract sources and unchanged generator/Makefile. Only the generated
  TypeScript was copied back; it matches the local generator byte for byte.
- The checkout's full `make gen-check` **fails** on `contracts/schema/Procedure.json`,
  `Visit.json` and `TrialDesign.json`. They are deliberately unchanged because the requested
  scope permits only the TypeScript generated file. The temporary mirror's full check passes.
- `pnpm --dir web typecheck` **fails** at `web/src/app/api/mock/data.ts:8`: its old typed
  `Procedure` factory lacks the three new fields. That file is outside the permitted scope.
  Runtime legacy handling is covered by component tests. No workaround weakened the
  generated contract or hid this compiler error.
- No edits were made to `main.py`, benchmark, `PeerMirror.tsx`, peer fixtures, command,
  validation, README or docs. Unrelated existing/concurrent workspace changes were left alone.

## Verification

- `uv run --project api pytest api/tests/importers api/tests/test_scenarios.py api/tests/test_app_basics.py`:
  **173 passed**.
- **15 temporary API/contract checks passed**: defaults and invalid enum values, full-label
  and time-frame matching, primary precedence, no description/code inference, independent
  labels and visits, corrected-week preservation, fresh human overrides, real stored-design
  registry reimport, cached protocol re-extraction and apply preservation (including lowercase
  NCT input). These checks used temporary databases and were not added outside the allowed
  source/test paths. Script retained in the local temporary generation mirror at
  `C:/Users/ol735/AppData/Local/Temp/trialpilot-endpoint-gen-f03680e12fec4fb7ac5c7e3b3c86887e/test_endpoint_links.py`.
- `corepack pnpm --dir web test src/features/scenario/scenario.test.tsx src/features/scenario/compute.test.tsx`:
  **25 passed**, including five new endpoint-role tests. The metric test checks the existing
  compute output; removing a questionnaire in the existing mock changes staff time while its
  cost/carbon values remain unchanged.
- `uv run --project contracts pytest contracts/tests/test_roundtrip.py contracts/tests/test_contract_v4.py`:
  **70 passed**.
- Ruff on the three changed importer files and `git diff --check` on the task files: passed.
- Generation and typecheck results, including the two scope-limited failures, are above.

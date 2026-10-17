# A4 review of A8 (web shell, import UI, scenario simulator)

Reviewer: A4 (importers) · 2026-10-16 ~22:45 ET · working tree on `dev` at `020a19e` (the files cited are committed).

How I tested:
- A8's vitest suite, run with `node web/node_modules/vitest/vitest.mjs run` (pnpm is broken, see #5) → **25 passed (4 files)**; `tsc --noEmit` clean.
- Vite on my port 5177 → A5's API on 8004 (`DEMO_OFFLINE=1`, temp DB). I walked §7 steps 1–2 in the browser:
  - import BOREAS → protocol extraction → accept → apply → simulator → demo levers → provenance → save;
  - plus the failure paths below.

## Findings (most important first)

### 1. BLOCKER: importing a trial never stores it, so the simulator says "not found" for anything A5 didn't seed
- **Where:** `web/src/features/scenario/ImportPage.tsx:177-198` (`runImport`: `importCtgov` → `showDesign`, no `saveDesign`), then `:389` (navigate to `/scenario/:id`, which does `GET /api/designs/:id`, `ScenarioPage.tsx:160`).
- **Input → output:** A5 started with `TP_SEED_FIXTURE_DESIGNS=0` (this is also what happens for any NCT outside A5's four seeded fixtures, online). Type NCT04456673 → Import (trial card fine) → **Open scenario simulator** → "This trial design was not found". Network log: `POST /api/import/ctgov/NCT04456673` 200, **no** `POST /api/designs`, then `GET /api/designs/3b11a429…` 404.
- **Why it matters:** §7 step 1 ("paste a real Phase 3 trial ID") works today only because A5 seeds A4's four fixtures at startup. A judge who pastes their own NCT (online) hits a dead end at the hero screen.
- **Fix:** after `importCtgov`, `GET /api/designs/:id`.
  - 404 → `saveDesign(res.design)` (A5 answers 200 with no new version when the content is identical).
  - Exists → show the stored latest version (it may already have the confirmed protocol schedule), plus a "re-import from registry" action that saves a new version deliberately.
  - Saving the template design blindly would regress a design whose protocol schedule was already applied.

### 2. MAJOR: the simulator doesn't pin the design version, so saved numbers can differ from the screen
- **Where:** `web/src/features/scenario/ScenarioPage.tsx:204` (`saveScenario({ design_id, name, levers })`) and `hooks/useScenarioCompute.ts:51` (`compute(designId, …)`). Neither sends `design_version`.
- **Input → output:** BOREAS v2 loaded (header "939 patients", 19 visits, cost card P50 **$178.7M** with the demo levers). Another user stores v3 (enrollment 100) via `POST /api/designs`. Save → the saved row shows **$49.4M**, `design_version 3`, right under the $178.7M card and the "939 patients" header. Any later lever change also computes on v3 while the header still shows v2's facts.
- **Why it matters:** what the author reviews, saves, submits and gets approved can be a different design version from the one on screen, with no indication.
- **Fix:** keep the loaded version (A5's `X-Design-Version` header or the design summary) and send `design_version` on compute and save. Show "design vN" in the header and in each saved row. A5's side of this is in `reviews/A4_on_A5.md` #2.

### 3. MAJOR: "Remove procedures" removes several assessments behind one label, with wrong counts
- **Where:** `web/src/features/scenario/components/LeversPanel.tsx:82-92`. It groups by `code`, shows the first label seen, and counts occurrences (not visits).
- **Input → output:** BOREAS with the applied protocol schedule (19 visits) shows:
  - "Review electronic diary — **40 visits**": it is at 17 visits. Unticking it removes code `questionnaire`: Review electronic diary 17 + SGRQ 7 + EQ-5D-5L 1 + Health care utilization 15.
  - "PARC — 23 visits" removes every `biomarker_sample` (PARC, Eotaxin-3, Total IgE, RNA, DNA, archival serum).
  - "Spirometry (pre-BD) — 27" also removes post-BD.
- **Why it matters:** the demo's "drop one low-value procedure" silently drops several assessments, and the trade-off is credited to the wrong procedure.
- **Fix:** one row per code, listing all its labels, e.g. "Questionnaires (Review electronic diary, SGRQ, EQ-5D-5L, Health care utilization): 40 at 19 visits". Count distinct visits. A4 will also send the vocabulary's per-code label so you don't have to invent one (see A4 HANDOFF).

### 4. MAJOR: after "Apply to design", the page still says the template schedule is in use
- **Where:** `web/src/features/scenario/ImportPage.tsx:250` updates `missing_fields` but keeps `info.warnings` (A4's import notes, `:268`).
- **Input → output:** BOREAS → Use the registry protocol → Accept all → Apply. The page says "Applied 19 visits", "19 visits and 275 sites ready", and under Missing & assumed it still shows "Visit schedule is NOT in the registry: filled with assumed template 'phase3_default' (11 visits …)".
- **Why it matters:** the page contradicts itself at the demo's key step, and judges read that panel.
- **Fix:** once `visits` leaves `missing_fields`, drop the visit-schedule note. A4 will tag each note with the field it explains (`notes_by_field` / `note.field`), so you can filter generically. Until then, filter notes that start with "Visit schedule is NOT in the registry".

### 5. MAJOR: `web/pnpm-workspace.yaml` breaks every pnpm command in `web/`
- **Where:** `web/pnpm-workspace.yaml:1` (untracked, created 22:28 ET; content `allowBuilds: { esbuild: true }`, no `packages:`).
- **Input → output:** `pnpm --dir web test` → `ERROR  packages field missing or empty`; same for `pnpm --dir web exec …`. CI (`pnpm --dir web typecheck` / `test`) and `make dev` run these commands.
- **Why it matters:** if it gets committed, CI and the judges' setup break. Right now it already breaks other agents' local runs.
- **Fix:** delete it and put `"pnpm": { "onlyBuiltDependencies": ["esbuild"] }` in `package.json`, or add `packages: ["."]`.

### 6. MINOR: the "Missing & assumed" badge counts plain notes as assumptions
- **Where:** `web/src/features/scenario/ImportPage.tsx:396` (`missing_fields.length + warnings.length`).
- **Input → output:** BOREAS shows **9**: 2 assumed fields + 7 notes, including facts such as "Enrollment 939 is the actual number enrolled".
- **Fix:** count `missing_fields` (plus notes A4 tags as assumptions), and show notes without a count.

### 7. MINOR: demo chips don't come back if the API was unreachable at first load
- **Where:** `web/src/features/scenario/ImportPage.tsx:140-147` (fetches once on mount); fallback `DEMO_TRIALS` is empty (`:261-267`).
- **Input → output:** page opened while the API was starting → "API unreachable" badge and no chips. Once the API is up, still no chips until a manual reload.
- **Fix:** refetch when health turns ok. Or fill `DEMO_TRIALS` with the four verified NCTs in A4's HANDOFF table, all fetched and verified (not from memory).

### 8. MINOR: protocol review edits — an empty week becomes 0, and bulk accept inflates the accuracy metric
- **Where:** `web/src/features/scenario/components/ProtocolReview.tsx:137` (`Number(e.target.value)`: clearing the field gives week 0), `:174` ("Done" marks the row `edited` with no check), and `:73` / `:56` ("Accept all remaining" rows are reported as `accepted`).
- **Input → output:** (from the code; not clicked) clear the week of V5 and press Done → week 0, row "edited". A4's apply rejects it with 422 `weeks_not_increasing` only because the order breaks; a cleared week on V1 would go through as week 0. In my run, after "Accept all remaining" the review log said 19/19 accepted unchanged (`accepted_unchanged_share: 1.0`), which reads as 100 % extraction accuracy.
- **Fix:** treat an empty or NaN week as invalid and disable Done on that row. Send the number of rows bulk-accepted without opening them; A4 will add an optional `bulk_accepted` field to `POST /api/import/protocol/review` and exclude those rows from the accuracy share.

## Checks that passed
- **§2 labels:** the registry card says "real registry data · served from the local cache" with the ClinicalTrials.gov attribution, data-processed date and modifications (meets the CT.gov terms); "Offline mode — cached data" and "Prototype" badges are shown.
- **Extraction UI (A4 contract):**
  - "AI DRAFT — confirm each row" stamp and A4's DRAFT notice.
  - Page, quote and confidence on every visit; excluded columns and warnings listed.
  - Nothing applied until Apply; pending rows are not applied.
  - Apply → A4 `/protocol/apply` → A5 stores v2 (visits leave `missing_fields`); the review is logged with the registry role.
- **Simulator:**
  - All five metrics shown as P50 + P10–P90.
  - Levers recompute (V3–V5 Home + on-demand + 50 % remote: cost P50 $365.4M → $178.7M, CO2e 1,186 → 825 t, same as A5's API directly).
  - Visits not remote-eligible are marked inline.
  - The provenance drawer shows formula ids, resolved inputs and per-country fallback assumptions.
  - The design's `missing_fields` and the engine warnings are reachable in a collapsible box.
- **Failure behaviour:** unknown design → clear "not found" panel with a way back; NCT format validated inline; PDF type and 20 MB checks before upload.
- **Tests:** vitest 25/25; `tsc --noEmit` clean.

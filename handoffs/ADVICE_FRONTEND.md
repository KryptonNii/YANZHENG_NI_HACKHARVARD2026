# Advice frontend: current-scenario comparisons and preview

Completed 2026-10-17 (America/Toronto), without committing or pushing. Existing unrelated work was retained.

## Files changed by this task

- `web/src/features/scenario/components/NextLever.tsx`
- `web/src/features/scenario/ScenarioPage.tsx` — only the existing NextLever call was extended.
- `web/src/features/scenario/nextLever.test.tsx`
- This handoff.

## Behavior

Advice requests contain the saved design ID/version and JSON of every current lever. The component clears old advice immediately on a changed design, version or selection; waits 250 ms before fetching; aborts the superseded request; and ignores a response that arrives after cleanup. A response must echo the matching design/version and equivalent `current_levers`. Object keys and selection arrays are normalized for comparison, so JSON insertion order does not create a false mismatch.

The card displays the API's sampling explanation (one ranking stage with seed `seed` and `draws` = 200 for the baseline, every candidate and the stress scenario; the formal scenario uses its own `scenario_draws`, 2,000 by default, so its figures can differ; the supply cap is disclosed in `sampling_note`), duration and modeled stockout constraints, stockout estimates or `Not estimated`, rejected-candidate reasons (including candidates ranked below the top three), blocked procedure removals, and procedure-review requirements. A `procedure_removal` recommendation or rejection also shows a "Not clinical approval" notice that removal still requires manual protocol review. `stress_scenarios` render in a separate "Stress test (assumption)" section tagged `assumption`; they are never ranked, recommended or previewed, and their cost change is not a saving. Empty recommendations are an expected state when evidence or constraints do not support a change. Model constraints are explicitly not clinical safety or protocol approval.

The API response types remain local to NextLever and match `api/trialpilot_api/advice/schemas.py`. No generated contract or backend file was edited. Raw patch JSON has been replaced by readable change descriptions and a `Preview this change` button.

ScenarioPage previews by merging the returned minimal patch into its current levers, which triggers the existing scenario computation. It does not save a design or scenario. The frontend additionally refuses to display a recommendation that changes the enrollment rate, drops an existing home-visit, telehealth-visit or excluded-site selection, or changes the procedure-removal set other than as a `procedure_removal` whose only patch field is `removed_procedures`, which keeps every current removal, adds exactly one code matching `procedure.code`, has only `not_linked` endpoint roles and is not in the returned blocked list. Arrays returned by the API are otherwise complete merged selections and replace only that corresponding field.

## Verification

Run from the `web` directory using the installed Node/runtime dependencies:

```powershell
& 'C:\Program Files\nodejs\node.exe' node_modules/typescript/bin/tsc --noEmit -p tsconfig.app.json
& 'C:\Program Files\nodejs\node.exe' node_modules/vitest/vitest.mjs run src/features/scenario/nextLever.test.tsx src/features/scenario/scenario.test.tsx src/features/scenario/peerMirror.test.tsx src/features/scenario/compute.test.tsx
```

- TypeScript: exit 0, no errors.
- Vitest: **49 passed, 0 failed**, four files (NextLever 15, scenario 21, PeerMirror 9, compute 4), completed about 01:47 EDT.
- After the single-stage advice refactor (2026-10-17): `nextLever.test.tsx` **21 passed**; `tsc --noEmit` clean for `tsconfig.app.json` and for `tsconfig.node.json` (which includes `e2e/next-lever.spec.ts`). The other three files were not re-run for that sync.
- New coverage includes complete-current-levers transport, refresh/debounce, cancellation and late responses for choices/version changes, mismatched response baselines, equivalent JSON key order, empty-state/rejection evidence, stockout and sampling explanation, contradictory removals, array-clearing/subset patches, errors/retry, and invalid saved versions.
- The integration test renders the real ScenarioPage, changes supply/local-lab/procedure-removal controls, clicks preview, and verifies the resulting compute preserves those choices. It confirms that neither saveScenario nor saveDesign was called.
- The broader existing scenario suite emitted React Router future-flag and asynchronous `act(...)` warnings; assertions passed.

The initial `pnpm exec` attempt invoked dependency verification and was stopped by the configured minimum-release-age policy. The successful commands above use dependencies already present in `node_modules`; no dependency policy, manifest or lockfile was changed.

## Remaining integration responsibility

The root agent owns the overall acceptance run. `web/e2e/next-lever.spec.ts` now follows the single-stage contract: it expects `seed` 7, `draws` 200 and `scenario_draws` 2000 (no `screening_draws`), assumption-tagged stress scenarios that never appear as recommendations, no recommendation touching the enrollment rate, and every `procedure_removal` adding exactly one unblocked code whose roles are only `not_linked`. An imported assumed schedule shows the reviewed-schedule rejection until protocol review is applied. The spec type-checks; the real-API flow needs the cached BOREAS registry study and was not re-run for this sync. These frontend results are component/integration evidence, not a claim that the whole current workspace or model has passed independent validation.

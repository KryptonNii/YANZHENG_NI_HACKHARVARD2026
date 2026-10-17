# Action predictions and follow-up (command center)

Completed 2026-10-17 in the shared working tree. Simulated feed only; every prediction below is a planning-model
output built from labelled assumptions, not an observed or clinical result.

## What it does

1. **Predict.** For a site-level `enrollment_lag` or `drug_overstock` alert, the alert detail (`options`) ranks the
   quantified recommended actions by predicted net value (cost avoided minus the action's cost, P50). Each option
   shows time saved, cost avoided, action cost and net value as P10/P50/P90, the reasoning and the assumptions.
   Quantified: `enrollment_retraining`, `activate_backup`, `supply_on_demand`, `transfer_excess`. Others are listed
   as "not quantified" with a reason. "Do nothing" equals the alert's own impact estimate (tested).
2. **Save.** Planning the action stores the prediction as it stood (`ops.intervention.expectation` audit entry,
   `expectation` on `GET /effects/{id}`). It is never recomputed.
3. **Compare.** `reconciliation` on `GET /effects/{id}` compares the observed difference-in-differences 95%
   interval with the predicted range for the weeks observed, diluted by the assumed start-up lag. Verdicts:
   `exceeded`, `met`, `partial`, `not_met`, `inconclusive`, `insufficient_data`. Only the metric the action moves is
   compared (kits on hand, enrollment rate); predicted days and dollars follow from the same model and are not
   observed separately (the response says so in `basis`).
4. **Re-plan.** `partial` or `not_met` after at least 6 observed weeks reopens the original alert, writes
   `ops.intervention.replan` to the audit trail, and the UI shows a banner. Once per intervention.

The prediction never reads the simulator or its ground truth (`test_prediction_never_reads_the_simulator_or_its_ground_truth`).
Ten new parameters, all `assumption: true` with a rationale and no source: `ops.effect.*` (6) and `ops.cost.action.*`
(4) in `data/fixtures/ops/ops_params.yaml`. They are independent of the simulator's knobs.

## Files

New: `api/trialpilot_api/ops/expectation.py`, `api/tests/ops/test_expectation.py`,
`web/src/features/command/expectation.test.tsx`, this file.
Changed: `ops_params.yaml`, `ops/store.py` (IvMeta fields, create/update attach the prediction, refresh hook,
`alert_detail.options`), `ops/router.py` (`/effects/{id}` adds two keys), `ops/KPIS.md`,
`web/src/features/command/{api.ts,present.ts,AlertsPanel.tsx,InterventionsPanel.tsx}`.
No shared contract (`contracts/**`) changed: the prediction lives in ops-internal dicts, so the `Intervention`
model is unchanged and the state is lost when `/simulate` is restarted, like all other ops state.

## Decisions that differ from the plan I proposed

- **Backup site.** The demo's only backup sites (S39, S40, Brazil) are already activated by the scripted I2 at day
  406, and no lagging site is in Brazil. So the option picks a free backup in the same country, else the nearest
  one, and names it explicitly as the intervention target. Its metric is the country-level
  `regional_enrollment_rate_per_month`, not the lagging site's own rate. At the default clock (day 406) the option
  reads "no unactivated backup site"; at day 180 it is offered (tested).
- **Re-plan reminder** was added after the friend's description (not in the first file list).
- **Retraining** is modelled as closing a share of the gap to the planned rate, not a multiplier of the current
  rate: a multiplier on a site with near-zero enrollment predicts nothing.

## Measured on the demo seed (seed 42, day 406, simulated)

Drug overstock at S14 (alert impact $106k P50). Planned on-demand resupply: predicted net $72.3k ($29.3k to $140.6k),
predicted fall in kits on hand −43 (−61 to −24) over the window. Observed fall −87 (95% interval −99 to −75) after
5 observed weeks: `exceeded`, and still `exceeded` at 8 and 12. Transfer of excess kits: predicted net $60.1k;
`exceeded` after 5 and 8 observed weeks, `met` after 12. The alert resolved by itself in both runs.

This verdict only says the stock fell by at least as much as predicted. The prediction counts kits recovered from
projected expiry, a lower bound on the stock change, so `exceeded` is expected here and does not validate the
dollar savings.

Enrollment retraining at S06, S14: predicted +0.1 to +0.2 patients/month, below the metric's detection floor of
0.3. All follow-ups at 5, 8 and 12 observed weeks were `inconclusive` (single-site intervals about ±1.5 patients
per month). The planning dialog warns about this before the action is chosen. Net value (P50): S14 +$7.8k, S06
+$2.9k, S26 +$0.2k. S30 (never enrolled) has no ranked option: its recommendations are close the site, a backup
site and a feasibility call.

The re-plan path did not occur naturally in these runs. It is covered by a test that forces an implausible
forecast, which shows the mechanism, not realistic behaviour.

## Tests

`cd api && .venv/Scripts/python.exe -B -m pytest tests/ops -q -p no:cacheprovider` (27 new tests in
`test_expectation.py`, 38 existing ops tests unchanged and passing); `cd web && corepack pnpm@9.15.9 exec vitest run
src/features/command` (6 new tests). Whole-folder runs on the shared working tree: `api/tests` (417 tests, all passed, no failures), `web` vitest (14 files, 131 tests, all passed), `tsc --noEmit` clean, `ruff check` clean on `ops` and `tests/ops`. The backend commit was also checked on a clean export of HEAD plus these hunks only: `tests/ops` 61 passed.

## Commit scope

The backend is committed (`expectation.py`, the `store.py` and `router.py` hunks, `ops_params.yaml`, `KPIS.md`,
`test_expectation.py`, this file). `store.py` and `router.py` carry another session's uncommitted edits in the
working tree; only the hunks of this work were committed. The four web files (`api.ts`, `present.ts`,
`AlertsPanel.tsx`, `InterventionsPanel.tsx`) and `expectation.test.tsx` are left uncommitted in the working tree:
they sit next to another session's unfinished i18n pass and import its untracked `web/src/app/i18n.ts` and
`displayText.ts`, so a commit at HEAD would not build.

## Not verified

- The prediction card was checked in a real browser against the real API as text; a screenshot of it could not be
  captured (the pane returned blank images when scrolled). The dialog table was captured.
- Chinese UI: all new labels use `t(en, zh)`, but the server's reasoning, warnings and explanation strings are
  English and shown as is.
- No clean-clone validation run. The README's "576 passed at e5c386b" does not cover this code.
- Parameter values are placeholders with wide ranges, not calibrated. Nothing here is validated against real trials.
- Other sessions edited `store.py`, `router.py`, `AlertsPanel.tsx`, `InterventionsPanel.tsx` and `present.ts` in the
  same working tree while this was built; their changes are not part of this work.

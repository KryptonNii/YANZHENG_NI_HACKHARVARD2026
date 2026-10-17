# Command-center lock recovery rehearsal

The existing `/command/demo-40` page opens with one guided, explicitly simulated
story: see lock slip outside its planned band, reveal two executable replay
actions, then compare their follow-up judgments side by side. Starting an action
shows `inconclusive`; reading follow-up reveals the recorded estimator result.
SMS alone never recovers the lock forecast. Reset clears both action states.

`lock_recovery_story.json` supplies the authored lock forecast and operational
copy. The lock timeline assumes enrollment/vendor prerequisites are complete and
query clearance is the final bottleneck. It is **not** an output of the backend
milestone forecaster, which does not link eCRF retraining to lock dates. This
distinction is visible in the page. Replay buttons do not mutate the API's
scripted, read-only interventions or advance its clock.

`lock_recovery_evidence.json` contains actual outputs of the existing seeded
`estimate_effect` function for I1 and I4, including early inconclusive estimates,
matched controls, windows, values, and 95% intervals. The original intervention
dates differ; the UI displays their respective windows rather than pretending
they were simultaneous. It retains seed 42, the 40-site design, `simulated: true`,
and `Simulated feed`. No new effect classifier is introduced.

Regenerate or independently check evidence from the repository root:

```powershell
uv run --project api python data/fixtures/ops/export_lock_evidence.py
uv run --project api python data/fixtures/ops/export_lock_evidence.py --check
```

Neither the exporter nor runtime UI reads `ground_truth.json`. Command tests
compare the rendered judgments with its existing I1/I4 answers and compare the
scripted lock path with its additional `command_lock_recovery` answer key.

```powershell
cd web
corepack pnpm test -- src/features/command
corepack pnpm exec playwright test e2e/command.spec.ts
corepack pnpm exec playwright test --config src/features/command/lockStory.playwright.config.ts
```

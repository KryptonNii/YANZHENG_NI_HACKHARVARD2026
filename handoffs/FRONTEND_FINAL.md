# TrialPilot frontend and presentation handoff

Status: **FRONTEND_READY** (2026-10-17, America/Toronto). Frontend code stayed frozen during complete combined validation. Final documentation and actual application media are complete. Exact commits and verification receipts are recorded below.

## Commits and ownership

- Frontend code: `e425ca25541e69b40328337aba0ef5145fcd8d91` on existing `dev`.
- Includes inherited A8/A9 fixes plus final concurrency/normalization regressions. Only 48 explicit web paths were committed. Generated `web/src/contracts.ts` was neither edited nor staged by this task; backend owns its v5 update.
- Final documentation/media commit: `52e617a728b0a5ab5a6878419236ce4da8896529` (54 explicit allowed files; no application code change).
- Backend code: `f91cdb2`; complete tested code: `e5c386b1fb0b6edf362bf5d37b97cc17066dfd07`; backend evidence/handoff receipt: `0579470`. Later commits only change presentation/documentation files.
- Initial working tree and inherited web diff archived in OS temp below. No frontend file changed concurrently after the baseline snapshot. Backend changes were left intact. Existing untracked `web/e2e/scenario-screenshots/` were preserved, not treated as final captures.

## Verification of frontend code

Run root: `C:/Users/ol735/AppData/Local/Temp/tp-frontend-9e83bff8d4154ba7a5a779c29daa3243/`.

| Check | Result | Log |
|---|---|---|
| `corepack pnpm@9.15.9 --dir web typecheck` | PASS, generated v5 | `typecheck-final.log` |
| `corepack pnpm@9.15.9 --dir web build` | PASS, production bundle | `build-final.log` |
| `corepack pnpm@9.15.9 --dir web test` | 48 passed, 6 files | `unit-final-2.log` |
| Real Edge + API E2E | **12 passed, 0 failed/skipped/retried** | `e2e-final.log`, `e2e-final/` |
| `git diff --check -- web` | PASS | console |

These are frontend checks against the shared working backend, not a substitute for final complete validation of the combined committed code. Some test logs include React act/router future warnings; no assertion was waived.

Core browser coverage: unseeded NCT04456673 persists before simulator opens; a concurrent design change leaves compute/save pinned, and saved metrics/forecast/supply exactly match the computed JSON; same-version comparison uses per-draw ranges, different versions do not; real 409 stale edits; BOREAS protocol review/empty week/bulk_accepted; re-import keeps confirmed visits unchanged unless the explicit replacement action is used; recovery after unavailable health restores chips; save/submit, author denial, Reviewer then QA, signed hash/manifestations; audit verification and CSV; site/country full-week histories, open partial week, backup sites, alerts/interventions/effects; validation package count/status and downloaded Markdown/PNG/ZIP hashes.

Unit coverage additionally includes unknown metrics, curve gaps, missing protocol week rejection, superseded compute responses and retry without changing levers, grouped procedures, broken audit chain, changed approval record, unknown/missing package states.

## Isolated runtime / reproducibility

- API `http://127.0.0.1:8008`, Vite `http://127.0.0.1:5181`.
- `DEMO_OFFLINE=1`, `TP_SEED_FIXTURE_DESIGNS=0`, `TP_DB_PATH=<run root>/final.sqlite`, `TP_DATA_DIR=<run root>`, `TP_VALIDATION_OUT=<run root>/validation-final`.
- API launched with `api/.venv/Scripts/python.exe -m uvicorn trialpilot_api.main:app --host 127.0.0.1 --port 8008`. Vite uses `API_TARGET=http://127.0.0.1:8008` and `--port 5181 --strictPort`.
- E2E: from web, `node node_modules/@playwright/test/cli.js test --output <run root>/e2e-final --reporter=list`, reuse only this task's isolated servers. Set `E2E_WEB_PORT=5181`, `E2E_API_PORT=8008`, `CI=`.
- Download regression copied unchanged historical package `validation/out/clean-clone/20261017T023042Z/package` to the temporary output with `A9_VALIDATION_SOURCE` and `A9_VALIDATION_OUT`. It reports commit `38e2073`, 507 passed / 3 failed, awaiting QA. It tests rendering/download integrity only; it is **not current product validation**. Final media uses the new 20261017T041438Z backend package; the historical package is not used in delivered captures.
- E2E API PID 19780 was stopped before final media. Recording API PID 43160 used fresh `media.sqlite`, with unchanged final package copied to `<run root>/validation-media/package`; Vite PID 6688 served 5181. Cleanup receipt is below. Other ports/services/databases were untouched.

## Full demo route

1. `/`: BOREAS chip or NCT03930732 → **Use the registry protocol (cached extraction)** → review source page/quote → **Accept all remaining** (bulk review is not accuracy) → **Apply to design**. Empty week blocks Done; template warning clears after apply. The cached extraction is a transcription, not measured live LLM accuracy.
2. **Open scenario simulator**: show design vN, assumptions, five ranges. Change remote monitoring and **On-demand resupply**; the recording does not change visits or remove procedures without clinical eligibility review. Save stays disabled while a calculation is pending. Show forecast/supply requested/used draws and duration/waste provenance. Do not promise a clinical benefit from a design lever.
3. **Save scenario** → name → **Save** → **Submit for approval**. Alex PIN 1111 is denied; switch Riley 2222 to review, Sam 3333 to approve. These are fictional automated demo identities, not human QA sign-off.
4. `/compare`: choose two saved scenarios on the same design version; show per-draw differences. A different design version gets a warning and only differences of P50s.
5. `/command/demo-40`: **Start simulation** (or **Restart simulation**), **Sites** / **Countries**, source badges, complete weeks and backup zero plan. S14 drug overstock → **Acknowledge** → **Plan intervention** → **Save intervention** → **Start intervention** → **Advance 6 weeks**. Show the returned effect interval and interpretation. All feeds are synthetic.
6. `/audit`: **Verify chain**, filters, **Export CSV**. Current audit is distinct from the validation package's generation-time snapshot.
7. `/science`: use the final generated output, reveal module gaps and sampling assumptions. `/validation`: show package/execution commits, actual counts and failures, **awaiting QA approval**, then download evidence/manifest.

## Complete combined validation

Original report: `validation/out/clean-clone/20261017T041438Z/summary.json` and `package/report.md`. Package entry: `validation/out/clean-clone/20261017T041438Z/package/index.html`. Tested commit **e5c386b1fb0b6edf362bf5d37b97cc17066dfd07**, clean clone. [Backend final](BACKEND_FINAL.md) records conditions and all paths.

- **576 passed, 0 failed/errors/skipped/unrun**, including contracts 106, engine 105, API 233, operations 34, validation 50, science 36, real Edge E2E 12. No retries/flakes.
- 13 preflight checks passed, including generated v5 contracts, parameter/license checks, web typecheck/build and **48/48 unit tests**. The 48 is separate from 576.
- **32/32 requirements passed**, zero untested/incomplete/failing requirements, including substantive URS-014 science/module/WTT tests.
- **114/114** package hashes/downloads verified through the real compliance HTTP router. No integrity problems. Package-generation audit snapshot: 12 intact entries; final post-packaging audit: 14 intact entries.
- Full-suite E2E ran before package creation and checked honest `package_not_built`. A separate **1/1** unchanged real browser package test ran against the final package, including Markdown/PNG/ZIP hashes: `validation/out/backend/20261017T042216Z-package-browser/`; no skip/retry. Separate from 576.
- Cold server compute: **147.8 ms median**, seven distinct cache-miss seeds 200–206 and 2,000 requested forecast draws. <300 ms gate passed. Earlier standalone **308.2 ms** miss and historical **664.1 ms** failure at 38e2073 remain preserved; no universal latency guarantee.
- Report **awaiting QA approval**; `human_qa_approval=false`; automated demo signatures do not constitute actual human approval.

No backend defect blocks the demonstrated flows. Original evidence and backend/science sources were not edited by this task. The original validation output is local and ignored by Git; it has not been externally archived or uploaded.

## Final scientific source

`science/out/results.json` at tested e5c386b; parameter set **1249d0f0eed8**, seed **7**, **2,000 draws**. SHA256 `51b307a5a85795969551bf4bde514044f95cc988484f83f8c3600082668358a2` (also confirmed in backend handoff).

| kg CO2e | Published | Engine/library P10 / P50 / P90 | P50 gap |
|---|---:|---:|---:|
| CASPS | 71,938.8 | 64,601.50 / 88,758.48 / 123,510.08 | **+23.38%** |
| PRIMETIME | 89,360.2 | 87,891.34 / 109,685.91 / 142,685.69 | **+22.75%** |

Paper arithmetic is separately +0.01% / −0.16%. Drug_supply excluded, direct/WTT counted once each. Old +5%/+7% results are obsolete. Both references are inside ranges but module gaps remain: PRIMETIME subgroup coverage, hospital utilities, some samples/audits and assumed monitoring/initiation/closeout activity. The pitch does not infer cost, forecast or clinical accuracy from carbon reproduction.

## Final materials and media paths

All paths relative to repository root unless noted.

- `README.md`; `docs/DECK.md` (exactly 12 slides, 3 points + cited speaker note each); `docs/DEVPOST.md` (unsubmitted draft); `docs/JUDGE_QA.md` (15 answers); `docs/DEMO_RUNBOOK.md` (8008/5181, unique OS temp DB); `docs/VIDEO_SCRIPT.md`; `docs/EVIDENCE.md`; `docs/STACK_AND_LICENSES.md`.
- Editable deck: **`docs/assets/trialpilot-deck.pptx`**. Twelve 1280×720 slides; native text and three native tables. Every slide rendered and visually inspected; package/layout/font/import checks passed with zero findings. Previews: `docs/assets/slides/slide-01.png` through `slide-12.png`. Native PowerPoint application playback was not separately tested.
- Actual video: **`docs/assets/trialpilot-demo.webm`**, **180.000 seconds**, 1440×900, 25 fps, VP9. Silent screen recording; no voice-over. English captions: `docs/assets/trialpilot-demo.en.vtt`; local player: `docs/assets/demo-player.html`; 18 contiguous cues, 300 words, 0–180 seconds. No upload URL or publishing claimed.
- Actual screenshots: `docs/assets/screenshots/01-home.png`, `02-import.png`, `03-protocol-review.png`, `04-protocol-applied.png`, `05-simulator-baseline.png`, `06-simulator-scenario.png`, `07-forecast.png`, `08-provenance.png`, `09-self-approval-blocked.png`, `10-demo-approved.png`, `11-audit.png`, `12-command.png`, `13-intervention.png`, `14-effect.png`, `15-science.png`, `16-validation.png`, `17-validation-qa.png`, `18-country-weeks.png`, `19-site-weeks.png`.
- `08-provenance.png` is a frame from the raw actual recording after the drawer's transition settled; other primary captures are direct Playwright screenshots. Supplemental QA/site/country captures use the same code and temporary DB, after recording.
- Capture actions/times: `docs/assets/screenshots/capture-log.json`; actual downloaded evidence manifest: `docs/assets/screenshots/downloaded-evidence-manifest.json` (unchanged download, not regenerated evidence).
- Source metadata/hashes: `docs/assets/release-data.json`; final output inspection/hashes: **`docs/assets/media-manifest.json`**. Authoring sources: `record-demo.mjs`, `build-deck.mjs`, `caption-cues.json` under `docs/assets/`.
- Raw video and temporary database: `<run root>/video-raw/page@99558bdef0064615e35724acf5f39493.webm`, `<run root>/media.sqlite`. First 2.24 seconds of setup and final tail removed to make exactly 180 seconds; no result/action substitution. Private final deck validation receipt: `<run root>/deck-build-4/.codex-finalizer/deck.validation.json`.

Media inspection includes actual import/review, ranges/provenance, self-approval denial, separate demo signatures, audit, synthetic interventions, science and final validation counts. The recording intentionally omits optional compare/concurrency and extended weekly drilldowns to fit three minutes; these are covered by tests and the full runbook. Final local-link/structure check and media duration/playback results are in the manifest.

## Specific remaining gaps

1. **No human QA approval**, live LLM accuracy or measured human validation effort. Automated identities and bulk acceptance must remain labelled demo/review activity.
2. **No Docker verification, deployment URL, public video upload or submission.** No push/publish performed. Physical network disconnection was not separately rehearsed; cached offline application mode was demonstrated.
3. **No observed clinical/financial savings, real-world model coverage or clinical eligibility review** for visit/procedure changes. Model/source limitations remain as disclosed.
4. **Original sponsor sheets/rules and public repository URL are unavailable.** Challenge-title mapping is from the supplied brief; no Tufts percentages were invented.
5. **Original complete validation evidence is local, ignored by Git and not externally archived.** Preserve the exact timestamped output and hashes when archiving later.
6. Native PowerPoint playback and an audio narration track are not claimed. Delivered deck was rendered/import-validated; delivered video is silent with captions.

## Ownership and submission receipt

Application code remained unchanged after FRONTEND_READY; `git diff e5c386b -- web contracts engine api/trialpilot_api science data/params` was empty before materials submission. Inherited `api/README.md`, `prof.out` and `web/e2e/scenario-screenshots/` are outside this task's final submission and were preserved. No reset/clean/stash/branch change/worktree/push/system installation was used. Playwright's portable media dependency was downloaded only into the OS temporary run root.

Cleanup: owned recording API **43160** and Vite **6688** were stopped after capture/playback checks. Ports 8008/5181 have no listener. Earlier owned API PIDs 10096/19780 were also stopped. No other service or database was changed.

Final material checks: **115 local Markdown links, zero missing**, 12 slide sections with 3 points and cited notes each, 15 Q&As, 18 contiguous caption cues covering exactly 180 seconds. Final WebM checked by FFmpeg and Edge (1440×900, 25 fps, 4,500 frames); six browser seek/caption checks passed, terminal frame confirmed through sequential decoding and browser playback. Video SHA256 `2d5766d78911aabac28db6b0bc873e6761d84a869ee742d5acc1f959392bca5e`; PPTX SHA256 `1e5568daae606f7ae50ab3ce2e0f88951e04c0c74d78c36c671e3208a8aace1c`. Downloaded evidence manifest matches the original package byte-for-byte.

### Final commit receipt

- Frontend code: **e425ca25541e69b40328337aba0ef5145fcd8d91**.
- Documentation/media: **52e617a728b0a5ab5a6878419236ce4da8896529**; 54 explicit files, approximately 24.9 MB total assets/content.
- This handoff is a separate final receipt commit; it records the two deliverable commits without requiring a self-referential hash.
- Complete product validation applies to **e5c386b1fb0b6edf362bf5d37b97cc17066dfd07**, not to the later documentation-only HEAD as a newly executed product run. Application source remained identical.
- Final status: **FRONTEND_READY; MATERIALS_READY**. Remaining gaps above are explicit, not silently marked complete.

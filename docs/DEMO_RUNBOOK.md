# TrialPilot — demo runbook

Verified code: **8fca2d71cde979909c7a8535d43dc95b4f6c94c0**. Complete run: **819 passed / 0 failed**, 32/32 requirements passed; report **awaiting QA approval**. [Summary](evidence/clean-clone-20261018T061014Z/summary.json). The [180-second recording](../README.md#demo-media) was made earlier on `e5c386b` (576 passed, [summary](evidence/clean-clone-20261017T041438Z/summary.json)) and uses the actual local application and that package, with a fresh temporary database. Its subtitle track is available in the [player](assets/demo-player.html); no voice-over is included.

## Isolated setup on Windows

Use the existing `dev` checkout and already prepared Python/web dependencies. Do not reset a shared database or stop another task's service. API **8008** and UI **5181** are this frontend task's ports; **8007/5180** belong to backend validation. Inspect whether ports are free before starting.

In a first PowerShell terminal at the repository root:

```powershell
$tpDemo = Join-Path $env:TEMP ('trialpilot-demo-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tpDemo | Out-Null
$tpValidation = Join-Path $tpDemo 'validation'
New-Item -ItemType Directory -Path $tpValidation | Out-Null
Copy-Item -LiteralPath 'validation/out/clean-clone/20261017T041438Z/package' -Destination $tpValidation -Recurse
$env:DEMO_OFFLINE = '1'
$env:TP_SEED_FIXTURE_DESIGNS = '0'
$env:TP_DB_PATH = Join-Path $tpDemo 'demo.sqlite'
$env:TP_DATA_DIR = $tpDemo
$env:TP_VALIDATION_OUT = $tpValidation
api/.venv/Scripts/python.exe -m uvicorn trialpilot_api.main:app --host 127.0.0.1 --port 8008
```

In a second terminal, also at the root:

```powershell
$env:API_TARGET = 'http://127.0.0.1:8008'
$env:VITE_MOCK_API = '0'
Set-Location web
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5181 --strictPort
```

Open [local app](http://127.0.0.1:5181). Verify **Offline mode — cached data**, no Mock API badge, and API health at [8008](http://127.0.0.1:8008/api/health). The recorded offline mode uses cached data; physically disconnecting the network was not separately tested. Dependency installation and optional live extraction require connectivity. Container build/run and public deployment remain unverified.

Reset by stopping **only these two foreground commands** with Ctrl+C and starting a new unique temporary directory. Keep previous run evidence. Do not kill processes by a broad name, delete another database, or reuse the backend validation ports.

## Presenter card

| Item | Value |
|---|---|
| Primary trial | BOREAS, NCT03930732; registry snapshot: 939 enrolled, 275 sites, 24 countries, 48.6 months |
| Protocol input | Cached build-time transcription; 19 candidate visits, page/quote evidence; not measured live LLM output |
| Demo changes | 50% remote monitoring and On-demand resupply; hypothetical inputs |
| Patient visits / procedures | No home-visit change or procedure removal in the recorded demo; eligibility review not established |
| Design/scenario versions | Read the page and saved row; do not invent UUIDs or hardcode version 1 |
| Demo identities | Alex Author / 1111; Riley Reviewer / 2222; Sam QA / 3333 — fictional |
| Operations | `/command/demo-40`; synthetic 40-site feed; S14 overstock |
| Science | `science/out/results.json`; parameter set 1249d0f0eed8; seed 7, 2,000 draws |
| Package | `validation/out/clean-clone/20261017T041438Z/package` |
| QA | Validation report awaiting QA approval; automated scenario signatures do not approve the report |
| Recording | `docs/assets/trialpilot-demo.webm`, exactly 180.000 seconds; silent with WebVTT captions |

## Full walkthrough

Navigation labels: **Trials** (import), **Analysis** (scenario simulator), **Compare**, **Operations** (command center), **Approvals**, **Audit**, **Validation**, **Models** (science checks), **Methods**.

1. **Trials** → BOREAS chip (or enter NCT03930732 and click **Import**). Inspect **Pending inputs** and the registry/map source notes. A new trial is stored before **Scenario analysis →** becomes available.
2. **Extract registry protocol**. Inspect draft, page, quote, procedure-group names and counts. **Edit visit** then blank the week: **Done** is disabled; a blank is never converted to week zero. Restore the week or cancel editing. **Accept all remaining** is a demonstration of bulk review; it is logged as a subset of accepted rows, not extra approvals or extraction accuracy. **Apply to design** saves a new version and clears only resolved template warnings.
3. Import the same NCT again. The stored confirmed protocol is retained. Use the explicit replacement control only if intentionally replacing a template in this temporary demo.
4. **Scenario analysis →** opens **Analysis**. Read the design vN badge. Set **Monitoring visits done remotely** to 50% and choose **On-demand resupply**. Wait for computation and enabled **Save scenario**. Metrics, forecast and supply remain pinned to this design version; unknown fields display unknown and missing curves are not fabricated.
5. **Calculation details** on carbon, duration or waste opens provenance. Inspect formula, input, parameter source/assumption and draw counts. **Close panel** or Escape returns to the page.
6. **Save scenario** → descriptive **Name** → **Save**. The saved row contains the same computation and design version. **Submit for approval** → on **Approvals**, **Sign this record** as Alex with PIN 1111 → **Sign** is rejected with “Authors can't approve their own work.” Select Riley, PIN 2222, meaning *reviewed* → **Sign**; then Sam, PIN 3333, meaning *approved* → **Sign**. Show signatures, UTC timestamps and record hashes. These are automated fictional demos.
7. Optional compare: save a baseline and altered scenario at the same design version, tick both rows, open **Compare**. Show **P10–P90 of the difference**. Different design versions instead show a version warning and differences of P50s. Do not compare them as paired draws.
8. Optional concurrency: keep **Analysis** open while a second editor changes the design. The original page computes/saves its original vN. Stale **Edit facts → Save changes** returns a visible version conflict instead of silently overwriting the new design. Automated evidence verifies JSON equality of computed and saved metrics, forecast and supply.
9. **Audit → Verify chain** → intact result; inspect rows and **Export CSV**. A broken-chain unit fixture shows a damaged state, but the live demo database is not deliberately corrupted. **Approvals** also exposes pending/approved records and the same independent roles.
10. **Operations** (`/command/demo-40`) → **Start** (or **Restart**). Keep **Simulated feed** visible. **Sites** and **Countries** show completed weeks; current totals can include the open partial week. Backup sites retain zero enrollment plans. Country plan bands sum site bands, rather than a new joint percentile calculation.
11. S14 drug-overstock alert → **Acknowledge** → **Plan intervention** → **Save intervention** → **Start intervention** → **Advance 6 weeks**. Show the effect verdict and explanation. The card reports bootstrap P10–P90; the explanation's 95% interval is wider and determines the verdict. Do not describe them as the same interval. The synthetic comparison does not prove causation or clinical effectiveness.
12. **Models**: CASPS +23.38%, PRIMETIME +22.75% engine/library P50 gaps, with module boundaries. **Validation**: actual tested commit e5c386b, 576/0 counts, draft/QA status and evidence attachments. **Download evidence manifest**, **Download package manifest** or **Download Markdown**; the final backend run verified all 114 package files and hashes.

## Re-recording and evidence

[record-demo.mjs](assets/record-demo.mjs) drives real UI actions against these services without API response mocks. Set `TP_CAPTURE_DIR` to a new directory, and optionally `TP_VIDEO_DIR` to an OS temporary output folder; Playwright's portable ffmpeg dependency must already be prepared. Run `node docs/assets/record-demo.mjs` from the repository root. Without `TP_VIDEO_DIR` it performs a fast rehearsal. With it, stage deadlines target the [180-second script](VIDEO_SCRIPT.md); inspect the capture log, trim only initial loading/tail to 180 seconds, verify duration and representative frames, and do not claim success if an action fails.

The delivered media manifest records codec, duration, source hashes and inspection points. Raw capture and temporary database were retained in the frontend run root documented in [FRONTEND_FINAL.md](../handoffs/FRONTEND_FINAL.md). Evidence checks are read-only; do not regenerate or overwrite original validation files while recording.

## Failure handling

If a control fails live, state the failure and switch to the verified local recording. Do not substitute a mock result as real. If the final package is unavailable, show “No validation package yet” and name the absent file; never replace it with historical passing counts. Human QA, live LLM accuracy, human effort timing, Docker and deployment remain gaps even after successful playback.

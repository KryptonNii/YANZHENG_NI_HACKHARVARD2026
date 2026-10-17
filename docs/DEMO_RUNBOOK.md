# TrialPilot — three-minute demo runbook

**Status: rehearsal draft.** A11 checked existing source labels, not a running end-to-end application. Missing integration results, trial selection and A9 interior controls are explicit gates below. Do not present unverified steps as demonstrated behavior.

The live demo follows the same [180-second script](VIDEO_SCRIPT.md). Open the app, problem slide, closing slide and terminal before the timer starts. Recordings must retain prototype, simulated and mock disclosures. Cost, site workload, patient travel and timeline come before carbon.

## Readiness gates

| Gate | Required preparation | State at A11 draft |
|---|---|---|
| G1 | API and built UI start; `/api/health` reports offline; UI has no Mock API badge | Not executed by A11 |
| G2 | A4 selects a real cached Phase 3 trial and confirms identity, site count, locations and visit assumptions | Trial id pending A4 |
| G3 | A2/A3/A5 computation and A8 UI produce matching ranges and provenance | Integration evidence pending |
| G4 | Pick exactly three clinically eligible visit numbers and one optional removable procedure for the selected fixture | Fixture choices pending; do not invent eligibility |
| G5 | Save and submit works; author denial returns `self_approval_forbidden`; Riley then Sam signs; chain verifies | A7 execution evidence / integrated UI rehearsal pending |
| G6 | A6/A9 provides a reproducible labelled synthetic overstock alert and qualified effect comparison | Controls, reset interface and fixture pending |
| G7 | A10 supplies generated JSON and distinguishes paper arithmetic, engine reproduction and library sensitivity | Pending; published references alone do not satisfy gate |
| G8 | A7 supplies package CLI options, package index, executed evidence and detected/attempted defect report | Pending |
| G9 | Actual UI captures and local 03:00 backup video are checked | Not recorded |
| G10 | Disconnect after caches are prepared and repeat the chosen walkthrough successfully | Not executed |

The original Regeneron sheets are also needed to verify sponsor quotations and Tufts figures. The existing deck uses independently sourced context and identifies the title mapping as brief-provided.

## Rehearsal setup

Human/judge defaults: API `8000`, development UI `5173`; Docker serves both UI and API on `8000`. A11 may start only its own servers on API `8011` and UI `5184`. Do not run a repo-wide test command while others build.

From a configured Bash shell at the repository root, with dependencies already installed:

```bash
make dev API_PORT=8011 WEB_PORT=5184 DEMO_OFFLINE=1 \
  TP_DB_PATH="$PWD/docs/.rehearsal.sqlite" \
  TP_CORS_ORIGINS=http://localhost:5184,http://127.0.0.1:5184
```

Open `http://localhost:5184/`. Confirm `Offline mode — cached data` and absence of `Mock API — fictional data`. Those labels come from `web/src/app/Layout.tsx`. An API unreachable badge or mock mode means G1 fails. The initial install and container build can require a network even when the demo runtime is offline.

Before the timer, fill this presenter card from actual owner handoffs and rehearsal:

| Presenter card item | Value |
|---|---|
| Build commit and rehearsal timestamp | Pending |
| Cached NCT id / trial title / site count | Pending A4 evidence |
| Visit numbers approved for Home | Pending fixture review |
| Optional procedure code / rationale | Pending fixture review, otherwise omit |
| Rehearsed cost-increase example | Pending computed result, otherwise explain it as a possibility |
| Scenario / design / approval ids | Capture from rehearsal responses, never invent UUIDs |
| Synthetic overstock / effect cases and reset controls | Pending A6/A9 |
| Science output identity and engine/reference status | Pending A10 |
| Package output directory / index / defect report | Pending A7 |
| Backup video path and checked duration | `docs/assets/trialpilot-demo.mp4`, not created |

## Exact controls confirmed in current source

| Target | Interaction | Source checked |
|---|---|---|
| Import page | Click **Import** in main navigation | `web/src/app/Layout.tsx` |
| Registry import | Enter the presenter card's NCT id in **ClinicalTrials.gov ID**, click the form's **Import**, inspect **Missing & assumed**, then **Open scenario simulator →** | `ImportPage.tsx`, test ids `nct-input`, `nct-submit`, `open-simulator` |
| Simulator | Click **Simulator** after a design is selected | Same file; uses last selected design id |
| Monitoring | Focus slider **Monitoring visits done remotely**, press Home, then Right Arrow ten times for 50% (5-point steps) | `LeversPanel.tsx`, test id `lever-remote-monitoring` |
| Home visits | In each selected **Visit {number} {label} location** group, click **Home** | `LeversPanel.tsx`; eligibility must be confirmed separately |
| Supply | In **Drug supply strategy**, click **On-demand resupply** | `LeversPanel.tsx` |
| Optional procedure | In **Remove procedures**, tick the rehearsed procedure label | `LeversPanel.tsx`; removes that code from all visits |
| Provenance | On a metric card, click **How is this calculated?** | `MetricCard.tsx` |
| Close provenance | Click **Close panel** or press Escape | `web/src/app/ui/index.tsx` |
| Save | Click **Save scenario**, enter `Scenario B` in **Name**, then click **Save** | `ScenarioPage.tsx` |
| Submit | In **Saved scenarios & approval**, select Scenario B, then click **Submit for approval** | `VersionsPanel.tsx` |
| Sign in simulator | In the embedded **Approval** panel, enter the current user's demo PIN in **Re-enter your PIN** and click **Sign: reviewed**, then **Sign: approved** after review | `ApprovalPanel.tsx`; current required meaning controls button text |
| Lever reset | Click **Reset to baseline** | `LeversPanel.tsx` |
| Identity | Select **Alex · Author**, **Riley · Reviewer**, or **Sam · QA** in **Demo identities** | `IdentitySwitcher.tsx` / `identity.ts` |
| Other pages | Click **Approvals**, **Audit**, **Command center**, **Science**, **Validation** | `Layout.tsx`; route existence alone does not verify page behavior |

The simulator's embedded approval panel supplies the confirmed signing controls, so approval can use that route without relying on A9's separate Approvals page. A9 audit, simulation and intervention interior controls still need final labels. Every control still needs a running integration rehearsal. The timeline identifies remaining gaps explicitly.

## Timed live sequence

Intervals have inclusive starts and exclusive ends. Move to the next segment at the boundary, including after failure. Do not add recovery time.

| Time | Exact navigation / action | Required visible evidence / failure action |
|---|---|---|
| 00:00–00:08 | Start on **Import**, title visible | Prototype and offline badges; no Mock API badge |
| 00:08–00:24 | Switch to deck slide 2, then back to **Import** | Historical cost context with date/source; no unsourced Tufts claim |
| 00:24–00:40 | Enter the cached id in **ClinicalTrials.gov ID**, click the form's **Import**, inspect **Missing & assumed**, then **Open scenario simulator →** | Registry facts and assumed schedule; fixture identity still pending A4, otherwise use the script fallback |
| 00:40–01:08 | Monitoring slider Home + Right Arrow ×10; click **Home** for the three confirmed visits; click **On-demand resupply**; tick optional procedure only if confirmed | Wait for recomputation to finish; compare actual ranges and trade-off; no numeric claim if computation fails |
| 01:08–01:24 | Click **How is this calculated?** on the selected metric; inspect, then **Close panel** | Actual formula, inputs, parameter versions and sources; fallback if drawer unavailable |
| 01:24–01:37 | Select **Alex · Author**; **Save scenario**, **Name** = `Scenario B`, **Save**; in **Saved scenarios & approval** click **Submit for approval** | Record saved version and approval id; keep embedded Approval panel visible |
| 01:37–01:49 | As Alex, enter the documented demo PIN in **Re-enter your PIN**, click **Sign: reviewed** once | Show actual `self_approval_forbidden` denial; absence of a button does not prove server enforcement |
| 01:49–02:07 | Select Riley, enter their PIN, **Sign: reviewed**; select Sam, enter their PIN, **Sign: approved**; click **Audit** and verify | Reviewer before QA, signature manifestations and current hash; audit verify control pending A9, or show the actual API verification response |
| 02:07–02:29 | Click **Command center**; use prepared synthetic alert/intervention/effect case | Visible synthetic label, alert, assignment and qualified effect; interior controls/reset pending A6/A9 |
| 02:29–02:42 | Click **Science** | Generated results and computation path, or say pending; current script uses pending narration |
| 02:42–02:54 | Click **Validation**; show package index, traceability and executed evidence if available | Do not treat package presence as execution/approval; interior controls pending A9/A7 |
| 02:54–03:00 | Switch to deck slide 12 | Limits and proposed pilot; stop at exactly 03:00 |

## Approval preparation and API fallback

A7's source requires `reviewed` then `approved` for scenarios. Its handoff defines fictional demo users `alex.author`, `riley.reviewer`, `sam.qa`; use its documented demo PINs only, entered by the presenter, without reading private environment values. A distinct reviewer is required before QA. Do not skip directly to QA after the author denial.

If the UI cannot show a denial but the API is working, pre-open the exact request in a local API client during preparation. Use `POST /api/approvals/{actual_approval_id}/sign`, `X-User: alex.author`, and body `{ "meaning": "approved", "pin": "<documented-demo-PIN>" }`. Expected HTTP 403/code `self_approval_forbidden` follows current A7 source but still requires execution evidence. Reviewer uses `meaning: reviewed`, then QA uses `meaning: approved`, each under their own identity. `GET /api/audit/verify` provides the backend verification result. If this fallback is used, show the actual response and disclose that this step uses the API client.

This is an operator fallback, not a claim that A11 executed or signed approvals. Never generate a human signature or validation execution result for the presenter.

## Reset between takes

1. Stop only the rehearsal processes started in the rehearsal terminal with Ctrl+C. Confirm their ports are no longer served by those processes.
2. For a clean backend state, choose a **new, previously unused** A11 database path such as `docs/.rehearsal-take-2.sqlite` in the setup command. Leave earlier SQLite files, WAL/SHM files, shared `var/` state and Compose volumes untouched.
3. Clear only TrialPilot rehearsal-origin local storage in the browser. Current A8 keys are `tp.identity` and `tp.lastDesignId`; a fresh browser profile is also acceptable. This does not reset backend records.
4. Restart on 8011/5184 with offline mode and the isolated path. Re-import the selected cached trial and recapture real ids. Click **Reset to baseline**, then ensure Home/Tele choices, supply, removed procedures and excluded sites match baseline.
5. Reset operations only through A6's documented interface after it is supplied. Never guess a reset endpoint or reuse stale intervention ids across databases.
6. A7 owns generated validation evidence. Reuse a dated verified package as a disclosed recording artifact or follow A7's clean execution instructions; do not edit evidence/signatures to make a take look fresh.

Do not commit `.rehearsal*.sqlite` files, local logs or recordings containing private data. Stage only the named A11 documentation paths.

## Offline and failure handling

Cached backend mode (`DEMO_OFFLINE=1`) differs from browser mock mode (`VITE_MOCK_API=1`). A successful mock UI rehearsal provides no proof of engine, compliance or real registry mapping. Keep its fictional-data badge and describe it accordingly.

If a cached import is missing, use only another verified fixture prepared by A4 or the script's documented-flow fallback. A real cached record may still have an assumed visit schedule. If any live step fails, use the matching [fallback narration](VIDEO_SCRIPT.md#in-segment-fallback-narration), display a clearly labelled documented flow or dated real recording, and continue at the original boundary.

**Backup video:** the planned path is `docs/assets/trialpilot-demo.mp4`; it does not exist at this draft. Once recorded, check duration, source commit, labels and audio offline. Keep it loaded in a local media player before judging. On total live failure, say “The live session is unavailable; this is a recording of the stated build,” then play the verified recording from its start. If the recording is unavailable, display the Markdown deck as a concept walkthrough and explicitly say the product demo is unavailable.

## Final lock

Reconcile every measured Devpost value against the named handoff. Verify source-sheet quotations and competitor references in A10's source index. Record pass/fail for each gate, actual click labels, the final commit, recording duration and known gaps in `handoffs/A11.md`. A11 does not enter review phase until the human says “review.”

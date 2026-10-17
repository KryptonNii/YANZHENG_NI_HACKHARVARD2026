# TrialPilot — 180-second video script

Delivered: [actual WebM](assets/trialpilot-demo.webm) · [captioned local player](assets/demo-player.html) · [English WebVTT](assets/trialpilot-demo.en.vtt). **180.000 seconds**, 1440 × 900, 25 fps, VP9, silent. There is no recorded voice-over; the text below is both the caption script and an optional presenter narration.

The recording uses actual UI actions against the real API on 8008/5181 with a fresh temporary database. Cached protocol transcription is labelled; operations and identities are fictional. Application code matches tested **e5c386b**; later changes only affect materials. See [release metadata](assets/release-data.json), [media verification](assets/media-manifest.json) and [complete runbook](DEMO_RUNBOOK.md).

Intervals have inclusive starts and exclusive ends, with no gaps or overlaps. The first 2.24 seconds of raw browser setup and the final tail were removed; no result or action was substituted. Controls/latency may vary during a live presentation.

| Time | Actual action | Caption / optional narration |
|---|---|---|
| 00:00–00:08 | Import home | TrialPilot compares trial choices with visible assumptions and evidence. This is a real local API demo. |
| 00:08–00:18 | Import BOREAS | Import BOREAS from cached ClinicalTrials.gov data. Registry facts and missing inputs stay distinct. |
| 00:18–00:31 | Use the registry protocol (cached extraction) | Review 19 protocol candidates with pages and quotations. This cached transcription is not measured live LLM accuracy. |
| 00:31–00:40 | Accept all remaining → Apply to design | Bulk acceptance is recorded as review activity. Applying the protocol saves a new design version; it does not establish clinical approval. |
| 00:40–00:50 | Open scenario simulator | Inspect cost, site hours, patient travel, duration and carbon. These ranges depend on model assumptions. |
| 00:50–01:02 | 50% remote monitoring → On-demand resupply | Change hypothetical monitoring and supply inputs. Screen results and the saved scenario remain bound to the same design version. |
| 01:02–01:12 | Enrollment forecast and drug supply | Forecast and supply expose their actual draw counts. Inspect stockout risk and warnings alongside modeled waste. |
| 01:12–01:24 | How is this calculated? | Open carbon provenance: formulas, activity inputs, direct and upstream factors, and explicit assumptions. Model precision is not empirical accuracy. |
| 01:24–01:34 | Save scenario → Save | Save the computed scenario and its version. A pending calculation cannot be saved as if it were current. |
| 01:34–01:43 | Submit for approval → Alex signature attempt | The real API blocks self-approval: authors cannot approve their own work. |
| 01:43–01:51 | Riley → Sign: reviewed | Riley demonstrates the independent reviewer role, binding a signature to the saved record hash. |
| 01:51–02:01 | Sam → Sign: approved | Sam demonstrates QA approval of this scenario. These fictional automated signatures are not human approval of the software or validation report. |
| 02:01–02:11 | Audit → Verify chain | Verify the current audit chain and inspect events. This prototype still needs production identity and security controls. |
| 02:11–02:20 | Command center → Start simulation | Open the 40-site synthetic feed. Its operational signals demonstrate software behavior, not real clinical activity. |
| 02:20–02:31 | Acknowledge → Plan intervention → Start intervention | Acknowledge overstock, assign an intervention and start it. The action and owner are recorded. |
| 02:31–02:42 | Advance 6 weeks | Advance six simulated weeks. Inspect treated and control changes, the effect interval and its assumptions; this does not prove causation. |
| 02:42–02:51 | Science | Engine/library gaps are +23.38% for CASPS and +22.75% for PRIMETIME, excluding drug supply. Module gaps remain. |
| 02:51–03:00 | Validation → Download evidence manifest | Tested code e5c386b: 576 passed, zero failed. Download the actual evidence. The report remains awaiting human QA approval. |

## Scientific and validation scope

Scientific source: [results.json](../science/out/results.json), parameter set **1249d0f0eed8**, seed **7**, **2,000 draws**, at **e5c386b**. CASPS engine/library P50 88,758.48 kg CO2e versus 71,938.8 (+23.38%); PRIMETIME 109,685.91 versus 89,360.2 (+22.75%). These exclude drug_supply. Paper arithmetic is separately +0.01%/−0.16%; old +5%/+7% engine claims are obsolete. No real-world coverage, cost accuracy or clinical savings is inferred.

Validation source: [20261017T041438Z](../validation/out/clean-clone/20261017T041438Z/summary.json), exact tested commit **e5c386b1fb0b6edf362bf5d37b97cc17066dfd07**. 576 passed, zero failed/errors/skipped, 32 requirements passed. The 48 frontend unit checks and separate 1/1 final-package browser check are separate counts. 114 package file hashes/downloads verified. The report remains **awaiting QA approval**; automated signatures are demo fixtures.

## Delivery limits and live fallback

Live LLM accuracy, human validation effort, actual human QA approval, Docker execution, public deployment and a video-upload URL remain unestablished. This video has not been published. The recording uses offline cached-data mode; physical network disconnection was not separately tested.

If the application fails during a live pitch, say the step failed and use this verified local recording. Do not substitute mock figures or historical passing counts. The recording omits optional comparison/concurrency and detailed country-week drilldown to fit three minutes; those are exercised in browser tests and described in the full runbook.

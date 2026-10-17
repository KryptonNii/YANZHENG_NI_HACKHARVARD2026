# TrialPilot — Devpost draft

**DRAFT — requires human review.** Prepared against tested code `e5c386b1fb0b6edf362bf5d37b97cc17066dfd07`. This file has not been submitted or published.

## Inspiration

Study-design choices affect cost, site workload, patient travel and timing. We wanted to make their assumptions and evidence easier to inspect, with carbon as an additional consequence. Historical research identifies procedures, staffing and monitoring as major cost drivers. The $19.0m pivotal-trial median is historical estimated direct cost from a 2015–2016 cohort, not our product's savings. [Original sources and qualifications](EVIDENCE.md).

## What it does

TrialPilot imports registry records, distinguishes facts from missing inputs, and presents protocol candidates with page/quote evidence for review. The simulator compares hypothetical activity choices across cost, site hours, patient travel, duration and carbon, with model ranges and provenance. Calculation, saving and comparison carry the design version; stale updates produce a conflict.

The command center shows completed-week site/country enrollment, alerts, interventions and qualified effect estimates from **synthetic feeds**. Saved scenario approvals reject self-approval and bind reviewer/QA demonstration signatures to record hashes. Audit verification and a downloadable validation package expose the actual execution and its scope.

The [180-second application recording](assets/trialpilot-demo.webm) uses the real local API, not UI mocks. Cached registry/protocol inputs, synthetic operations and fictional identities remain labelled. It is a silent recording with [English captions](assets/trialpilot-demo.en.vtt) and a [local player](assets/demo-player.html), not a human-narrated video.

## How we built it

Shared Pydantic contracts connect a Python activity-based engine, FastAPI/SQLite and React/TypeScript. Seeded sampling exposes uncertainty and assumptions; forecasts and supply report their own actual draw counts. The carbon method follows LCCT with a separately disclosed drug-supply extension. The validation toolkit links requirements, protocols, executed checks, traceability and evidence hashes. [Architecture](../README.md), [methods](model.md), [forecast/supply](model_forecast.md).

Optional live extraction uses the official Anthropic SDK and Messages API; `EXTRACT_MODEL` selects the model, with source default `claude-opus-5-5`. This is a configuration disclosure, not a verified live-provider run. The video uses a cached build-time transcription. Code and documents were assisted by OpenAI Codex. Original code/docs are MIT; data, fonts, provider services and dependencies retain separate terms. [Inventory](../THIRD_PARTY.md), [licenses and disclosure](STACK_AND_LICENSES.md).

## Challenges and accomplishments

Separating sourced facts, missing inputs and human-review candidates matters as much as rendering a number. We fixed version races so that the saved result corresponds to the screen, made unknown metrics explicit, retained real approval/audit controls and exposed package-specific counts.

| Check | Result and scope |
|---|---|
| Complete isolated execution | **576 passed, 0 failed/errors/skipped**, **32/32 requirements passed**, exact code `e5c386b`; [summary](../validation/out/clean-clone/20261017T041438Z/summary.json) |
| Frontend checks | Typecheck + production build passed; **48 unit tests** in preflight; **12 real-API browser tests** in executed evidence; a separate **1/1** final-package browser download check |
| Evidence downloads | **114/114** package files downloaded and hash-verified; generation-time audit chain intact across 12 entries; final post-packaging audit 14 |
| Cold compute | **147.8 ms median** from seven distinct seeds, `X-Cache: miss`, 2,000 forecast draws, server `X-Compute-Ms`; target <300 ms passed in this run |
| Earlier performance | Standalone **308.2 ms** missed the target; historical full run at `38e2073` had **664.1 ms**; preserved, not replaced by a pass |
| CASPS | Engine/library P50 **88,758.48 kg CO2e**, **+23.38%** vs published 71,938.8; P10–P90 64,601.50–123,510.08 |
| PRIMETIME | Engine/library P50 **109,685.91 kg CO2e**, **+22.75%** vs published 89,360.2; P10–P90 87,891.34–142,685.69 |
| Separate paper arithmetic | **+0.01% / −0.16%**; seed 7, 2,000 draws for engine comparisons, parameter set 1249d0f0eed8; [JSON](../science/out/results.json) |
| Extraction | Historical synthetic parser recovered **7/7 visits, 50/50 procedure items** on a generated protocol; **live LLM accuracy unmeasured**, per [A4](../handoffs/A4.md) |
| Defect experiment | **6/6 at d616645**, historical, unsigned and **not blind**; same author planted defects and wrote checks, per [A7](../handoffs/A7.md) |

The science comparison excludes `drug_supply`, counts direct/WTT once each and has substantial module gaps. PRIMETIME applies visits to all 1,962 rather than a 1,623 subgroup; hospital utilities, some sample activity and audits are absent. Both published totals lie in model ranges, which does not validate coverage or other metrics. Old +5%/+7% claims are obsolete.

The report remains **awaiting QA approval**. Demo signatures are automated fixtures, not human approvals. Human validation effort, real LLM accuracy and observed clinical/financial savings are unmeasured. Successful tests do not establish regulatory acceptance.

## What we learned

A reproducible calculation can still be misleading if boundaries are wrong. Versioning, source labels and explicit unknowns make disagreement inspectable. Packaging evidence, passing tests and obtaining human approval are distinct steps.

Evinova, SHC/iLCCT, Medidata and ValGenesis already cover related design, carbon, monitoring and validation functions. Our focus is an inspectable MIT implementation connecting them, not a first-of-kind or superiority claim. [Vendor sources](EVIDENCE.md).

## What's next

A permitted-data pilot with a sponsor and site team should calibrate workload/forecast estimates and measure live extraction quality and review effort against prospective criteria. Production identity/security, authorized connectors, independent QA, Docker/deployment verification and potential SMI mapping remain future work.

## Submission gaps

| Field | State |
|---|---|
| Public repository URL | Not supplied; no push performed |
| Deployment URL | Not established; Docker unavailable and container run unverified |
| Video upload URL | Local 180-second WebM exists; no upload/publish performed |
| Screenshots/deck | Actual [captures](assets/screenshots/), [12-slide PowerPoint](assets/trialpilot-deck.pptx) and [source](DECK.md) |
| Sponsor titles/rules | Mapping from supplied A11 brief; original sheets still unavailable |
| Human QA and timing | Awaiting human approval; effort unmeasured |

Keep these gaps explicit until resolved by a person with the required evidence and publishing authorization.

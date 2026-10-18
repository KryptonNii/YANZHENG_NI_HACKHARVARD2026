# TrialPilot — Devpost draft

**DRAFT — requires human review.** Prepared against tested code `8fca2d71cde979909c7a8535d43dc95b4f6c94c0`. This file has not been submitted or published.

## Inspiration

Study-design choices affect cost, site workload, patient travel and timing. We wanted to make their assumptions and evidence easier to inspect, with carbon as an additional consequence. Historical research identifies procedures, staffing and monitoring as major cost drivers. The $19.0m pivotal-trial median is historical estimated direct cost from a 2015–2016 cohort, not our product's savings. [Original sources and qualifications](EVIDENCE.md).

## What it does

TrialPilot imports registry records, distinguishes facts from missing inputs, and presents protocol candidates with page/quote evidence for review. The simulator compares hypothetical activity choices across cost, site hours, patient travel, duration and carbon, with model ranges and provenance. Calculation, saving and comparison carry the design version; stale updates produce a conflict.

The command center shows completed-week site/country enrollment, alerts, interventions and qualified effect estimates from **synthetic feeds**. Saved scenario approvals reject self-approval and bind reviewer/QA demonstration signatures to record hashes. Audit verification and a downloadable validation package expose the actual execution and its scope.

Claude can also query TrialPilot directly through an MCP server. Connected in Claude Desktop, it can answer questions like "Why is the BOREAS cost range so wide?": it calls `explain_metric` and finds that the biologic kit price, a market-price proxy, drives about 40% of the variance. The six tools are compute-only and read-only, so the agent can explore what-ifs and explain numbers but never saves, approves or signs; those steps stay with people in the web app. [Setup and example questions](../README.md#ask-claude-about-a-design-mcp-compute-only).

The [demo video](../README.md#demo-media) uses the real local API, not UI mocks. Cached registry/protocol inputs, synthetic operations and fictional identities remain labelled.

The project connects five Regeneron starter sheets rather than building one literally: Choose Your Timeline, One Screen to Rule Them All, Software Speedrun, How Extra Is Your Trial? and Trial by Design. The [sheet-by-sheet mapping](../README.md#regeneron-starter-sheets) lists what is implemented, what is measured and what is not done.

## How we built it

Shared Pydantic contracts connect a Python activity-based engine, FastAPI/SQLite and React/TypeScript. Seeded sampling exposes uncertainty and assumptions; forecasts and supply report their own actual draw counts. The carbon method follows LCCT with a separately disclosed drug-supply extension. The validation toolkit links requirements, protocols, executed checks, traceability and evidence hashes. [Architecture](../README.md), [methods](model.md), [forecast/supply](model_forecast.md).

Optional live extraction uses the official Anthropic SDK and Messages API; `EXTRACT_MODEL` selects the model. Live extraction accuracy has not been measured. The video uses a cached build-time transcription. We built TrialPilot by orchestrating AI coding agents against shared contracts and acceptance checks: Claude Code with Claude Opus 5.5 and Sonnet 5.5 for the coding agents, Cursor, and OpenAI Codex for documentation drafts and the editable deck. Each agent's hand-off is in [`handoffs/`](../handoffs/). Original code/docs are MIT; data, fonts, provider services and dependencies retain separate terms. [Inventory](../THIRD_PARTY.md), [licenses and disclosure](STACK_AND_LICENSES.md).

## Challenges and accomplishments

Separating sourced facts, missing inputs and human-review candidates matters as much as rendering a number. We fixed version races so that the saved result corresponds to the screen, made unknown metrics explicit, retained real approval/audit controls and exposed package-specific counts.

| Check | Result and scope |
|---|---|
| Complete isolated execution | **819 passed, 0 failed/errors/skipped**, **32/32 requirements passed**, exact code `8fca2d7`; [summary](evidence/clean-clone-20261018T061014Z/summary.json) |
| Frontend checks | Typecheck + production build passed; **155 unit tests** in preflight; **13 real-API browser tests** in executed evidence |
| Evidence downloads | **115/115** package files downloaded and hash-verified; audit chain intact across 14 entries |
| Cold compute | **143.3 ms median** from seven distinct seeds, `X-Cache: miss`, 2,000 forecast draws, server `X-Compute-Ms`; target <300 ms passed in this run |
| Earlier performance | Standalone **308.2 ms** missed the target; historical full run at `38e2073` had **664.1 ms**; preserved, not replaced by a pass |
| CASPS | Engine/library P50 **88,758.48 kg CO2e**, **+23.38%** vs published 71,938.8; P10–P90 64,601.50–123,510.08 |
| PRIMETIME | Engine/library P50 **109,685.91 kg CO2e**, **+22.75%** vs published 89,360.2; P10–P90 87,891.34–142,685.69 |
| Separate paper arithmetic | **+0.01% / −0.16%**; seed 7, 2,000 draws for engine comparisons, parameter set 1249d0f0eed8; [JSON](../science/out/results.json) |
| Command center vs withheld truth | **42/42** planted operating problems detected by their deadlines; **11/12** intervention verdicts match the simulator's withheld ground truth, including **3/3** coincidental improvements identified as coincidence. The miss is a true no-effect case reported as inconclusive. Three seeds, synthetic feeds; [evaluation.json](../data/fixtures/ops/evaluation.json), reproduced on current code |
| PeerMirror | BOREAS against **439** cached Phase 3 COPD registry peers: 17 outcomes vs peer median 6 (84th percentile), 24 countries vs 2 (93rd), 275 sites vs 34 (93rd). Descriptive position, not a quality verdict |
| Sponsor complexity trend | **27,969** industry Phase 2–3 trials, 2010–2024, observed ÷ expected for phase and MeSH disease category: Regeneron-led **2.4×** (95% CI 2.0–2.7), level with large-sponsor peers by 2022–24; registered outcome measures **2.9×** vs **1.5×**. Registry proxies, not quality judgments; [method](COMPLEXITY_TREND.md) |
| MCP tools | Real stdio session: all six tools listed as read-only; `compute_scenario` and `explain_metric` answered with ranges and drivers; [tests](../api/tests/test_mcp_server.py) |
| Extraction | Historical synthetic parser recovered **7/7 visits, 50/50 procedure items** on a generated protocol; **live LLM accuracy unmeasured**, per [A4](../handoffs/A4.md) |
| Defect experiment | **6/6 at d616645**, historical, unsigned and **not blind**; same author planted defects and wrote checks, per [A7](../handoffs/A7.md) |

The science comparison excludes `drug_supply`, counts direct/WTT once each and has substantial module gaps. PRIMETIME applies visits to all 1,962 rather than a 1,623 subgroup; hospital utilities, some sample activity and audits are absent. Both published totals lie in model ranges, which does not validate coverage or other metrics. Old +5%/+7% claims are obsolete.

The report remains **awaiting QA approval**. Demo signatures are automated fixtures, not human approvals. Human validation effort, real LLM accuracy and observed clinical/financial savings are unmeasured. Successful tests do not establish regulatory acceptance.

## What we learned

A reproducible calculation can still be misleading if boundaries are wrong. Versioning, source labels and explicit unknowns make disagreement inspectable. Packaging evidence, passing tests and obtaining human approval are distinct steps.

Evinova, SHC/iLCCT, Medidata and ValGenesis already cover related design, carbon, monitoring and validation functions. Our focus is an inspectable MIT implementation connecting them, not a first-of-kind or superiority claim. [Vendor sources](EVIDENCE.md).

## What's next

1. **Per-scenario assumption overrides.** A team should be able to replace a library value for one scenario, labelled, versioned and shown in provenance. The first candidate is its own investigational-product cost of goods in place of the biologic kit's market-price proxy, which drives about 40% of BOREAS cost variance.
2. **A permitted-data pilot** with a sponsor and site team: calibrate workload and forecast estimates, then measure interval coverage, live extraction quality and review effort against prospective criteria.
3. **Missing planning levers:** enrollment target, site count and activation speed, then programme-level probability of success and rNPV.
4. **Production readiness:** identity and security, authorized connectors, independent QA, production deployment with persistent storage, and potential SMI reporting mapping.

## Submission gaps

| Field | State |
|---|---|
| Public repository URL | https://github.com/KryptonNii/YANZHENG_NI_HACKHARVARD2026 (public, MIT) |
| Deployment URL | https://surround1ngkni-trialpilot.hf.space (Docker image on a Hugging Face Space; live registry import; storage resets on restart) |
| Video upload URL | Local 180-second WebM exists; no upload/publish performed |
| Screenshots/deck | Actual [captures](assets/screenshots/), [12-slide PowerPoint](../README.md#demo-media) and [source](DECK.md) |
| Sponsor titles/rules | Checked against the official starter kit and judging criteria; [mapping](../README.md#regeneron-starter-sheets) |
| Human QA and timing | Awaiting human approval; effort unmeasured |

Keep these gaps explicit until resolved by a person with the required evidence and publishing authorization.

# TrialPilot presentation

Exactly 12 slides including the title. The editable PowerPoint is [trialpilot-deck.pptx](assets/trialpilot-deck.pptx); the actual app recording is [trialpilot-demo.webm](assets/trialpilot-demo.webm). Product captures use the real local API, cached registry data, synthetic operations and fictional demo identities. Final code/report scope is recorded in [EVIDENCE.md](EVIDENCE.md).

## Slide 1 — TrialPilot

- Clinical trial choices with visible assumptions
- Planning connected to synthetic operations
- Software evidence available for human review

**Speaker note:** TrialPilot is an MIT-licensed hackathon prototype for inspecting operational consequences of study-design choices. Cost, site workload, patient travel and timeline come before carbon. We demonstrate local software behavior; no clinical outcomes, savings, production deployment or regulatory acceptance are claimed. [Build and scope](../README.md).

## Slide 2 — Decisions with real operational cost

- Procedures and site activity are major historical cost drivers
- Monitoring and supply choices change resource needs
- Start with workload and timing, then inspect carbon

**Speaker note:** The $19.0m figure is the historical median estimated direct cost per pivotal trial: 138 trials supporting 59 FDA approvals in 2015–2016. It is not a current invoice or TrialPilot saving. ASPE's 2014 report provides additional cost-driver context. Original Regeneron sheets were not supplied. [Moore et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC6248200/), [ASPE](https://aspe.hhs.gov/sites/default/files/migrated_legacy_files//44516/rpt_erg.pdf), [claim ledger](EVIDENCE.md).

## Slide 3 — Import, review, save the design

- Registry facts stay separate from missing inputs
- Protocol candidates expose page and quotation
- Apply reviewed rows to a new saved design version

**Speaker note:** The recording imports BOREAS NCT03930732 and uses a cached protocol transcription, not a measured live LLM extraction. Accept all remaining records bulk acceptance; it does not establish accuracy or clinical review. Empty weeks are rejected. Re-import preserves an already confirmed protocol unless the user explicitly requests replacement. The final regression also covers previously unseeded NOTUS NCT04456673. [Runbook](DEMO_RUNBOOK.md), [A4](../handoffs/A4.md).

## Slide 4 — Compare the consequences

- Cost, site hours, patient travel, duration and carbon
- 50% remote monitoring plus on-demand supply in this demo
- Calculation and saved result use the same design version

**Speaker note:** The choices are hypothetical operating inputs, not a clinical recommendation. We avoid changing patient visits or removing procedures without eligibility review. Read computed ranges as model output, never observed savings. The frontend disables saving during a pending calculation and saves the computed levers and explicit design version; stale design edits receive a visible conflict. [Frontend evidence](../handoffs/FRONTEND_FINAL.md).

## Slide 5 — Inspect every estimate

- Open formulas, inputs, cited parameters and assumptions
- Forecast and supply report requested and actual draw counts
- Missing data stays unknown; curve gaps remain gaps

**Speaker note:** P10/P50/P90 are conditional model quantiles without demonstrated real-world coverage. Forecast and supply have distinct sampling paths; use the displayed counts, not an assumed 2,000 everywhere. Recruitment, dropout, supply look-ahead and stockout limitations remain. [Engine method](model.md), [forecast and supply method](model_forecast.md), [sources](sources.md).

## Slide 6 — Act on a synthetic signal

- Sites and countries show completed-week enrollment
- Acknowledge overstock, assign an intervention, start it
- Advance six simulated weeks and inspect the effect interval

**Speaker note:** The 40-site demonstration combines synthetic EDC, CTMS, IRT, travel and courier feeds. The open week is excluded from completed-week curves; country bands sum site bands, and backup-site plans remain zero. A difference-in-differences estimate relies on its comparison group and assumptions. Its verdict is not a clinical causal conclusion. [Methods](model_forecast.md), [runbook](DEMO_RUNBOOK.md).

## Slide 7 — Bind review to the saved record

- Self-approval is rejected by the real API
- Reviewer then QA demo signatures bind the record hash
- Verify the current audit chain and inspect its entries

**Speaker note:** Alex, Riley and Sam are fictional identities exercised by automation. An Approved scenario in this video demonstrates workflow controls, not human QA approval of TrialPilot or the validation report. A role switcher is not production authentication; a hash chain does not prevent a privileged rewrite of the entire database. [Frontend checks](../handoffs/FRONTEND_FINAL.md), [validation scope](EVIDENCE.md).

## Slide 8 — Science: show the remaining gap

- CASPS engine P50: +23.38% versus the published total
- PRIMETIME engine P50: +22.75% versus the published total
- Both references lie inside model ranges; module gaps remain

**Speaker note:** Source is science/out/results.json, parameter set 1249d0f0eed8, seed 7, 2,000 draws. CASPS: published 71,938.8 kg; engine/library P10 64,601.50, P50 88,758.48, P90 123,510.08 kg CO2e. PRIMETIME: published 89,360.2 kg; engine/library 87,891.34 / 109,685.91 / 142,685.69 kg. Drug_supply is excluded from this comparison. Paper arithmetic separately gives +0.01% / −0.16%; library-factor ledger checks are different from full-engine checks. Direct and WTT components are counted once each. PRIMETIME visits cover all 1,962 rather than the 1,623 subgroup; hospital utilities, some sample activity and audits are missing. Old +5%/+7% results are obsolete. Carbon checks do not validate cost or forecast accuracy. [Generated results](../science/out/results.json), [published method, CC BY 4.0](https://pmc.ncbi.nlm.nih.gov/articles/PMC10823997/), [backend version](../handoffs/BACKEND_FINAL.md).

## Slide 9 — Evidence with its exact scope

- Read the package's actual tested commit and counts
- Keep failed checks and traceability gaps visible
- Download evidence; report remains awaiting QA approval

**Speaker note:** The Validation page reads the package metadata, not hardcoded historical counts. Inspect execution, failures, artifact hashes and QA state. Automated fixture signatures do not establish human sign-off. The historical 6/6 planted-defect experiment at d616645 was not blind and is not a result for this code. Human effort and live LLM accuracy remain unmeasured. [Final execution scope](EVIDENCE.md), [package path](../handoffs/BACKEND_FINAL.md).

## Slide 10 — Three challenge workflows

- Choose Your Timeline: scenario choices and forecasts
- One Screen to Rule Them All: alerts and interventions
- Software Speedrun: executed, downloadable evidence

**Speaker note:** Challenge titles come from the supplied A11 brief. The original sponsor sheets remain unavailable; this mapping does not verify their exact wording or submission rules. Each workflow shown has real API browser evidence, with synthetic and draft boundaries retained. [Missing sheet evidence](EVIDENCE.md#unavailable-sheet-evidence).

## Slide 11 — Existing tools, an inspectable prototype

- Evinova and SHC/iLCCT cover related design and carbon needs
- Medidata covers monitoring; ValGenesis covers validation
- Our focus is an MIT implementation connecting inspectable evidence

**Speaker note:** These are vendor descriptions, not a head-to-head evaluation or a claim of first-of-kind capability. SHC/iLCCT's calculator was developed with Pistoia participation. [Evinova](https://evinova.com/dds), [carbon offering](https://evinova.com/carbon), [Pistoia](https://pistoiaalliance.org/news/launches-sustainability-initiative/), [Medidata](https://www.medidata.com/en/clinical-trial-products/clinical-operations/rbqm/centralized-monitoring/), [ValGenesis](https://www.valgenesis.com/blog/valgenesis-vlms-5.0-next-gen-validation-lifecycle-management).

## Slide 12 — A bounded pilot, with open gaps

- Calibrate against permitted sponsor and site data
- Measure live extraction quality and human review effort
- Add production identity, deployment checks and independent QA

**Speaker note:** No deployment URL, Docker validation, real LLM accuracy, human review timing or human QA approval is established. Keep any final performance failure visible. A pilot needs prospective acceptance criteria and clinical review of allowed changes. SMI reporting mapping remains future work, not demonstrated conformity. [Limitations](../README.md#limitations), [SMI context](https://a.storyblok.com/f/109506/x/0245e71cdc/smi-ceo-cro-letter-_-february-2025.pdf), [final handoff](../handoffs/FRONTEND_FINAL.md).

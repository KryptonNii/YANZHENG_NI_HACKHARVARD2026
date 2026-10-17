# TrialPilot presentation

12 slides including the title, exactly three bullets and one speaker note each. Editable Markdown content, not a rendered PowerPoint. Product behavior remains a demo target until the runbook gates pass. Use actual captures with simulation/mock labels.

## Slide 1 — TrialPilot

- Clinical trial planning with inspectable assumptions
- Operational signals connected to a saved scenario
- Software evidence packaged for human review

**Speaker note:** TrialPilot is our MIT hackathon prototype. We want study teams to inspect the operational consequences and evidence behind a decision. Show only rehearsed paths. [Build status](../README.md).

## Slide 2 — Expensive operational decisions

- Historical pivotal trials had a $19.0m median estimated direct cost
- ASPE identified procedures, site staff and monitoring as major cost drivers
- The supplied Regeneron brief puts cost, workload and timing first

**Speaker note:** The cost is historical context from 2015–2016 approvals, not our product result. ASPE is a 2014 report. Regeneron's original sheets remain unavailable, so Tufts percentages and sheet quotations are pending. [Original cost study](https://pmc.ncbi.nlm.nih.gov/articles/PMC6248200/), [ASPE](https://aspe.hhs.gov/sites/default/files/migrated_legacy_files//44516/rpt_erg.pdf), [ledger](EVIDENCE.md).

## Slide 3 — A traceable decision

- Import a registry record and expose missing inputs
- Change eligible activities and compare modelled ranges
- Carry a selected scenario into approval and operations

**Speaker note:** Separate sourced facts, assumptions and extraction candidates requiring human review. A saved scenario should identify design and parameter versions. Present the current implementation as a prototype. [Architecture](../README.md#architecture).

## Slide 4 — Scenario simulator

- Show cost, site hours, patient travel and duration before carbon
- Demonstrate monitoring, eligible home visits and supply choices
- Explain a cost increase when the computed result supports it

**Speaker note:** Use a real UI capture after rehearsal. The planned 50% monitoring setting and three home visits are inputs, not results. Read computed values without inventing savings. Explain the activity behind an honest trade-off. [Runbook](DEMO_RUNBOOK.md).

## Slide 5 — Provenance and uncertainty

- P10, P50 and P90 describe the model under stated assumptions
- A metric exposes its formula, inputs and cited parameters
- Missing inputs remain visible for human review

**Speaker note:** Model quantiles have no established real-world coverage. Show one source and one assumption. Precision does not establish confidence. [Engine methods](model.md), [forecast methods](model_forecast.md), [contracts](../contracts/trialpilot_contracts/models.py).

## Slide 6 — Command center

- Synthetic feeds compare operations with a saved plan
- An overstock alert leads to an assigned intervention
- A comparison group qualifies the effect estimate

**Speaker note:** Keep the simulated label visible. Demonstrate a likely-worked case alongside coincidence or inconclusive output only when A6/A9 evidence supports it. Difference-in-differences depends on assumptions. Synthetic effects are not clinical findings. [Runbook](DEMO_RUNBOOK.md).

## Slide 7 — Approval and audit

- An author submits a specific scenario version
- Independent roles review and approve the bound record
- Verification checks the stored audit hash chain

**Speaker note:** Rehearse rejected self-approval and the actual reviewer/QA sequence. Until evidence exists these are required controls. A role switcher is not production authentication, and a hash chain is not certification. [A7 handoff](../handoffs/A7.md).

## Slide 8 — Published science check

- CASPS and PRIMETIME provide reference cases
- Compare module boundaries and exact generated totals
- Report remaining gaps and the calculation path

**Speaker note:** Show generated science output when available. Separate paper-factor arithmetic, A2 engine reproduction and library sensitivity. Results are pending at this draft. Carbon reproduction cannot validate cost or forecast models. [Published method](https://pmc.ncbi.nlm.nih.gov/articles/PMC10823997/), [A10 handoff](../handoffs/A10.md).

## Slide 9 — Validation evidence

- Requirements connect to risk, protocols and executed checks
- Defect detection uses the observed run result
- Human review and signatures complete approval

**Speaker note:** Show the actual package index, traceability and defect report or say results are pending. Packaging is distinct from execution. AI drafts carry “DRAFT — requires human review.” [A7 handoff](../handoffs/A7.md), [package instructions](../README.md#validation-package).

## Slide 10 — Regeneron challenge mapping

- Choose Your Timeline: design choices and forecast assumptions
- One Screen to Rule Them All: alerts and interventions
- Software Speedrun: reviewable validation evidence

**Speaker note:** Titles and mapping come from the supplied A11 brief. Confirm the original sheets before attribution. Each mapping depends on demonstrated module behavior. [Evidence gaps](EVIDENCE.md#unavailable-sheet-evidence).

## Slide 11 — Existing tools and our focus

- Evinova describes multi-metric design and carbon tools
- SHC/iLCCT's calculator and CTMS/RBQM cover related decisions
- Validation platforms already support execution and traceability

**Speaker note:** Pistoia participated in the calculator, Medidata describes monitoring, and ValGenesis describes iVal validation workflows. Our focus is an MIT implementation joining visible assumptions to synthetic operations and software evidence. No competitor testing or uniqueness claim. Opened sources: [Evinova suite](https://evinova.com/dds), [carbon](https://evinova.com/carbon), [Pistoia](https://pistoiaalliance.org/news/launches-sustainability-initiative/), [Medidata](https://www.medidata.com/en/clinical-trial-products/clinical-operations/rbqm/centralized-monitoring/), [ValGenesis](https://www.valgenesis.com/blog/valgenesis-vlms-5.0-next-gen-validation-lifecycle-management). A10 must add these to `docs/sources.md` before deck lock.

## Slide 12 — Limits and the next pilot

- Assumptions, synthetic feeds and demo identities limit deployment
- A pilot would compare estimates with site time and supply data
- Future work includes authorized connectors and SMI reporting mapping

**Speaker note:** Define a pilot with permitted data and prospective criteria. Do not promise savings or regulatory acceptance. SMI mapping is future work. [Limitations](../README.md#limitations), [SMI context](https://a.storyblok.com/f/109506/x/0245e71cdc/smi-ceo-cro-letter-_-february-2025.pdf).

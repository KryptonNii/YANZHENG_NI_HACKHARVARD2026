# TrialPilot — Devpost draft

**DRAFT — requires human review.** Confirm final feature claims against completed module handoffs. Do not submit unresolved placeholders. A11 does not publish or submit this draft.

## Inspiration

We wanted to help a study team inspect the consequences of changing a trial design: cost, site workload, timing and patient travel, with carbon as another metric. Historical research identifies procedures and site activity as cost drivers, while existing products already offer design and monitoring tools. We explored whether an open implementation could make a decision's assumptions and software evidence easier to inspect. [Context and sources](EVIDENCE.md).

## What it does

TrialPilot's intended workflow imports registry metadata or a human-reviewed protocol candidate, exposes missing fields and compares activity changes such as remote monitoring, eligible home visits or on-demand supply. Results carry ranges and provenance. A command center demonstrates alerts and interventions with synthetic operating feeds. Approval controls and a validation toolkit connect saved decisions with software-check records when those paths pass integration.

**Simulated feeds are synthetic.** Registry records and published references keep their source labels. Modelled differences are scenario estimates, not observed clinical or financial outcomes. A UI mock is a separate mode and cannot prove backend behavior.

## How we built it

The repository uses shared Pydantic contracts, a Python activity-based engine, FastAPI with SQLite, and a React/TypeScript interface. The design calls for seeded sampling and visible assumptions. Carbon uses the LCCT method with a separate drug-supply extension. The validation toolkit is intended to connect requirements, approved protocols and actual execution. [Architecture](../README.md), [stack/API/model/data disclosures and licences](STACK_AND_LICENSES.md), [direct dependencies](../THIRD_PARTY.md).

AI-assisted protocol extraction produces candidates for human confirmation. AI validation text is a draft. Human reviewers provide approvals and signatures. Disclose A4's actual extraction provider, model and terms from the final configuration; none is assumed here.

## Challenges

Registry records may omit the activity schedule, requiring a distinction between recorded facts and assumptions. A deterministic model can still mislead when parameters or boundaries are wrong. Demo identities, synthetic operations and the scope of a hash chain need clear disclosure.

Evinova already describes timeline, cost, patient-experience and carbon comparisons. Monitoring and validation vendors cover related workflows. We focus on inspectability and reproducibility without claiming these functions are new. [Opened competitor sources](EVIDENCE.md#opened-external-evidence).

## Accomplishments

The presentation package includes architecture, a timed walkthrough, a claim ledger and explicit unfinished-work disclosures. Product measurements require the owning teammate's handoff:

| Measurement | Submission value | Evidence required |
|---|---|---|
| Protocol extraction accuracy | [[NUMBER]]% | A4: scoring rule, numerator/denominator, corpus, model and evidence path |
| Planted defects detected | [[NUMBER]] | A7: detected/attempted, executed report and run identity |
| CASPS reproduction gap | [[NUMBER]]% | A10 + generated JSON: gap definition, boundaries and engine/reference path |
| PRIMETIME reproduction gap | [[NUMBER]]% | A10 + generated JSON with the same definitions |
| Compute latency P50 | [[NUMBER]] ms | A2/A5: hardware, draws, warm/cold and cache state, evidence |

The seeded-defect count is not a detection count. Reference arithmetic does not demonstrate integrated-engine reproduction. Never fill these values from mock constants, targets in the brief or inferred measurements.

## What we learned

An explanation needs to distinguish a sourced input, an assumption and a calculated result. Ranges need an interpretation. Test execution also needs a clear boundary from generated text and approval. These distinctions shaped our specification and demo narrative.

## What's next

Complete integration, independent review and evidence. Then define a pilot with a sponsor and site team using permitted data. Future work includes production identity controls, authorized system connectors, workload/forecast calibration and SMI reporting mapping. The current prototype does not establish those outcomes.

## Submission fields to complete

| Field | State |
|---|---|
| Repository URL | Human supplies public URL after final local integration |
| Demo URL | Local walkthrough documented; hosting not established |
| Video URL | Recording/upload pending, based on [03:00 script](VIDEO_SCRIPT.md) |
| Screenshots | Actual captures pending, retaining synthetic/mock labels |
| Track wording | Confirm original sheets; mapping currently from supplied brief |
| Attribution | Reconcile [THIRD_PARTY.md](../THIRD_PARTY.md) and [supplement](STACK_AND_LICENSES.md) with final manifests |

Remove this editing table and draft note only after resolution. If a measurement cannot be established, replace its claim with an explicit unmeasured limitation.

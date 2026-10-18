# Validation Plan — TrialPilot

## 1. Purpose and scope
This plan defines how TrialPilot is validated for its intended use: planning clinical-trial designs (cost, site workload, patient burden, timeline risk, carbon) and monitoring simulated trial operations, with an append-only audit trail, electronic signatures and role-based approvals. It follows the fictional company procedure SOP CSV-001 (`validation/company_sop.md`).

- Version under validation: git commit `8fca2d71cde979909c7a8535d43dc95b4f6c94c0`
- Requirements in scope: **32** (H 21, M 10, L 1; GxP-relevant 21)
- Areas: access (1), audit (3), configuration (2), engine (5), esign (3), import (2), operations (3), parameters (1), performance (1), records (2), science (1), validation (6), workflow (2)
- Out of scope: infrastructure qualification (IQ) of a production host, real patient data, integrations with real EDC/CTMS/IRT systems (TrialPilot ingests simulated feeds).

## 2. System category (judgement for a human decision)

DRAFT — requires human review

Suggested: **GAMP 5 software category 5 (custom application)** — TrialPilot is bespoke code written for this purpose (engine, API, UI), not configured off-the-shelf software. Libraries it builds on (FastAPI, React, NumPy, SQLite) would be treated as category 1 infrastructure software. Reference: ISPE GAMP® 5 Guide, 2nd edition (2022) — consult the guide; it is not reproduced here. *This category must be confirmed or changed by the validation lead and QA; tpv does not decide it.*

## 3. Approach (risk-based)
- Each URS item carries a risk (H/M/L) and a GxP flag with written rationale (`tpv risk`). Test depth follows SOP CSV-001 §4.
- Tests are automated (pytest per package, Playwright end-to-end) and tagged with the requirement ids they verify. `tpv protocol` lists them per requirement.
- The protocol is approved (reviewer → QA) **before** `tpv execute` runs it. Execution evidence is hashed in a manifest and signed `executed` by the executor.
- `tpv trace` links requirement → risk → tests → result → evidence hash and flags gaps; `tpv report` states the real counts; QA approves the report in the app.
- Planted defects (`validation/defects/`) check that this process actually catches problems; the detection count is reported as measured (`tpv defects-run`).

## 4. Deliverables

| # | Deliverable | Produced by | File in package |
|---|---|---|---|
| D1 | Validation plan | `tpv plan` | plan.md |
| D2 | User requirements (URS) | `validation/requirements.yaml` | urs.md |
| D3 | Risk assessment | `tpv risk` | risk_assessment.md |
| D4 | OQ test protocol (approved before execution) | `tpv protocol` | protocol.md |
| D5 | Executed evidence + manifest (signed 'executed') | `tpv execute` | evidence.md |
| D6 | Traceability matrix | `tpv trace` | trace_matrix.md |
| D7 | Validation summary report (QA approval) | `tpv report` | report.md |
| D8 | Change control (impact analysis, change record) | `tpv impact` | change_control.md |

## 5. Roles
Author (writes and executes), Reviewer (independent review), QA (final approval), Admin (no signing), Viewer (read-only). Matrix: `validation/ROLES.md`. Nobody approves their own work; enforced in code (`workflow.py`).

## 6. Acceptance criteria
Every requirement passes (all its tests pass), no requirement is left without a test, and every deviation is resolved or justified in the summary report before QA approval.

## 7. Use of AI
AI may draft prose (e.g. a plan introduction with `tpv plan --ai-draft`); every such paragraph is stamped "DRAFT — requires human review". Results, evidence, counts and signatures are produced by the test runners and humans only; AI actors cannot sign (enforced in code).

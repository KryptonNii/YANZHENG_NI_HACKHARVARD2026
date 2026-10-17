# SOP CSV-001 — Computerised System Validation (risk-based)

> **FICTIONAL DOCUMENT.** "Northwind Clinical Research" does not exist. This short procedure was written
> for the TrialPilot hackathon demo so that `tpv` has a company procedure to follow. It is not a real
> company SOP, not legal or regulatory advice, and does not reproduce any copyrighted guidance text.
> It is loosely shaped like a risk-based CSV procedure in the spirit of ISPE GAMP® 5 (2nd ed., 2022 —
> not reproduced here; see ispe.org) and FDA 21 CFR Part 11.

| Field | Value |
|---|---|
| Company | Northwind Clinical Research (fictional) |
| Document | SOP CSV-001, version 1 |
| Applies to | Software used to plan or run clinical trials |

## 1. Purpose
Ensure computerised systems are fit for their intended use, with effort proportional to risk, and that
records and signatures they hold are trustworthy.

## 2. Roles
| Role | Responsibility |
|---|---|
| Author | Writes requirements, protocols, records; executes tests. Cannot review or approve own work. |
| Reviewer | Independent technical review of protocols and records. |
| QA | Final approval of protocols, validation reports and change records. |
| Admin | Manages users and configuration. Does not sign records. |
| Viewer | Read-only access. |

## 3. Deliverables (per system)
| # | Deliverable | Approval |
|---|---|---|
| D1 | Validation plan (scope, system category judgement, deliverables) | Reviewer + QA |
| D2 | User requirements (URS) with risk and GxP relevance | Reviewer + QA |
| D3 | Risk assessment | Reviewer + QA |
| D4 | Test protocol (OQ) — **approved before execution** | Reviewer, then QA |
| D5 | Executed test evidence with integrity hashes, signed "executed" by the executor | — |
| D6 | Traceability matrix (requirement → risk → tests → result → evidence) | part of D7 |
| D7 | Validation summary report | QA |
| D8 | Change records for changes after release | Reviewer, then QA |

## 4. Risk scale
| Risk | Definition | Minimum test depth |
|---|---|---|
| **H** | Failure could corrupt a GxP record or signature, mislead a trial decision, or hide a change. | At least two tests, including one negative (misuse/failure) test; executed evidence required. |
| **M** | Failure degrades decision quality or usability; detectable by users. | At least one test; executed evidence required. |
| **L** | Failure is cosmetic or a performance inconvenience. | A test or a written justification. |

## 5. Rules
1. A test protocol must be approved (reviewer, then QA) **before** it is executed. Executing an unapproved
   protocol is a deviation.
2. Nobody reviews or approves their own work. One person signs at most one step of an approval.
3. Electronic signatures show the signer's printed name, date/time (UTC) and meaning, and are bound to
   the exact record version signed.
4. Every requirement must trace to at least one test; untested requirements are reported as deviations.
5. AI tools may draft prose; every AI-drafted paragraph is marked "DRAFT — requires human review".
   AI never produces results, evidence, counts or signatures.
6. Failures found during execution are recorded as deviations in the summary report; the report states
   the real counts.
7. Changes after release go through a change record with impact analysis and targeted re-testing.

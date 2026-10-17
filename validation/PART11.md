# 21 CFR Part 11 — control mapping (TrialPilot demo)

Source: eCFR, Title 21, Part 11 "Electronic Records; Electronic Signatures",
<https://www.ecfr.gov/current/title-21/chapter-I/subchapter-A/part-11> — sections below were opened and
checked on 2026-10-16 (eCFR "up to date as of 10/15/2026"). Summaries are our own wording, not quotes.
This is a hackathon prototype: the table states what is implemented **and what is not**. It is not a
compliance claim.

| Section (summary) | TrialPilot control | Where (code / test) | Status |
|---|---|---|---|
| **11.10(a)** Systems are validated, incl. ability to discern invalid or altered records | `tpv` validation package; hash chain + signature/record binding detect altered records | `validation/`, `audit.verify_chain`, `esign.signature_status` | Implemented for the demo |
| **11.10(b)** Accurate and complete copies of records for inspection | Audit trail CSV export of every entry; scenario CSV/PDF export (A5) | `GET /api/audit/export.csv`; URS-028 tests + defect D4 | Implemented |
| **11.10(d)** Access limited to authorised individuals | Role registry + permission matrix; mutations need an identity | `roles.py`, `validation/ROLES.md`, URS-023 | **Partial** — demo identity via `X-User` header, no login/SSO |
| **11.10(e)** Secure, computer-generated, time-stamped audit trail; changes don't obscure earlier entries | Append-only `audit` table (DB triggers abort UPDATE/DELETE), UTC timestamps, actor/role/reason, before/after hashes, SHA-256 chain | `audit.py`, `store.py`, URS-015/016/017 tests | Implemented |
| **11.10(f)** Operational checks enforce permitted sequencing | Approval steps in fixed order (409 `out_of_order`); protocol approved before execution (`tpv execute` refuses) | `workflow.py`, `execute.check_gate`, URS-022/024 | Implemented |
| **11.10(g)** Authority checks for signing, altering records, operations | Role per meaning (QA-only final approval), no self-approval, one signer per step, AI actors cannot sign | `workflow.py`, `esign.py`, URS-021/022/025 | Implemented |
| **11.10(i)** Training of people using the system | — | — | **Not implemented** (organisational) |
| **11.10(j)** Written accountability policy for e-signatures | Fictional SOP CSV-001 §5 | `validation/company_sop.md` | Demo only (fictional SOP) |
| **11.10(k)(2)** Change control of system documentation | `tpv impact` change records (reviewer → QA approval); git history | `impact.py`, URS-031 | Implemented for code/docs in git |
| **11.50(a)** Signed records show printed name, date/time, meaning | Signature manifestation: printed name, username, role, MEANING, UTC time, record id + hash | `esign.manifestation`, URS-019 | Implemented |
| **11.50(b)** Manifestation is part of any human-readable form | Shown in `/approvals` UI (A9), validation package pages, `tpv sign` output | `package.py` sign-off blocks, `/api/approvals/{id}` | Implemented (UI by A9) |
| **11.70** Signatures linked to their records so they can't be transferred | Signature stores the sha256 of the exact record; any change shows the signature invalid and blocks further signing | `records.py`, `esign.signature_status`, `workflow.sign_request` (409 `record_changed`), URS-020 | Implemented |
| **11.200(a)(1)** Non-biometric signatures use ≥ 2 components (e.g. ID code + password); each signing outside a continuous session uses all components | Every signature requires username + PIN re-entry | `esign.reauthenticate`, URS-018 | Implemented (demo PINs) |
| **11.200(a)(2)–(3)** Used only by genuine owner; misuse needs collaboration of ≥ 2 people | PINs stored as peppered argon2id hashes; 3 wrong PINs → 5-min lock, audited | `roles.py`, `esign.py` | **Partial** — demo PINs are published for judges; no per-user enrolment |
| **11.300** Controls for ID codes/passwords (uniqueness, periodic revision, loss management, transaction safeguards) | Unique usernames; lockout + audit of failed attempts | `esign.py` | **Partial** — no PIN ageing/revocation workflow |

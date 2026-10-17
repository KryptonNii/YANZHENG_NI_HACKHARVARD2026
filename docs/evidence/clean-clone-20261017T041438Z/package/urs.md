# User Requirements Specification — TrialPilot

Document `URS-TP` version 1 · source `validation/requirements.yaml` (sha256 `abb02d073a12cb38…`)

| ID | Area | Requirement | Risk | GxP |
|---|---|---|---|---|
| **URS-001** | import | The system imports a trial from ClinicalTrials.gov by NCT ID into a TrialDesign (sites, visits, enrollment, duration) and lists every field it could not obtain in missing_fields. | M | no |
| **URS-002** | import | Protocol-PDF extraction (LLM) returns candidate visits/procedures that a human must confirm before they enter a TrialDesign; nothing extracted is applied automatically. | H | yes |
| **URS-003** | parameters | Every parameter in the library has low/mid/high values and either a source (title, URL, year) or assumption=true with a written rationale; invalid parameters are rejected at load. | H | no |
| **URS-004** | engine | Every computed metric (cost, site staff hours, patient travel hours, CO2e, duration, drug waste) is reported as a P10/P50/P90 range with a unit; a missing input is reported as missing, never zeroed. | H | no |
| **URS-005** | engine | A computation is reproducible: the same design, levers, parameter-set version and seed give identical results. | H | yes |
| **URS-006** | engine | Each metric exposes its provenance: formula id, resolved inputs, parameter ids (with versions and sources) and assumptions used. | M | no |
| **URS-007** | engine | Design levers (remote monitoring share, home/remote visits, local labs, on-demand drug supply, removed procedures, excluded sites) change the affected metrics as documented in docs/model.md. | M | no |
| **URS-008** | engine | Carbon follows the Low Carbon Clinical Trials Group module framework (module ids as published); drug_supply is flagged as an extension beyond the published method. | M | no |
| **URS-009** | performance | Scenario compute with 2,000 Monte Carlo draws returns in under 300 ms at P50. | L | no |
| **URS-010** | records | Saved scenarios are versioned; a scenario that has been submitted for approval cannot be changed (an edit creates a new version). | H | yes |
| **URS-011** | operations | Simulated operational data is labelled simulated in data (simulated=true), API responses and the UI ("Simulated feed" badge). | H | yes |
| **URS-012** | operations | Alerts carry a severity, a plain-English summary, estimated impact as ranges (cost, CO2e, delay, site hours) and recommended actions; every alert action (acknowledge, plan, dismiss with reason) is audited. | M | no |
| **URS-013** | operations | The effect of an intervention is estimated with difference-in-differences against control sites and reported with a range and a verdict (likely worked / inconclusive / likely coincidence / no effect). | M | no |
| **URS-014** | science | The science check reproduces the published CASPS and PRIMETIME trial footprints (BMJ Open 2024) and reports the % difference per module against the published values. | M | no |
| **URS-015** | audit | The audit trail records every data-changing action with actor, role, UTC timestamp, action, object, before/after record hash and reason. | H | yes |
| **URS-016** | audit | The audit trail is append-only: the database rejects UPDATE and DELETE on audit entries and signatures, and no application code path updates or deletes them. | H | yes |
| **URS-017** | audit | The audit trail is tamper-evident: a SHA-256 hash chain links every entry and chain verification reports the first altered or missing entry. | H | yes |
| **URS-018** | esign | Signing requires re-authentication with the signer's PIN (stored only as a peppered argon2 hash); a wrong PIN is rejected, three consecutive failures lock signing for 5 minutes, and failures and lockouts are audited. | H | yes |
| **URS-019** | esign | A signature records signer, printed name, UTC date/time and meaning, is bound to the hash of the exact record signed, and its manifestation is shown with the record and in exports (21 CFR 11.50). | H | yes |
| **URS-020** | esign | If a signed record changes afterwards, its signatures are shown as invalid and the record cannot be signed further without resubmission. | H | yes |
| **URS-021** | workflow | The author of a record can never review, approve or reject their own record (segregation of duties). | H | yes |
| **URS-022** | workflow | Approval steps are signed in the required order for each record type (e.g. reviewed then approved), one person signs at most one step, and only QA gives the final approval. | H | yes |
| **URS-023** | access | Permissions follow the role matrix in validation/ROLES.md; a user's role comes from the user registry, never from the request, and mutations without an identity are rejected. | H | yes |
| **URS-024** | validation | A test protocol must be approved (exact version) before tpv executes it; tpv refuses otherwise and says why. | H | yes |
| **URS-025** | validation | AI may draft prose but never writes results, evidence, counts or signatures; AI-drafted text is stamped "DRAFT — requires human review" and AI actors cannot sign. | H | yes |
| **URS-026** | validation | Test execution evidence is captured with a manifest listing the sha256 of every evidence file, UTC timestamps, the executor and the git commit, and is signed "executed" by the executor. | H | yes |
| **URS-027** | validation | The traceability matrix links every requirement to its risk, tests, results and evidence hashes, and flags requirements with no test and tests with no requirement. | H | yes |
| **URS-028** | records | Exports (audit trail CSV, scenario CSV) contain every row of the underlying data, none dropped. | H | yes |
| **URS-029** | configuration | With DEMO_OFFLINE=1 the system makes no external network calls, uses cached fixtures, and reports offline=true on /api/health; the documented default is DEMO_OFFLINE=0. | M | no |
| **URS-030** | configuration | Secrets (API keys, the PIN pepper) come only from the environment / .env, which is never committed; .env.example lists names only. | M | yes |
| **URS-031** | validation | For a code change, change control lists the changed files, the affected requirements (via the component map) and the tests to rerun, and drafts a change record that a human completes and that is approved reviewer → QA. | M | yes |
| **URS-032** | validation | The validation summary report states the real counts from the signed execution (tests, requirement results, deviations) and shows "awaiting QA approval" until QA signs it; QA's signature is invalidated if the report changes. | H | yes |

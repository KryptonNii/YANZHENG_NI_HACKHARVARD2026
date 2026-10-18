# TrialPilot

**Compare clinical trial designs across cost, site workload, patient travel and timeline risk, with carbon as an additional metric and evidence behind each estimate.**

TrialPilot is an MIT-licensed hackathon prototype connecting scenario planning, an operations command center and software-validation evidence.

**Verified code:** clean-clone run at `e5c386b1fb0b6edf362bf5d37b97cc17066dfd07`: **576 passed, 0 failed/errors/skipped**, **32/32 requirements passed**, and **114 package files downloaded and hash-verified**. Typecheck, production build and all 48 frontend unit tests passed separately in preflight. The package remains **awaiting QA approval**; signatures are automated fictional demos, not human approval. [Full summary](docs/evidence/clean-clone-20261017T041438Z/summary.json) · [scope and handoff](handoffs/FRONTEND_FINAL.md). Later documentation/media commits do not change this tested code.

**Simulated feeds are synthetic.** Registry records and published reference values are sourced real data. Assumed visit schedules, operating events and UI mock results must retain their assumption, simulated or mock labels.

## Demo media

The demo video and slide deck are linked from the Devpost submission. Video and deck binaries are kept out of Git so a fresh clone stays small.
<!-- Add the public video URL and deck URL here once uploaded. -->

[Slide outline and speaker notes](docs/DECK.md) · [video script](docs/VIDEO_SCRIPT.md) · [English captions](docs/assets/trialpilot-demo.en.vtt) · [media manifest](docs/assets/media-manifest.json)

The original 180-second recording uses the real API on an isolated temporary database; no UI mock or invented result is used. The media manifest records its duration, hashes, source commits and inspection results.

![Scenario simulator: hypothetical monitoring and supply choices](docs/assets/screenshots/06-simulator-scenario.png)

[Protocol review](docs/assets/screenshots/03-protocol-review.png) · [Provenance](docs/assets/screenshots/08-provenance.png) · [Approval demo](docs/assets/screenshots/10-demo-approved.png) · [Synthetic command center](docs/assets/screenshots/12-command.png) · [Validation package](docs/assets/screenshots/16-validation.png)

## Why these decisions matter

These historical figures explain the levers. They are context, not TrialPilot savings or current price estimates.

| Bottleneck | Opened evidence | Interpretation |
|---|---|---|
| Procedures and site work | ASPE's 2014 report lists procedures **15–22%**, administrative staff **11–29%**, monitoring **9–14%**, site retention **9–16%**, and central laboratories **4–12%** across phases. [Report, PDF p. 34](https://aspe.hhs.gov/sites/default/files/migrated_legacy_files//44516/rpt_erg.pdf) | The detailed discussion excludes site overhead and sponsor monitoring. These ranges span phases and are not additive uncertainty bounds. |
| Pivotal trial expense | A 2018 study estimated a **$19.0m** median direct cost per pivotal trial among **138 trials** supporting **59 FDA approvals in 2015–2016**. [Original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC6248200/) | Historical modelled cost per trial, not total drug-development cost. |
| Study duration | FDA gives Phase 1 **several months**, Phase 2 **several months to 2 years**, and Phase 3 **1–4 years**. [FDA](https://www.fda.gov/patients/drug-development-process/step-3-clinical-research) | Educational ranges, not a forecast for the imported study. |
| Drug supply waste | Clinical Trials Arena reported an industry estimate of **60–70% clinical-trial IMP waste** on May 28, 2025. [Article](https://www.clinicaltrialsarena.com/news/mapping-out-opportunities-to-reduce-emissions-in-clinical-trials/) | Attributed conference estimate in coverage of a Genentech presentation, not a measured baseline for our trial. |

The figures above come from independent studies and FDA, not from Regeneron's starter sheets. See the [claim ledger](docs/EVIDENCE.md).

## Regeneron starter sheets

Regeneron's judging guidance says not to build a starter sheet literally. TrialPilot connects several sheets into one decision loop: review a design, compare the consequences of a choice, act on an operating signal, then check whether the action did what was predicted. The sheets also describe the starting problem: cost, enrollment and timeline models live in separate spreadsheets, so "each 'what if' takes days" (*Choose Your Timeline*).

| Starter sheet | What TrialPilot implements | Measured evidence | Not done |
|---|---|---|---|
| **Choose Your Timeline** (trial ops scenario simulator) | One activity model links visits and procedures to cost, site hours, patient travel, duration and carbon. Seeded Monte Carlo gives P10/P50/P90 ranges; scenarios are compared side by side, and advice uses paired per-draw differences. "Calculation details" ranks each metric's top five parameters by share of variance. | Engine and API test suites; [method](docs/model.md), [forecast and supply](docs/model_forecast.md), [advice method](docs/DECISION_METHOD.md) | Program-level Phase 1→3 chain and rNPV; one-at-a-time low/high swings |
| **One Screen to Rule Them All** (control tower) | A synthetic 40-site trial with EDC, CTMS, IRT, travel and courier feeds; study → country → site view; alerts; actions ranked by predicted net value; difference-in-differences follow-up compared with the saved prediction. | **42/42** planted problems detected by their deadlines; **11/12** intervention verdicts match withheld simulator truth, including **3/3** coincidental improvements identified as coincidence. The miss is a true no-effect case reported as inconclusive. Three seeds; [evaluation.json](data/fixtures/ops/evaluation.json), reproduced on current code with `python -m trialpilot_api.ops.evaluate` | Connectors to real systems; validation on real study data |
| **Software Speedrun, Any%** (GxP CSV) | `tpv` produces a plan, URS, risk assessment, protocols, executed evidence, trace matrix, Part 11 mapping and summary report. Self-approval and out-of-order execution are refused. | **576** passed, **32/32** requirements, **114/114** package files hash-verified at `e5c386b` ([summary](docs/evidence/clean-clone-20261017T041438Z/summary.json), [report](docs/evidence/clean-clone-20261017T041438Z/package/report.md), [trace matrix](docs/evidence/clean-clone-20261017T041438Z/package/trace_matrix.md)); historical planted defects **6/6**, not blind | Manual baseline timing for the 10× claim (the `tpv effort` stopwatch exists but has not been run); other teams' projects; human QA approval |
| **How Extra Is Your Trial?** (protocol complexity) | PeerMirror compares a trial with cached ClinicalTrials.gov records of the same phase and condition. The schedule of activities then drives cost and burden estimates. | BOREAS against **439** Phase 3 COPD peers: **17** outcomes vs peer median **6** (84th percentile), **24** countries vs **2** (93rd), **275** sites vs **34** (93rd). [Sponsor trend](docs/COMPLEXITY_TREND.md) over **27,969** industry Phase 2–3 trials: Regeneron-led trials sit at **2.4×** expected composite complexity (95% CI 2.0–2.7), level with large-sponsor peers by 2022–24; registered outcome measures **2.9×** vs **1.5×** for those peers | PeerMirror covers one disease and phase cohort; no link to duration or termination; schedule reconstruction accuracy against posted protocols |
| **Trial by Design** (protocol as data) | Protocol PDF candidates carry page and verbatim quote, need human acceptance, and are saved as a versioned design. | Synthetic parser fixture: **7/7** visits, **50/50** procedure items; live LLM accuracy not measured | USDM v4 or ICH M11 export |

![Registered trial complexity vs. expectation, 2010–2024](docs/complexity/complexity_trend.png)

The sponsor trend uses observed ÷ expected, with expected = the industry median for the same phase and MeSH disease category, as the sheet recommends; ratios are questions for a design team, not quality judgments. [Method, tables and limits](docs/COMPLEXITY_TREND.md).

The *One Screen to Rule Them All* sheet cites Tufts CSDD: about 11% of sites never enroll a patient and 37% under-enroll. The synthetic command center is built around that kind of early site-level signal.

**Mentor guidance applied.** Only public registry data and synthetic feeds are used; no patient data. Every displayed value carries its source or an assumption label, and changes are attributable in the audit chain (ICH E6(R3) traceability). Consequential steps need a human: protocol candidates are accepted one by one, and scenario approval requires a different reviewer and QA identity. For the optional LLM extraction path, indirect prompt injection from a protocol PDF is the main risk (OWASP LLM01). The design limits it: the model returns schema-constrained candidates only and has no tools that act; each quote is checked verbatim against the page text; nothing reaches a design until a person accepts it, and the acceptance is logged. TrialPilot is a planning tool that does not create or change trial data. On a risk-based assurance scale, it therefore sits below systems that affect patient safety or data integrity.

## Architecture

Implemented module boundaries. Dashed feed inputs represent synthetic demo events; production connectors remain future work.

```mermaid
flowchart LR
    Registry[ClinicalTrials.gov and cached records] --> Import[Importers and human review]
    PDF[Protocol PDF candidates] --> Import
    Import --> API[FastAPI API]
    UI[React UI] <--> API
    API --> Engine[Pure Python scenario engine]
    Params[Versioned parameters and sources] --> Engine
    API <--> DB[(SQLite designs and scenarios)]
    Feeds[Synthetic EDC CTMS IRT travel courier feeds] -.-> Ops[Alerts and intervention estimates]
    Ops <--> API
    API --> Audit[Audit chain and approval workflow]
    Tests[Demo-approved protocols and executed evidence] --> Package[tpv validation package]
    Audit --> Package
    Published[Published CASPS and PRIMETIME references] --> Science[Science checks]
    Engine --> Science
    Science --> API
```

| Directory | Responsibility |
|---|---|
| `contracts/` | Pydantic contracts, parameter schema, JSON Schema and TypeScript |
| `engine/` | Activity calculations, uncertainty, forecast and supply |
| `api/` | Persistence, importers, operations, compliance and HTTP/SSE |
| `web/` | Scenario, command, approval, audit and science views |
| `validation/` | `tpv`, requirements, protocols, evidence and traceability |
| `science/` | Published footprint fixtures and reproduction outputs |
| `data/` | Parameters, cached registry responses and synthetic fixtures |
| `docs/` | Methods, sources and the presentation package |

## Quick start

On Windows, double-click `sysup.cmd` to start the API and web app in live mode at
[http://127.0.0.1:5181](http://127.0.0.1:5181). It uses the prepared local dependencies,
loads `.env`, disables offline/mock mode and sample-design seeding, and defaults to Claude
Sonnet 5.5 for protocol extraction. Each launch forcibly stops any processes listening
on API **8008** and web **5181**, including healthy services, then starts fresh.
See [live setup and logs](docs/LIVE_RUNBOOK.md).

The verified local route uses API **8008**, UI **5181**, cached records and an independent OS temporary database. Follow the complete [PowerShell setup and walkthrough](docs/DEMO_RUNBOOK.md). Dependencies must already be prepared; the recorded run used locked pnpm **9.15.9** and Edge. Initial installation can require a network.

```powershell
corepack pnpm@9.15.9 --dir web typecheck
corepack pnpm@9.15.9 --dir web build
corepack pnpm@9.15.9 --dir web test
```

The root Makefile also supports `make install` and `make dev` in a configured Bash environment. Docker configuration exists, but Docker was unavailable: **container build/run and deployment are not verified**, and no public deployment URL is claimed. Do not replace that gap with a successful local Vite run.

## Demo walkthrough

Navigation: **Trials** (import) · **Analysis** (scenario simulator) · **Compare** · **Operations** (command center) · **Approvals** · **Audit** · **Validation** · **Models** (science checks) · **Methods**. Screenshots above predate these labels.

1. On **Trials**, import BOREAS **NCT03930732**; distinguish registry facts and **Pending inputs**. Choose **Extract registry protocol**, review page/quotation candidates and **Apply to design** after acceptance. Bulk acceptance is not measured extraction accuracy.
2. **Scenario analysis →** opens **Analysis**. Set **Monitoring visits done remotely** to 50% and choose **On-demand resupply**. These are hypothetical inputs, not clinical advice; this walkthrough does not change visits or remove procedures.
3. Read cost, site hours, patient travel, duration and carbon ranges. Inspect forecast/supply requested and actual draws. Open **Calculation details** for the formula, inputs, parameters and top variance drivers.
4. **Save scenario**, then **Submit for approval**. On **Approvals**, Alex cannot self-approve; Riley reviews and Sam approves with fictional demo PINs (**Sign this record** → PIN → **Sign**). These controls do not establish human QA approval.
5. **Audit → Verify chain**. Open **Operations** (`/command/demo-40`), **Start** the synthetic feed, acknowledge overstock, plan/start an intervention, then **Advance 6 weeks** and inspect the qualified effect.
6. **Models** exposes module gaps. **Validation** shows the package's exact commit, counts, failures and QA state; download its evidence manifest. Optional comparison and concurrency steps appear in the [runbook](docs/DEMO_RUNBOOK.md).

`VITE_MOCK_API=1` is a separate fictional UI mode and cannot establish API, engine or compliance behavior.

## Ask Claude about a design (MCP, compute-only)

TrialPilot includes an MCP server, so Claude Desktop or Claude Code can query the same API the web app uses. It exposes six tools, all annotated read-only: `list_designs`, `list_scenarios`, `compute_scenario`, `compare_scenarios`, `explain_metric` and `get_parameter`. Claude can explore what-ifs and explain any number. No tool saves, submits, approves or signs anything: saving a scenario and every signature stay with a person in the web app. Results come back as P10/P50/P90 ranges with units, and `null` means unknown.

**Connect Claude Desktop.** Open Settings → Developer → Edit Config, add the server to `claude_desktop_config.json`, then restart Claude Desktop:

```json
{
  "mcpServers": {
    "trialpilot": {
      "command": "C:\\path\\to\\YANZHENG_NI_HACKHARVARD2026\\api\\.venv\\Scripts\\python.exe",
      "args": ["-m", "trialpilot_api.mcp_server"],
      "env": { "TP_MCP_API_URL": "http://127.0.0.1:8008" }
    }
  }
}
```

On macOS or Linux, use `api/.venv/bin/python`. With `TP_MCP_API_URL`, Claude sees the designs and scenarios of the API started by `sysup.cmd`. Without it, the server runs the API in-process on the local database, which seeds the four fixture trials. For Claude Code, run `claude mcp add trialpilot -- <that python> -m trialpilot_api.mcp_server`.

**Questions to try:**

1. *List the TrialPilot designs. For BOREAS, compute cost, site staff hours and CO2e with half of the monitoring visits done remotely, and compare them with no changes. Give P10/P50/P90.*
2. *Why is the BOREAS cost range so wide? Explain cost_usd: which parameters drive its variance, and where does the top one come from?* On current code the answer is the biologic kit price, a Medicare market-price proxy that explains about 40% of the variance. That is why per-scenario overrides lead the roadmap below.
3. *Move visits 4, 5 and 6 to home nursing and analyse half of the samples locally. How do patient travel hours and site staff hours change, and what warnings does the engine raise?*

Checked on October 17, 2026 with a real stdio session against a temporary database: the server listed all six tools as read-only, `list_designs` returned the seeded BOREAS design, and `compute_scenario` and `explain_metric` answered with ranges and drivers. `api/tests/test_mcp_server.py` covers the tools.

## Method and uncertainty

The design reuses activity inputs for cost, site time, patient travel and emissions. Carbon uses activity multiplied by emission factor under the LCCT method, limited to trial-specific activities beyond routine care. [Griffiths et al., 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC10823997/).

The engine uses seeded triangular sampling and P10/P50/P90 outputs; the science reproduction uses 2,000 draws. Forecast and supply report their own requested and actual counts. These are model quantiles conditional on assumptions, without demonstrated real-world coverage. Consult the published [engine methods](docs/model.md). The [forecast/supply methods](docs/model_forecast.md) document additional limits.

Module ids: `setup`, `trial_management`, `meetings_travel`, `intervention`, `data_collection`, `supplies_equipment`, `patient_assessments`, `samples`, `laboratory`, `closeout`. `drug_supply` is an **extension beyond the published method** and must be separated from like-for-like reproduction. Missing inputs need a visible assumption or warning. Forecasts are planning estimates.

## Science check

Generated output at `e5c386b`, parameter set **1249d0f0eed8**, seed **7**, **2,000 draws**. All numbers below are kg CO2e; percentages use unrounded published references.

| Trial | Published | Paper arithmetic | Engine + library P10 / P50 / P90 | Engine P50 gap |
|---|---:|---:|---:|---:|
| CASPS | 71,938.8 | 71,943.18 (+0.01%) | 64,601.50 / 88,758.48 / 123,510.08 | **+23.38%** |
| PRIMETIME | 89,360.2 | 89,221.19 (−0.16%) | 87,891.34 / 109,685.91 / 142,685.69 | **+22.75%** |

[Generated JSON](science/out/results.json) · [published method, CC BY 4.0](https://pmc.ncbi.nlm.nih.gov/articles/PMC10823997/) · [backend explanation](handoffs/BACKEND_FINAL.md). Both references lie inside engine ranges; that is not proof of real-world coverage. Paper arithmetic, library-factor ledgers and full-engine structural checks are separate. Direct and WTT factors are counted once each. The old **+5%/+7%** engine claims are obsolete.

The comparison excludes the `drug_supply` extension. PRIMETIME visits cover all 1,962 rather than the 1,623 subgroup; hospital utilities and some sample/audit activity are absent, and assumed monitoring/initiation/closeout activity differs. Offsetting module differences can conceal structural gaps. Carbon reproduction does not validate cost, workload, forecast or intervention accuracy.

Cold compute in this complete run: **median 147.8 ms**, seven distinct seeds 200–206, every response `X-Cache: miss`, 2,000 requested forecast draws, measured by `X-Compute-Ms`; unchanged target <300 ms passed. It is server compute timing, not browser interaction latency. Earlier standalone median **308.2 ms** missed the target; the historical `38e2073` full run recorded **664.1 ms** and failed. These records are preserved, not rewritten. [Final summary](docs/evidence/clean-clone-20261017T041438Z/summary.json), [earlier cold observation](docs/evidence/backend-20261017T041106Z-cold/benchmark.json).

## Validation package

[Exact tested execution](docs/evidence/clean-clone-20261017T041438Z/summary.json) · [package index](docs/evidence/clean-clone-20261017T041438Z/package/index.md) · [summary report](docs/evidence/clean-clone-20261017T041438Z/package/report.md) · [trace matrix](docs/evidence/clean-clone-20261017T041438Z/package/trace_matrix.md) · [download/hash checks](docs/evidence/clean-clone-20261017T041438Z/package-downloads.json).

[`docs/evidence/`](docs/evidence/) holds an unmodified copy of the package's text deliverables and run summaries; screenshots, logs and the ZIP stay local. `tpv` regenerates the full package.

The complete isolated run has **576 passed, 0 failed/errors/skipped**, **32/32 traced requirements passed**, no untested requirements and no evidence-integrity problems. All 114 package files were downloaded and hash-verified; the package audit snapshot is intact across 12 entries (14 in the final post-packaging audit). The 12-test E2E suite ran before package generation and checked the honest missing-package state; a separate 1/1 browser check then verified this final package and downloaded Markdown/PNG/ZIP hashes. Frontend preflight separately ran 48 unit tests plus typecheck/build; these are not silently added to the 576 executed-protocol count.

The report remains **awaiting QA approval**. All clean-clone signature identities are automated demo fixtures; AI text stays **DRAFT — requires human review**. Packaging and test success do not establish human approval or regulatory acceptance. Human validation effort and live LLM accuracy are **not measured**.

The [historical defect experiment](validation/defects/LAST_RUN.json) detected **6/6 at d616645**; it was **not blind**, because the same author planted defects and wrote checks. It is unsigned historical evidence, not a current-code detection result. The older 507/3 result belongs only to `38e2073`; the validation UI always reads its loaded package's own counts.

## Frameworks, libraries, APIs, models and datasets

The [current complete direct-dependency list](THIRD_PARTY.md) is maintained by A1 from manifests and installed metadata. It identifies React, React DOM, React Router, Recharts, Vite, TypeScript, Tailwind, font/mapping packages, FastAPI, Pydantic, NumPy, SQLModel, SSE, PDF tooling and development tools individually. The [stack and licence supplement](docs/STACK_AND_LICENSES.md) covers runtime, API, model and dataset disclosures and additional licence checks. The final backend license inventory check found 0 items to review; container notices still need verification when a container is built. The project's MIT licence does not relicense dependencies or data.

The [Devpost draft](docs/DEVPOST.md) records measurements with their source and conditions: A4's synthetic parser recovered 7/7 visits and 50/50 procedure items, while live-LLM extraction accuracy and human validation effort remain unmeasured.

**AI-assisted development.** TrialPilot was built by orchestrating AI coding agents. Module ownership, shared contracts and acceptance checks were defined first, and each agent's hand-off is in [`handoffs/`](handoffs/). Tools used: Claude Code with Claude Opus 5.5 and Claude Sonnet 5.5 for coding agents (34 of the first 80 commits carry a Claude author or co-author trailer), Cursor (7 of those commits), and OpenAI Codex for documentation drafts and the editable deck. Optional live protocol extraction calls the Anthropic Messages API; `EXTRACT_MODEL` selects the model.

## Limitations

- Registry records can omit schedules. Assumed visits and extracted candidates need human confirmation.
- Parameter quality and boundaries limit results. Carbon does not represent every environmental impact.
- Operating feeds are synthetic. Authorized production connectors remain future work unless separately evidenced.
- Difference-in-differences depends on comparison-group assumptions and can be confounded. Synthetic effects are not clinical findings.
- Demo identity headers do not provide production authentication. Hash chaining detects inconsistencies relative to trusted evidence but cannot prevent a privileged rewrite of a database and its whole chain.
- Prototype controls and generated documents do not establish regulatory acceptance. Security, deployment, clinical appropriateness and QA need separate assessment.
- Live LLM quality, human review timing, human QA approval, production deployment and Docker execution remain open gaps.

## Roadmap

1. **Per-scenario assumption overrides.** Let a team replace a library value for one scenario, labelled, versioned and shown in provenance. The first candidate is a sponsor's own investigational-product cost of goods in place of the biologic kit's market-price proxy, which drives about 40% of BOREAS cost variance.
2. **A permitted-data pilot.** Calibrate workload and forecast estimates against completed studies, then measure interval coverage, live extraction accuracy and human review effort.
3. **Planning levers the model lacks.** Enrollment target, site count and activation speed, then programme-level probability of success and rNPV.
4. **Production readiness.** Production identity, authorized system connectors, Docker and deployment verification, and independent QA.

## Presentation package

[12-slide deck](docs/DECK.md) · [180-second script](docs/VIDEO_SCRIPT.md) · [Devpost draft](docs/DEVPOST.md) · [15 judge questions](docs/JUDGE_QA.md) · [demo runbook](docs/DEMO_RUNBOOK.md) · [claim ledger](docs/EVIDENCE.md)

## Licence

Original TrialPilot code and documentation use the [MIT licence](LICENSE). Source publications, APIs, datasets, fonts and dependencies retain their own terms. See [THIRD_PARTY.md](THIRD_PARTY.md) and the [licence supplement](docs/STACK_AND_LICENSES.md).

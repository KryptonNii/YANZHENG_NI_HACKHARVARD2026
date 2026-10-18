# A11 claim ledger

Reconciled October 17, 2026, America/Toronto. This ledger supports the final local presentation package. Backend owns `docs/sources.md`, the scientific output and original validation evidence; these were read without alteration. Competitor and BMJ pages were reopened; the Moore PMC page returned a browser challenge on this recheck, while the original source and earlier inspection remain cited.

## Opened external evidence

| ID | Publisher / year / opened source | Location and claim | Qualification |
|---|---|---|---|
| P1 | ASPE / ERG, 2014, [report](https://aspe.hhs.gov/sites/default/files/migrated_legacy_files//44516/rpt_erg.pdf) | Printed p. viii (PDF p. 9) and printed p. 21 (PDF p. 34): procedure 15–22%, administrative staff 11–29%, monitoring 9–14%, site retention 9–16%, central lab 4–12%. | Historical cost shares across phases. Detailed text excludes site overhead and sponsor monitoring. Not additive scenario bounds. Landing page and PDF fetched directly; PDF text inspected after browser fetch failed. |
| P2 | Moore et al., JAMA Internal Medicine, 2018, [original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC6248200/) | Abstract Results: $19.0m median estimated direct cost per pivotal trial, 138 trials, 59 agents approved in 2015–2016. | Historical modelled costs, not invoices or cost per drug approval. Original paper opened on PMC. |
| P3 | FDA, [Step 3: Clinical Research](https://www.fda.gov/patients/drug-development-process/step-3-clinical-research), accessed 2026 | Phase “Length of Study”: Phase 1 several months, Phase 2 several months to 2 years, Phase 3 1–4 years. | Educational durations, not a Regeneron quotation. The *Choose Your Timeline* sheet instead cites Wong, Siah & Lo 2019 medians (Phase 1 1.6, Phase 2 2.9, Phase 3 3.8 years). |
| P4 | Irena Maragkou, Clinical Trials Arena, May 28, 2025, [article](https://www.clinicaltrialsarena.com/news/mapping-out-opportunities-to-reduce-emissions-in-clinical-trials/) | Passage discussing Edward Owen's Genentech presentation gives an industry average 60–70% clinical-trial IMP waste estimate. | Conference reporting with no audit denominator/method in that passage. Browser returned 403; direct HTTP fetch succeeded and article/date inspected. |
| S1 | Griffiths, Fox, Williamson and LCCT Group, BMJ Open, 2024, [original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10823997/) | Abstract: CASPS 72 t CO2e and PRIMETIME 89 t CO2e, rounded. Methods: activity × factor, 10 modules, activities beyond routine care. | Published references only. Exact comparison outputs belong to A10's generated JSON. Paper CC BY 4.0. |
| C1 | Evinova, [Drug Development Suite](https://evinova.com/dds), accessed 2026 | Describes scenario comparisons across timeline, cost, patient experience, complexity and carbon. | Vendor capabilities, not head-to-head testing; no “first multi-metric simulator” claim. |
| C2 | Evinova, [Carbon Estimation and Reporting](https://evinova.com/carbon), accessed 2026 | Design-stage carbon module, reporting and benchmarking services. | Do not infer missing features from silence or repeat “industry-first” as our finding. |
| C3 | Pistoia Alliance, March 2025, [announcement](https://pistoiaalliance.org/news/launches-sustainability-initiative/) | SHC/iLCCT launched the Clinical Trial Carbon Calculator in February 2025 with Pistoia participation. | Collaboration, not solely a Pistoia product; no unverified absence claims. |
| C4 | Medidata, [Centralized Monitoring](https://www.medidata.com/en/clinical-trial-products/clinical-operations/rbqm/centralized-monitoring/), accessed 2026 | Describes targeted SDV, remote source review and data/risk surveillance. | Established monitoring overlap; no superiority claim. |
| C5 | ValGenesis, [VLMS 5.0 retrospective](https://www.valgenesis.com/blog/valgenesis-vlms-5.0-next-gen-validation-lifecycle-management), updated July 17, 2026 | Identifies current iVal validation authoring, execution, traceability and risk workflows. | Vendor description; no “first AI validation platform” claim. |
| N1 | SMI Health Systems Task Force, February 2025, [CEO/CRO letter](https://a.storyblok.com/f/109506/x/0245e71cdc/smi-ceo-cro-letter-_-february-2025.pdf) | Reporting commitment/framework context for future mapping. | TrialPilot has not demonstrated framework conformity. |
| H1 | HackHarvard, [official event page](https://www.hhuh.io/), accessed 2026 | Regeneron sponsors “Reinvent Clinical Trials.” | Event page only; the starter kit below gives the sheets and rules. |

## Regeneron starter kit

Checked on October 17, 2026 against the official starter kit: judging criteria, starter sheets and Mentor Insights 01–02.

| Item | What the kit says | Use in TrialPilot |
|---|---|---|
| Judging criteria | Usefulness, readiness and design. Submit a GitHub repo (ideally MIT), a pitch deck, a demo video and ideally a demo link. Do not build a starter sheet literally. | Repo is public and MIT; the [sheet mapping](../README.md#regeneron-starter-sheets) ties several sheets into one workflow |
| *Choose Your Timeline* | Cites Moore et al. 2018 ($19 million median pivotal trial) and Wong, Siah & Lo 2019 phase durations; says that with separate spreadsheets "each 'what if' takes days". | P2 is the same Moore figure, opened at source. P3 durations are FDA's, not the sheet's |
| *One Screen to Rule Them All* | Cites Tufts CSDD: about 11% of sites never enroll a patient and 37% under-enroll. | Quoted in the README as the sheet's figure, not re-verified at Tufts |
| *Software Speedrun, Any%* | Asks for a measured manual baseline for any effort claim and forbids declaring a system validated without human QA approval. | No effort claim is made; the package stays awaiting QA approval |
| Mentor Insights 01–02 | Public or synthetic data only; name agent risks such as prompt injection and show mitigations; judges distinguish working prototypes from mockups. | Synthetic feeds and public registry data; mitigations listed in the README |

## Versioned measurements and build claims

Code scope: **8fca2d71cde979909c7a8535d43dc95b4f6c94c0** (clean clone, dirty=false). Later commits change documentation only. Complete original output: [`validation/out/clean-clone/20261018T061014Z`](evidence/clean-clone-20261018T061014Z/summary.json). The previous run at **e5c386b1fb0b6edf362bf5d37b97cc17066dfd07** (frontend e425ca2, backend f91cdb2; 576 passed) is kept in [`docs/evidence/clean-clone-20261017T041438Z`](evidence/clean-clone-20261017T041438Z/summary.json); the demo recording was made on that commit. Unmodified copies of the run summaries and the package's text deliverables are in [`docs/evidence/`](evidence/); screenshots, logs and the package ZIP remain local.

| Claim | Recorded result | Scope / qualification |
|---|---|---|
| Complete execution | **819 passed; 0 failed/errors/skipped/unrun** | contracts 106, engine 139, API 404, ops 65, validation 55, science 37, real Edge E2E 13 |
| Frontend preflight | **155/155** unit tests, typecheck/build pass | Separate from the 819 execution count; pinned pnpm 9.15.9 |
| Requirements | **32 pass**, 0 fail/incomplete/untested | Includes substantive URS-014 module and WTT boundary checks |
| Final-package browser check | **1/1 pass** at e5c386b; not repeated for 8fca2d7 | [Supplement](evidence/backend-20261017T042216Z-package-browser/run-context.json); executed after that package was created, separate from its 576; checks counts, QA, Markdown/PNG/ZIP hashes |
| Package integrity | **115/115** hashes and downloads verified; zero evidence-integrity problems | Real compliance HTTP router via ASGI TestClient; [manifest checks](evidence/clean-clone-20261018T061014Z/package-downloads.json) |
| Audit | Audit chain intact at **14** entries | Checked by the clean-clone run after packaging |
| QA | **awaiting QA approval**, human_qa_approval=false | Fictional automated signatures; no human approval of report |
| Cold performance | **143.3 ms median**, samples 143.3/143.0/143.6/138.1/140.9/150.9/151.7 | Windows AMD64, CPython 3.15.0, seeds 200–206, all cache miss, 2,000 requested forecast draws, server X-Compute-Ms; <300 ms gate passed. Previous run at e5c386b: 147.8 ms on CPython 3.12.14 |
| Performance variability | **308.2 ms** earlier standalone median missed the same gate | [Original observation](evidence/backend-20261017T041106Z-cold/benchmark.json) retained; no blanket latency guarantee |
| Historical complete run | **507 passed / 3 failed**, **664.1 ms** cold median at 38e2073 | [Original 20261017T023042Z summary](evidence/clean-clone-20261017T023042Z-historical/summary.json), not evidence for the new commit |
| Protocol parser | Historical synthetic fixture: **7/7 visits, 50/50 procedure items** | [A4](../handoffs/A4.md); live LLM accuracy unmeasured; bulk acceptance is only a review-log metric |
| Planted defects | Historical **6/6** at d616645 | [LAST_RUN](../validation/defects/LAST_RUN.json); unsigned, not blind, not current-code GxP evidence |
| Human effort / realized savings | **Unmeasured** | No human timing, financial savings, clinical outcomes or faster trials claimed |
| Docker / hosting | **Unverified / no deployment URL** | Docker unavailable; no push, deployment, upload or submission |

The complete E2E suite occurs before package generation, so its validation-page test correctly sees `package_not_built`; the separate 1/1 browser supplement verifies the final package. Do not conflate these scopes.

## Scientific snapshot

[`science/out/results.json`](../science/out/results.json), code **e5c386b1fb0b6edf362bf5d37b97cc17066dfd07**, parameter set **1249d0f0eed8**, seed **7**, draws **2,000**. SHA256 **51b307a5a85795969551bf4bde514044f95cc988484f83f8c3600082668358a2**. Per-trial activity overrides also have their own parameter hashes in the output.

| kg CO2e | Published total | Paper arithmetic / gap | Engine + library P10 / P50 / P90 | Engine P50 gap |
|---|---:|---:|---:|---:|
| CASPS | 71,938.8 | 71,943.18 / +0.01% | 64,601.50 / 88,758.48 / 123,510.08 | **+23.38%** |
| PRIMETIME | 89,360.2 | 89,221.19 / −0.16% | 87,891.34 / 109,685.91 / 142,685.69 | **+22.75%** |

`engine_library` is the full engine check; `library` is a distinct factor-ledger check. Drug_supply is excluded from published-method comparisons per draw. Direct and WTT factors are applied once each; unidentified paper road freight is counted once without an invented WTT split. The former **+5%/+7%** results are obsolete.

Both references lie inside engine ranges. Missing hospital utilities, samples/audits, differing industry monitoring and initiation/closeout activity, and PRIMETIME's 1,962 versus 1,623 visit subgroup remain model gaps. Ranges have no established real-world coverage. Carbon reproduction does not validate other metrics. Industry-band rows use **t_co2e**; module comparisons use **kg_co2e**. The band is a sanity check, not calibration or validation.

## Media provenance

The [recording](../README.md#demo-media), [screenshots](assets/screenshots/) and [12-slide editable deck](../README.md#demo-media) use the final local application. The original 180-second recording is silent with [English captions](assets/trialpilot-demo.en.vtt); no synthetic voice or human narrator is claimed. [Release metadata](assets/release-data.json) and [media manifest](assets/media-manifest.json) bind sources, hashes, actual duration and visual inspection. Cached protocol content is a build-time transcription, operating feeds are synthetic, and all signers are fictional demos.

## Competitor wording

“Existing tools already cover trial design, carbon, monitoring and validation. TrialPilot explores an MIT implementation linking visible assumptions and scenario choices to synthetic operations and inspectable software evidence.”

This is project positioning, not a market-wide uniqueness claim. Competitor links are cited directly here and in deck speaker notes; this task did not modify backend-owned `docs/sources.md`.

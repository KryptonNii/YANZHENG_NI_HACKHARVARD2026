# A11 claim ledger

Reconciled October 17, 2026, America/Toronto. This ledger supports the final local presentation package. Backend owns `docs/sources.md`, the scientific output and original validation evidence; these were read without alteration. Competitor and BMJ pages were reopened; the Moore PMC page returned a browser challenge on this recheck, while the original source and earlier inspection remain cited.

## Opened external evidence

| ID | Publisher / year / opened source | Location and claim | Qualification |
|---|---|---|---|
| P1 | ASPE / ERG, 2014, [report](https://aspe.hhs.gov/sites/default/files/migrated_legacy_files//44516/rpt_erg.pdf) | Printed p. viii (PDF p. 9) and printed p. 21 (PDF p. 34): procedure 15–22%, administrative staff 11–29%, monitoring 9–14%, site retention 9–16%, central lab 4–12%. | Historical cost shares across phases. Detailed text excludes site overhead and sponsor monitoring. Not additive scenario bounds. Landing page and PDF fetched directly; PDF text inspected after browser fetch failed. |
| P2 | Moore et al., JAMA Internal Medicine, 2018, [original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC6248200/) | Abstract Results: $19.0m median estimated direct cost per pivotal trial, 138 trials, 59 agents approved in 2015–2016. | Historical modelled costs, not invoices or cost per drug approval. Original paper opened on PMC. |
| P3 | FDA, [Step 3: Clinical Research](https://www.fda.gov/patients/drug-development-process/step-3-clinical-research), accessed 2026 | Phase “Length of Study”: Phase 1 several months, Phase 2 several months to 2 years, Phase 3 1–4 years. | Educational durations. Exact Regeneron-sheet wording unverified. |
| P4 | Irena Maragkou, Clinical Trials Arena, May 28, 2025, [article](https://www.clinicaltrialsarena.com/news/mapping-out-opportunities-to-reduce-emissions-in-clinical-trials/) | Passage discussing Edward Owen's Genentech presentation gives an industry average 60–70% clinical-trial IMP waste estimate. | Conference reporting with no audit denominator/method in that passage. Browser returned 403; direct HTTP fetch succeeded and article/date inspected. |
| S1 | Griffiths, Fox, Williamson and LCCT Group, BMJ Open, 2024, [original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10823997/) | Abstract: CASPS 72 t CO2e and PRIMETIME 89 t CO2e, rounded. Methods: activity × factor, 10 modules, activities beyond routine care. | Published references only. Exact comparison outputs belong to A10's generated JSON. Paper CC BY 4.0. |
| C1 | Evinova, [Drug Development Suite](https://evinova.com/dds), accessed 2026 | Describes scenario comparisons across timeline, cost, patient experience, complexity and carbon. | Vendor capabilities, not head-to-head testing; no “first multi-metric simulator” claim. |
| C2 | Evinova, [Carbon Estimation and Reporting](https://evinova.com/carbon), accessed 2026 | Design-stage carbon module, reporting and benchmarking services. | Do not infer missing features from silence or repeat “industry-first” as our finding. |
| C3 | Pistoia Alliance, March 2025, [announcement](https://pistoiaalliance.org/news/launches-sustainability-initiative/) | SHC/iLCCT launched the Clinical Trial Carbon Calculator in February 2025 with Pistoia participation. | Collaboration, not solely a Pistoia product; no unverified absence claims. |
| C4 | Medidata, [Centralized Monitoring](https://www.medidata.com/en/clinical-trial-products/clinical-operations/rbqm/centralized-monitoring/), accessed 2026 | Describes targeted SDV, remote source review and data/risk surveillance. | Established monitoring overlap; no superiority claim. |
| C5 | ValGenesis, [VLMS 5.0 retrospective](https://www.valgenesis.com/blog/valgenesis-vlms-5.0-next-gen-validation-lifecycle-management), updated July 17, 2026 | Identifies current iVal validation authoring, execution, traceability and risk workflows. | Vendor description; no “first AI validation platform” claim. |
| N1 | SMI Health Systems Task Force, February 2025, [CEO/CRO letter](https://a.storyblok.com/f/109506/x/0245e71cdc/smi-ceo-cro-letter-_-february-2025.pdf) | Reporting commitment/framework context for future mapping. | TrialPilot has not demonstrated framework conformity. |
| H1 | HackHarvard, [official event page](https://www.hhuh.io/), accessed 2026 | Regeneron sponsors “Reinvent Clinical Trials.” | Does not expose starter sheets or verify all brief-provided rules. |

## Unavailable sheet evidence

| Needed item | Treatment | Resolution owner |
|---|---|---|
| Tufts site statistics in Regeneron's sheet | Omitted from factual copy; no remembered percentages | Human supplies sheet; A10 records page, quote, year and denominator |
| Sheet's median trial cost and phase durations | Independent P2/P3 context, explicitly not Regeneron quotations | A10 reconciles exact sheet wording |
| Choose Your Timeline / One Screen to Rule Them All / Software Speedrun | Mapping attributed to supplied A11 brief | Human/A10 verifies official titles and sheets |
| Submission rules and deadlines | Brief-provided planning context only | Human confirms official rules |

## Versioned measurements and build claims

Code scope: **e5c386b1fb0b6edf362bf5d37b97cc17066dfd07** (clean clone, dirty=false), containing frontend **e425ca25541e69b40328337aba0ef5145fcd8d91** and backend **f91cdb2**. Documentation/media revisions occur later and do not change tested application code. Complete original output: [`validation/out/clean-clone/20261017T041438Z`](../validation/out/clean-clone/20261017T041438Z/summary.json). Original evidence is preserved locally and ignored by Git; it has not been uploaded or externally archived.

| Claim | Recorded result | Scope / qualification |
|---|---|---|
| Complete execution | **576 passed; 0 failed/errors/skipped/unrun** | contracts 106, engine 105, API 233, ops 34, validation 50, science 36, real Edge E2E 12 |
| Frontend preflight | **48/48** unit tests, typecheck/build pass | Separate from the 576 execution count; pinned pnpm 9.15.9 |
| Requirements | **32 pass**, 0 fail/incomplete/untested | Includes substantive URS-014 module and WTT boundary checks |
| Final-package browser check | **1/1 pass**, no skips/retries | [Supplement](../validation/out/backend/20261017T042216Z-package-browser/run-context.json); executed after package creation, separate from the 576; checks current counts, QA, Markdown/PNG/ZIP hashes |
| Package integrity | **114/114** hashes and downloads verified; zero evidence-integrity problems | Real compliance HTTP router via ASGI TestClient; [manifest checks](../validation/out/clean-clone/20261017T041438Z/package-downloads.json) |
| Audit | Package snapshot intact at **12** entries; final audit intact at **14** | Different capture times, not a broken chain |
| QA | **awaiting QA approval**, human_qa_approval=false | Fictional automated signatures; no human approval of report |
| Cold performance | **147.8 ms median**, samples 143.8/142.7/148.2/143.7/147.8/150.5/151.0 | Windows AMD64, CPython 3.12.14, NCT03930732, seeds 200–206, all cache miss, 2,000 requested forecast draws, server X-Compute-Ms; <300 ms gate passed |
| Performance variability | **308.2 ms** earlier standalone median missed the same gate | [Original observation](../validation/out/backend/20261017T041106Z-cold/benchmark.json) retained; no blanket latency guarantee |
| Historical complete run | **507 passed / 3 failed**, **664.1 ms** cold median at 38e2073 | [Original 20261017T023042Z summary](../validation/out/clean-clone/20261017T023042Z/summary.json), not evidence for the new commit |
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

The [recording](assets/trialpilot-demo.webm), [screenshots](assets/screenshots/) and [12-slide editable deck](assets/trialpilot-deck.pptx) use the final local application. The recording is silent with [English captions](assets/trialpilot-demo.en.vtt); no synthetic voice or human narrator is claimed. [Release metadata](assets/release-data.json) and [media manifest](assets/media-manifest.json) bind sources, hashes, actual duration and visual inspection. Cached protocol content is a build-time transcription, operating feeds are synthetic, and all signers are fictional demos.

## Competitor wording

“Existing tools already cover trial design, carbon, monitoring and validation. TrialPilot explores an MIT implementation linking visible assumptions and scenario choices to synthetic operations and inspectable software evidence.”

This is project positioning, not a market-wide uniqueness claim. Competitor links are cited directly here and in deck speaker notes; this task did not modify backend-owned `docs/sources.md`.

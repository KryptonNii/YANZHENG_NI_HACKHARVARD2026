# Sources — parameter library and science check

Owner: A10. Every number in `data/params/*.yaml` and `science/` traces to an entry here. All sources below were
**opened** (downloaded or read) on 2026-10-16; quotes are copied from the opened text, with the table/page/cell
where the value sits. Nothing was filled in from memory.

**Library conventions** (also in each YAML header)
- `assumption: false` — the **mid** value is copied from an opened source, or derived by stated arithmetic from
  sourced numbers. Any bound that is ours is said so in `rationale`.
- `assumption: true` — the mid is ours; the range is deliberately wide and the rationale says what (if anything)
  bounds it. 58 of 203 parameters are assumptions (`uv run --project contracts python -m trialpilot_contracts.params data/params`).
- Emission factors: DESNZ 2026 is the mid; low/high span the 2022/2025/2026 editions (the only range DESNZ lets us
  source). Flights and air freight always use the **with-RF** columns. Well-to-tank (WTT) is a separate `ef.wtt.*`
  parameter; the published method adds it (see §1.3).
- Money is USD, **not inflation-adjusted**; each rationale gives the money year and FX rate.
- Grid electricity mids are **direct** (combustion) factors to match DESNZ; lifecycle values (Ember) mark the bounds
  or are used, labelled, where no direct factor was opened.

Contents: 1 Griffiths 2024 (science check) · 2 Mackillop 2023 · 3 DESNZ · 4 Grid · 5 Freezer · 6 Travel ·
7 Site time and monitoring · 8 Costs · 9 Drug supply · 10 Forecast · 11 Licences · 12 Not found

---

## 1. Griffiths, Fox, Williamson et al., BMJ Open 2024 — the published method and case studies

- **Title:** Quantifying the carbon footprint of clinical trials: guidance development and case studies
- **Authors / publisher / year:** Griffiths J, Fox L, Williamson PR, on behalf of the Low Carbon Clinical Trials Group.
  BMJ Open 2024;14:e075755, BMJ Publishing Group. doi:10.1136/bmjopen-2023-075755. **Licence: CC BY 4.0.**
- **URL:** https://bmjopen.bmj.com/content/14/1/e075755 (behind a bot check from our network; the identical full text
  and supplements were taken from Europe PMC, PMC10823997: `.../rest/PMC10823997/fullTextXML` and `/supplementaryFiles`).
- **Supplementary files used:** appendix C = `bmjopen-2023-075755supp003.pdf` (CASPS calculations, 24 pp.),
  appendix D = `supp004.pdf` (PRIMETIME, 24 pp.), worksheet "V0.2 14 Feb 2023". Both are image-only PDFs; every
  line was transcribed by hand from rendered page images into `science/data/casps_ledger.yaml` and
  `primetime_ledger.yaml` (page numbers per line).

### 1.1 Numbers verified against the paper (brief said "≈"; these are the paper's)
| | CASPS | PRIMETIME |
|---|---|---|
| Registry | ISRCTN63733470 | ISRCTN41579286 |
| Phase, patients, sites | Phase 2, 47 patients, 12 sites (UK, Spain, Australia) | Phase 3, 1962 patients, 64 UK sites (67 set up) |
| Total (main text, Results) | "72 tonnes (71 939 kgCO2e)" | "89 tonnes (89 360 kgCO2e)" |
| Total (appendix summary table) | 71,938.8 kg (appendix C p.24) | 89,360.2 kg (appendix D p.23–24) |
| Largest modules (main text) | "CTU emissions (23 488 kgCO2e), followed by trial specific meetings and travel (20 465 kgCO2e)" | "patient travel and assessments (60 823 kgCO2e), followed by CTU emissions (11 733 kgCO2e) and data collection and exchange (7572 kgCO2e)" |

Per-module values (appendix summary tables; Figure 2/3 labels agree after rounding):

| Module (paper name → TrialPilot id) | CASPS kg | PRIMETIME kg |
|---|---|---|
| Trial set up → `setup` | 349.8 | 454.2 |
| CTU emissions → `trial_management` | 23,487.6 | 11,733.3 |
| Trial staff meetings and travel → `meetings_travel` | 20,465.3 | 1,136.2 |
| Treatment intervention → `intervention` | 1,251.5 | 0 |
| Data collection and exchange → `data_collection` | 558.3 | 7,572.1 |
| Trial supplies and equipment → `supplies_equipment` | 522.5 | 1,741.5 |
| Trial specific patient assessments → `patient_assessments` | 11,298.4 | 60,822.7 |
| Samples → `samples` | 1,930.5 | 438.2 |
| Laboratory → `laboratory` | 9,353.6 | 2,061.4 |
| Analysis and trial close out ("Archiving" in the figures) → `closeout` | 2,721.3 | 3,400.6 |

Note: CASPS's "intervention" module is **IMP distribution and incineration of overage**, not manufacture (out of
scope in the method).

**Industry range** (Introduction): Mackillop et al.'s three industry trials "was 2498 tonnes CO 2 e, 1632 tonnes CO 2 e
and 1437 tonnes CO 2 e, respectively" → the 1,437–2,498 t band is correct (see §2 for Mackillop's own 1632/1638 discrepancy).

**Factor sources stated by the paper:** "The main emission factor sources used were Ecoinvent V.2.2, GOV.UK GHG
conversion factors and the SHC care pathway carbon calculator." Reference 10 = GOV.UK conversion factors **2022**.

### 1.2 Errors found while reproducing (all in `science/out/results.json` → `findings`)
| id | What | Effect |
|---|---|---|
| casps-f1 | Centrifuge energy: appendix C p.20 prints "310 x 0.25 = 77.5 kWh" (310 W × 0.25 h is 0.0775 kWh). The same worked example appears in the guidance (appendix D p.21). | −811.7 kg (−1.1% of CASPS) when corrected |
| casps-f2 | Ambient tissue storage (1 m² × 10 years, 221 + 415 kg) counted in both §9.3 (laboratory) and §10.2 (close-out). | −636 kg when de-duplicated |
| casps-f3 | Australia monitoring: activity "15310 p.km", calculation text "11074 p.km", result 3119.1 = 15310 × 0.20373. | none (typo in text) |
| casps-f4 | TMG teleconferences: 16 attendees in activity data, "18" in the calculation; result uses 16. | none |
| casps-f5 | Audit long-haul: 29442 × 0.21423 = 6307.4, printed 6303.1. | −4.3 kg |
| casps-f6 | CTAD + CPT glass tubes: calculation shows 3.413; result 9.57 uses glass 1.403 (listed on p.18). | none |
| primetime-f1 | Hotels: "8 x 13.9 = 250.2" (= 111.2; 250.2 = 18 × 13.9); the activity says 8 rooms twice. | −139.0 kg (−12.2% of the module) |
| primetime-f2/f3 | Kit postage "630 x 295.88" (result matches 301.8 km); tracking slips "26.9 kg" (result matches 29.89 kg). | none |
| primetime-f4 | Mammograms costed with the chest X-ray factor (0.8 kg), no mammography factor exists in the guidance. | — |
| (transcription) | PRIMETIME archive heating printed "36"; result 1428 = 35.69 × 40 (same factor as CASPS). | — |

### 1.3 The paper's travel and freight factors = DESNZ 2022 direct + well-to-tank (verified)
Each LCCT factor equals a DESNZ 2022 direct factor (with RF for aviation) **plus** its WTT factor, to 5 decimals
(`science/tests/test_ledger.py::test_lcct_travel_factors_are_desnz_2022_plus_wtt`):

| LCCT factor | DESNZ 2022 direct (sheet, cell) | + DESNZ 2022 WTT (full set, sheet, cell) |
|---|---|---|
| National rail 0.04441 | 0.03549 ('Business travel- land' E87) | 0.00892 ('WTT- pass vehs & travel- land' E83) |
| Domestic flight 0.27278 | 0.24587 ('Business travel- air' F23, with RF) | 0.02691 ('WTT- business travel- air' F20) |
| Short-haul flight 0.17034 | 0.15353 (F24) | 0.01681 (F21) |
| Long-haul flight 0.21423 | 0.19309 (F27) | 0.02114 (F24) |
| International flight 0.20373 | 0.18362 (F32) | 0.02011 (F29) |
| Freight flight domestic 4.98549 | 4.49363 ('Freighting goods' E98) | 0.49186 ('WTT- delivery vehs & freight' E92) |
| Freight flight short-haul 2.55439 | 2.30229 (E99) | 0.2521 (E93) |
| Freight flight long-haul 1.13047 | 1.0189 (E100) | 0.11157 (E94) |

Not identified: the road-freight factor 0.19443 matches no DESNZ 2022 HGV or van row (with or without WTT); the UK
electricity factor 0.273 is not explained in the appendices; hotel factors 13.9 / 18.7 / 42.6 are from the DESNZ
**2021** hotel tab linked in the appendix (2022–2026 editions: 10.4 / 7.0 / 35.0). Paper material 0.919 = DESNZ 2022
"Paper and board: paper" 919.39628 kg/t (cell E87).

### 1.4 Values taken into the library (`data/params/lcct_method.yaml`, `modules.yaml`)
Per-FTE coordinating-unit factors 193.28 / 431.56 / 1027.8 kg (appendix C p.5–7: "Energy consumption for 1 FTE for 1
year = 193.28 kgCO2e", "Heating for 1 FTE for 1 year = 431.56 kgCO2e", "total average commuting emissions = 1027.8
kgCO2e"); videoconference "157 grams CO2e per hour" (C p.8); patient visit "one patient visit to hospital (UK) = 5.8
kgCO2e (this includes both the out and back journeys)" (C p.15); consumables 0.30 kg per appointment; CT 9.2, MRI 24.7,
chest X-ray 0.8 kg (C p.15, D p.15); blood tests 82/116/49/99/0.5 g "include the materials and consumables required for
sample collection, phlebotomy and analysis" (C p.16); hospital 364.9 / 685.7 kg per FTE-year (C p.16–17); lab 1747.2 /
1376 kg per FTE-year (C p.19); ULT freezer "2192.2 kgCO2e per year ... this is for a whole freezer" (C p.21); fridge
298.9; single-use cold box 25.2, reusable 2.2 (C p.11–12, 18); dry ice "1.81kg CO2e for 1 kg dry ice produced/used"
(C p.18); "assume 1kg of dry ice is used per individual sample shipping box" (D p.10); data storage 1.365 kg/GB-year
(C p.14; 1.35 on p.23); computer services £ × 0.149, office machinery £ × 0.387 (C p.14); devices (C p.14–15); printing
0.22438 / 0.31786 kg per kg; 0.005 kg per page (C p.3); 17.4 km default delivery distance (C p.4); incineration
2.4252 kg/kg (C p.12); building space per m²-year: office 16.1 / 35.69, health 22.1 / 41.5–41.6, lab 43.7, warehouse
7.4 (C p.22, D p.22); 4 m² archive and 10 years (both appendices, case-study assumptions).
Derived module factors (`modules.yaml`) divide the published module totals by sites, patients or patient-years.
CASPS drug overage: "Total bottles destroyed = 1464" of "~4000 IMP bottles shipped" (C p.11–12) — ~37%, a real-world
data point used as context, not as a parameter (the 4000 is the paper's assumption).

---

## 2. Mackillop et al., BMJ Open 2023 (industry trials; the sanity band)
- Mackillop N, Shah J, Collins M, Costelloe T, Öhman D. Carbon footprint of industry-sponsored late-stage clinical
  trials. BMJ Open 2023;13:e072491, doi:10.1136/bmjopen-2023-072491, PMC10445340 (opened, incl. supplement).
- Abstract: "The total carbon footprint for the cardiovascular trial was calculated as 2498 tonnes ... the oncology trial
  resulted in 1632 tonnes CO2e and the respiratory trial 1437 tonnes". **Discrepancy:** Results text and Table 3 give
  1638 t for the oncology trial ("calculated to be 1638 tonnes CO 2 e ( table 3 )"). Band 1,437–2,498 t unaffected.
- Also used: "IP and placebo" 391.5 t (15.7%), 33 t, 24 t (Tables 2–4) — context for `ef.drug_kit.unit`; supplementary
  Table 2a/2b face-to-face monitor visits (3743 at 432 sites over 39 months; 2400 at 300 sites over 26 months) →
  low bound of `rate.monitoring.onsite_visits_per_site_month`; methodology "F2F - 500 km round trip distance by car
  transportation per visit" and "Virtual - Assumed 4 hours of videoconference" (their modelling assumptions).

---

## 3. UK Government GHG Conversion Factors for Company Reporting (DESNZ)
| Edition | Page | Workbook | Notes |
|---|---|---|---|
| **2026** (mid) | https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026 (published 11 Jun 2026) | `ghg-conversion-factors-2026-full-set.xlsx`, sha256 b5c4f2f8…0205 | 2026 has no condensed set ("full set (for all users)"); UK electricity method revised ('What's new' item 1); rail updated (item 2); HGV rows renamed (item 4) |
| 2025 | …/greenhouse-gas-reporting-conversion-factors-2025 | `…-2025-condensed-set.xlsx`, sha256 666f5a00…0fbb | |
| 2022 | …/greenhouse-gas-reporting-conversion-factors-2022 | `…-2022-condensed-set.xls` and `…-2022-full-set.xls` (WTT sheets) | the edition the paper used |

Column used: total "kg CO2e" (2025/2026) / "Total kg CO2e per unit" (2022). RF statement, 2026 'Business travel- air'
A47: "incorporate a 70% increase in CO2 emissions to approximate the indirect impact of non-CO2 emissions from
aviation"; 2022 B47 says 90%. Haul is defined by destination country ('Haul definition' sheet: e.g. Spain, Germany,
Turkey short-haul; USA, Australia long-haul), not by km.

Cells used (2026 / 2025 / 2022) — every value is in `data/params/emission_factors.yaml` with its cell:
car average unknown km X54 0.16591 / X54 0.16725 / Y56 0.17067 · bus D81 0.10151 / 0.10385 / E81 0.0965 · national rail
D87 0.03092 / 0.03546 / E87 0.03549 · taxi passenger.km D71 0.14861 / 0.14861 / E71 0.14876 · flights with RF (domestic
E23, short-haul E24, long-haul E27, international E32): 0.22928, 0.12786, 0.15282, 0.14253 (2026 = 2025) / 2022 0.24587,
0.15353, 0.19309, 0.18362 · freight flights with RF D98–D101: 4.60397, 1.27835, 0.89939, 0.89939 / 2022 E98–E101 4.49363,
2.30229, 1.0189, 1.0189 · van average unknown T35 0.6394 / 0.63823 / U35 0.58421 · HGV average laden D63 0.10356 (2026
renamed row "HGV (non-refrigerated, all diesel) / Average non-refrigerated HGVs") / P63 0.10163 / Q63 0.10614 · UK
electricity generated E25 0.13096 / E26 0.177 / F24 0.19338 · T&D E22 0.01299 / 0.01853 / F21 0.01769 · materials
(primary production, per tonne): paper D87 1343.59 / 1345.08 / E87 919.40; board D85 1198.24 / – / E85 828.87; mixed
D86 1287.02 / – / E86 884.16; plastics average D72 3170.51 / – / E72 3116.29; PP D78 2575.25 / – / E78 3104.73; PET D77
3861.58 / – / E77 4032.39; glass D40 1402.77 (= 2022) · hotels per room-night (all editions): UK 10.4 (D22), London 11.5,
Spain 7 (D73), Australia 35 (D29) · CO2 (refrigerant & other) D20 1 kg/kg · WTT 2026: car I50 0.04399, bus D78 0.02649,
rail D84 0.00897, flights E20/E21/E24/E29 0.0335/0.02286/0.03213/0.02162, freight flights D93–D96 0.57429/0.20515/0.13516/
0.13516, van H30 0.15335, HGV D58 0.02359; WTT 2022 (full set) in each rationale.
DESNZ no longer publishes overseas electricity factors ("We no longer provide overseas CO2 emission factors", 2026
'Overseas electricity' A11) → §4.

---

## 4. Grid electricity outside the UK (`grid_factors.yaml`)
| Source | Publisher, year | URL | Value taken (location) |
|---|---|---|---|
| REData API, "Emisiones y factor de emisión de CO2 en generación no renovables" | Red Eléctrica, data 2025 | https://apidatos.ree.es/ (query in YAML) | national 2025 `"value":0.10842…` tCO2eq/MWh (mid ES); peninsular 0.0861 (low) |
| National Greenhouse Accounts Factors 2026 | DCCEEW (Australia), Aug 2026, CC BY 4.0 | https://www.dcceew.gov.au/climate-change/publications/national-greenhouse-accounts-factors-2026 (read via Wayback copy) | Table 1 (p.10), "National 0.59 0.10" (scope 2 / scope 3, kg CO2-e/kWh); Victoria 0.74, NSW/ACT 0.60, Qld 0.65, SA 0.21 |
| eGRID2023 Summary Tables rev. 2 | US EPA, 12 Jun 2025 | https://www.epa.gov/egrid/summary-data | Table 1, U.S. total output CO2e 770.884 lb/MWh; grid gross loss 4.2% |
| Strom- und Wärmeversorgung in Zahlen | Umweltbundesamt, 2026 page | https://www.umweltbundesamt.de/themen/klima-energie/energieversorgung/strom-waermeversorgung-in-zahlen | "im Jahr 2025 bei der Erzeugung durchschnittlich 344 Gramm CO 2 ausgestoßen" (per kWh consumed; 2024 353, 2023 379) |
| Yearly electricity data (global CSV) | Ember, 2026 release, CC BY 4.0 | https://ember-energy.org/data/yearly-electricity-data/ | "Emissions intensity (gCO2e/kWh)", Total generation, 2025: Spain 153.459, Australia 517.956, USA 384.403 (2023: 392.9), Germany 334.117, France 41.224 (2024: 40.337), World 460.087 (2024 473.046, 2023 485.622). Lifecycle: methodology p.15 "These figures aim to include full lifecycle emissions" |
| Base Empreinte | ADEME, 2025 | https://data.ademe.fr/ (element 43642) | "Electricité – 2024 – mix moyen – consommation" 0.0519 kgCO2e/kWh (France high) |

---

## 5. −80 °C freezer energy (`energy.yaml`)
- **Roadmap for low-carbon ultra-low temperature storage in biobanking**, J Transl Med 2024, CC BY 4.0,
  https://doi.org/10.1186/s12967-024-05383-5 (PMC11308585): "a power consumption of 9.7 kWh per day has been set"
  (mid; metered 570 L unit, 12-year ageing); older units "sometimes consuming as much as 20 kWh per day" (high).
- **ENERGY STAR Certified Laboratory Grade Refrigerators and Freezers**, US EPA, dataset g242-ysjw (accessed
  2026-10-16): 77 ULT freezers, "Daily Energy Consumption at -80ºC (kWh/day)" min 4.71 (Haier DW-86L730BP, low), median
  8.72, max 13.19.
- **Evolution and Evaluation of Ultra-Low Temperature Freezers**, Foods 2025, CC BY 4.0 (PMC12248920), Table 3:
  "Upright ULT Freezers ... Energy Consumption: 16–25 kWh/day" (context).
- Cross-check: the LCCT 2192.2 kg per freezer-year ÷ 0.273 kg/kWh ≈ 8,030 kWh/yr ≈ 22 kWh/day.

---

## 6. Patient travel (`travel.yaml`)
| Source | Publisher, year | URL | Taken |
|---|---|---|---|
| NTS0403 Average trips, miles and time by purpose | DfT, updated 10 Sep 2026 | https://www.gov.uk/government/statistical-data-sets/nts04-purpose-of-trips | 'Personal business' 2025: 5.222 mi trip length (sheet NTS0403e, row 30) and 20.70 min (NTS0403f) → 16.8 km round trip (low), 24.4 km/h |
| NTS 2025 notes and definitions | DfT, 2026 | https://www.gov.uk/government/statistics/national-travel-survey-2025/nts-2025-notes-and-definitions | Personal business includes "medical consultations or treatment" |
| NTS0409 trips and distance by purpose and main mode | DfT, 2026 | same page | 2025 'Personal business': car/van driver 203.215 + passenger 105.931 of 386.311 mi (car share 0.80); surface rail 30.645 vs bus miles (rail share 0.657) |
| Impact of Virtual Clinics on ... NHS Outpatient Waiting Lists and Carbon Emissions | Foot Ankle Orthop, 2024 (PMC11653461) | https://doi.org/10.1177/24730114241305603 | "Average distance: 5.94 miles ... Round trip distance ... 11.89 miles" (mid GB) |
| Virtual joint school prior to hip and knee arthroplasty | Ann R Coll Surg Engl, 2026 (PMC13321172) | https://doi.org/10.1308/rcsann.2025.0080 | "each patient saved, on average, 38 miles and 62min of travel" (high GB) |
| 2022 National Household Travel Survey public-use data + codebook | FHWA/ORNL, 2025 | https://nhts.ornl.gov/ | WHYTO=11 "Health care visit", n=684, weighted: mean 12.901 mi, median 7.44 mi; car 92.29% of trips / 97.68% of miles; 27.33 mph; dwell median 61 min (our weighting reproduces the published 12.6 mi all-trip mean, Summary of Travel Trends Table 3-3) |
| At What Cost to Clinical Trial Enrollment? | The Oncologist, 2018 (PMC6263122, abstract) | https://doi.org/10.1634/theoncologist.2017-0628 | "median unidirectional distance ... was 25.8 miles" (high US) |
| Consuming Patients' Days | The Oncologist, 2024, CC BY (PMC11067814) | https://doi.org/10.1093/oncolo/oyae016 | "median (IQR) round-trip driving distance and travel time was 34 (17-49) miles and 50 (36-68) minutes"; "median (IQR) clinic time was 119 (78-202) minutes" |
| Opportunity costs of ambulatory medical care in the United States | Am J Manag Care, 2015 (PMC8085714) | https://pubmed.ncbi.nlm.nih.gov/26295356/ | "37 minutes ... of travel time and 84 minutes ... of clinic time" (mid visit time) |
| Impact on the reduction of CO2 emissions due to the use of telemedicine | Sci Rep, 2022, CC BY (PMC9307763) | https://doi.org/10.1038/s41598-022-16864-2 | "approximately 13 km for a round trip"; car 50% / 80% mode assumptions (ES) |
| Impact of travel distance on outcomes for clinical trial patients | Intern Med J, 2023 (abstract) | https://doi.org/10.1111/imj.15561 | "27% lived within 10 km, 29% lived between 10 and 50 km and 44% lived further than 50 km" (AU bounds) |

---

## 7. Site staff time and monitoring (`site_time.yaml`)
- **NIHR national costing tariff 2025-26 v1.1** (staff-time definitions for industry studies in the NHS), as appended
  to a Cardiff and Vale UHB board paper:
  https://cavuhb.nhs.wales/files/board-and-committees/finance-performance-2026-27/3-2c-appendix-a-nihr-national-costing-template-tarrifs-pdf-1-pdf/ .
  "Values within this tariff solely define the relevant labour time required by research staff". Lines used (minutes):
  NIHR_PRC_001 consent C60+N60 (guidance 30/45/60); _004 sample collection N15; _005 processing N20; _006 dispatch N30;
  _007 vital signs C10+N10; _011 physical exam C30+N20; _012/_013 urine N10+N10; _017/_018 questionnaire N30+N30;
  _026 "CRF/eCRF completion including data transfer and query resolution" C15+N60; _033 dispensing 70, _034 aseptic
  120, _037 IVR/IWR 16, _039 accountability 35; NIHR_GPC_017 "Monitoring fee for both onsite and remote monitoring"
  Nurse 450 + Admin 450, "based on a full working day for both onsite and remote monitoring"; _047 pharmacy 240.
- **Berthelot S et al.**, JACEP Open 2022 (PMC9292471), Table 2 measured medians: venipuncture 6.1, "ECG 8 82 4.6
  (3.8; 6.1)", CT abdomen with contrast 4.5 (expert 15), chest X-ray 5.1 (3.1; 7.1).
- **Colarieti A et al.**, Radiol Med 2025 (PMC12872687): MRI "typically 25–45 min", DCE-MRI 30 min, "CEM required
  approximately 10 min per case".
- **Sakamoto/Kagiyama et al.** AI-Echo RCT, JAHA 2026 (PMC12909003): "13.0±3.5 minutes versus 14.3±4.2 minutes";
  **Hollitt KJ et al.**, Echo Res Pract 2025 (PMC12168272): standard protocol 18.0 min.
- **Aytaç A et al.**, Acta Radiol Open 2025 (PMC12743816): biopsy "20.7 ± 7.4; median 18"; **Li P et al.**, Korean J
  Radiol 2025 (PMC12055272): "mean, 36.7 ± 8.7 minutes".
- **US FDA**, Oversight of Clinical Investigations — A Risk-Based Approach to Monitoring, Aug 2013,
  https://www.fda.gov/media/116754/download, p.3: "companies typically conduct on-site monitoring visits at
  approximately 4- to 8-week intervals".
- **Fu Z et al.**, J Med Internet Res 2023;25:e42175 (PMC10337412), Table 2: "Total monitoring time (hours) 28.61
  (20.719) 24.650 (20.950)".
- **Khan JS et al.**, Can J Pain 2019 (PMC8730625): queries "(4.92 [SD = 4.67] vs. 1.88 [SD = 1.51]" and pilot "25";
  **Blau S et al.**, JCO Clin Cancer Inform 2023 (PMC10569766): "an average of 472.97 per patient enrolled".
- **PPD** Preclarus case study 2023, https://www.ppd.com/wp-content/uploads/2023/06/Preclarus_Case-Study.pdf: "each
  query needing an estimated five minutes of hands-on time to resolve" (excludes research time).
- **CMS** HH PPS CY2026 Table 5 (average skilled-nursing visit 44.8 min) and PFS RVU26D descriptors ("Office o/p est
  low 20 min", "mod 30 min") → patient time for home and telehealth visits.

---

## 8. Costs (`costs.yaml`) — USD, money year in each rationale
| Source | Publisher, year | URL | Taken |
|---|---|---|---|
| Nevens H et al. Budgeting of non-commercial clinical trials (Additional file 1) | Trials (BMC), 2019, PMC6907219 | https://media.springernature.com/original/springer-static/esm/art%3A10.1186%2Fs13063-019-3900-8/MediaObjects/13063_2019_3900_MOESM1_ESM.docx | Table S1 "Clinical Research Associate (monitor) € 50,00 € 67,28"; Table S2 on-site visits €150,696 for 140 visits; "Fixed average transportation fee per on-site visit 65 €"; IMP handling €130,000 + storage €20,000 (400 patients × 7 visits); investigator meetings €3,500 |
| CTU price examples (27 Mar 2023) | Oslo University Hospital CTU, 2023 | https://oslo-universitetssykehus.no/4a2377/siteassets/underomrade-forskningsstotte/dokumenter/ctu/20230327-ctu-price-examples.pdf | Example III: NOK 120,000 for initiation + 3 monitoring visits |
| UUSOP-13 Clinical Research Institutional Fee Schedule (1 Jul 2026) | University of Utah, 2026 | https://qualitycompliance.research.utah.edu/sop-library/uu-sop-13.php | "Monitoring Visit: $918 per day"; "Research Nurse Effort: $417 per hour"; "Laboratory Setup: $2,025 one-time"; "Participant Travel Reimbursement: Current IRS business mileage rate" |
| OEWS May 2025 (API series OEUN…291141) | BLS, 2025 | https://www.bls.gov/oes/ | Registered Nurses hourly mean 48.76, p25 38.62, p90 66.09 |
| Employer Costs for Employee Compensation, June 2026, Table 4 | BLS, 2026 | https://www.bls.gov/news.release/ecec.t04.htm (read via fetch tool; bls.gov blocks downloads) | "Registered nurse occupations 79.02 100.0 52.14 66.0 …" → wages 66.0% of compensation |
| HH PPS CY2026 rate update, Transmittal 13488 / CR 14304 | CMS, Nov 2025 | https://www.cms.gov/files/document/R13488CP.pdf | Table 3 Skilled Nursing $172.73 → $176.96 (columns interleaved in the PDF; 5th row); LUPA add-on "1.7200 for SN" |
| 2026 National PFS Relative Value File (RVU26D, Oct) | CMS, 2026 | https://www.cms.gov/medicare/payment/fee-schedules/physician/pfs-relative-value-files/rvu26d | 99213 total RVU 2.85 (non-facility) / 1.72 (facility); 99214 4.06; CF 33.4009 |
| Ballpark Budget for ECHO Lab Core Shipping v2 | ECHO / VUMC, Nov 2025 | https://echochildren.org/wp-content/uploads/2025/11/Ballpark-Budget-for-ECHO-Lab-Core-Shipping_v2.pdf | Table 6: "FedEx 2-Day (Local/Ambient) … $26.25", national ambient $43.75, national dry ice $140.00 |
| ACTG Budget Processing Cost List (5 Jan 2023) | Rush University, 2023 | https://www.rushu.rush.edu/sites/default/files/2024-03/rspsl-price-list-0123.pdf | ambient shipper $56.35/$61.99/$67.62; refrigerated $133.91/$147.30/$160.69; dry ice real-time $185.07/$203.58/$222.08 |
| Logistical Challenges Of The 'Reverse Supply Chain' For Biospecimens | Clinical Research News, 24 Jan 2022 | https://www.clinicalresearchnewsonline.com/search-news/2022/01/24/logistical-challenges-of-the-reverse-supply-chain-for-biospecimens | premium courier "quoted $1,100" |
| Medicare Part B payment allowance limits, Oct 2026 | CMS, 2026 | https://www.cms.gov/medicare/payment/part-b-drugs/asp-pricing-files | Q5103 infliximab-dyyb 28.456 per 10 mg; J3380 vedolizumab 20.949/mg; J9271 pembrolizumab 62.253/mg (doses from FDA labels via openFDA) |
| NADAC 2026 | CMS / data.medicaid.gov, as of 2026-10-14 | https://data.medicaid.gov/dataset/fbb83258-11c7-47f5-8b18-5f8e79f7e704 | "ELIQUIS 5 MG TABLET" 5.52114 per tablet |
| Standard mileage rates | IRS, 2026 | https://www.irs.gov/tax-professionals/standard-mileage-rates | 2026 (Jul–Dec) business 76 cents/mile |
| CONUS per diem FY2027 (91 FR 57616) | GSA, 10 Sep 2026 | https://www.federalregister.gov/documents/full_text/text/2026/09/10/2026-18439.txt | lodging $113, M&IE $68 |
| Foreign Exchange Rates G.5A Annual | Federal Reserve, Jan 2020 and Jan 2026 releases | https://www.federalreserve.gov/releases/g5a/ | EUR 2019 1.1194 USD; EUR 2023 1.0817; NOK 2023 10.5659 per USD |
| Medical Scientists (19-1042) OEWS May 2025 | BLS | as above | mean hourly 56.18 (basis of the `cost.trial_management.per_fte_year` assumption) |
| **Examination of Clinical Trial Costs and Barriers for Drug Development** (ASPE 2014) | Sertkaya A et al., Eastern Research Group for HHS/ASPE, 25 Jul 2014 | https://aspe.hhs.gov/reports/examination-clinical-trial-costs-barriers-drug-development-0 | **Opened; publishes no per-unit costs.** Appendix B defines units (site monitoring "Day", SDV "Data field", RN/CRA "Patient") but only per-study means by phase (Table 2, p.3-6, e.g. Phase 3 site monitoring $1,624,874; central lab $849,180) and per-study totals (Table 1). Data 2004–2012, not inflation-adjusted. Used only as context. |
| Variation in the estimated costs of pivotal clinical benefit trials | Moore TJ et al., BMJ Open 2020 (PMC7295430) | https://doi.org/10.1136/bmjopen-2020-038863 | "estimated cost per patient was US$41 413 ... each patient visit to the study clinic cost an estimated median of US$3685" (context only) |

---

## 9. Drug supply (`supply.yaml`)
- **Clinical Trials Arena** — Maragkou I. "Mapping out opportunities to reduce emissions in clinical trials", 28 May
  2025, GlobalData. https://www.clinicaltrialsarena.com/news/mapping-out-opportunities-to-reduce-emissions-in-clinical-trials/
  (curl blocked; read in a browser). **Exact sentence** (paragraph 6), reporting a talk by Edward Owen (Genentech, Roche
  group) at CTO West Coast:
  > "Specifically, Owen mentioned that the company aims at improving enrollment forecasting to better manage drug supply
  > and avoid overproduction, a serious problem since across the industry, on average, 60-70% of clinical trial IMP is wasted."

  No primary data or citation is given for the figure → labelled **industry-reported** in the parameter.
- **ZS**, "Rethinking waste management in clinical supply chains" (white paper, 2025),
  https://www.zs.com/content/dam/pdfs/whitepaper-rethinking-waste-management-in-clinical-supply-chains.pdf: "Only 40%
  of manufactured clinical supplies are ultimately administered to patients on average"; Fig. 2 "industry wastage is
  ~60% (Range from 30% to 70%)"; p.2 "routinely plan for 150% to 200% overage".
- **IQVIA** (Duerr S), "Reducing Waste with Intelligent Automation...", 2024: "a median waste level of 50% for
  Investigational Medicinal Product (IMP) kits".
- **Carter K et al.**, Forced randomization, BMC Med Res Methodol 2024;24:234 (PMC11459895): "the overage was lowest
  (~ 47–52% higher than the "ideal") with the Low re-supply strategy"; ideal "n / 2 kits of each drug type ... per
  treatment group".
- **N-SIDE**, "The hard balance between a short shelf life and low drug waste" (case study, 2023): "expected to reach
  an overage of around 300%"; "fell below 80%"; shelf life 12 → 15/18 months, "up to a maximum of 24 months", "only 9
  months of remaining shelf life".
- **Yiu TH et al.**, Ther Adv Gastroenterol 2025 (PMC12497974): adalimumab shelf life 24–42 months (context).

## 10. Recruitment and timeline forecast (`forecast.yaml`)
- **Walters SJ et al.**, BMJ Open 2017;7:e015276 (PMC5372123): "The median recruitment rate (participants per centre
  per month) was found to be 0.92 (IQR 0.43–2.79)"; "median retention rate ... 89% (IQR 79–97%)".
- **Goyal A et al.**, JAMA Netw Open 2021 (PMC9435961): "Median time to activation was 171 days (IQR, 114-246 days)".
- **Lai J et al.**, Ther Innov Regul Sci 2021 (PMC7505220): contract execution "7.9 months for US sites ... 8.7 months
  for sites outside the US" (context).
- **Tufts CSDD Impact Report** Vol 20 No 1, Jan/Feb 2018 (2017 eClinical Landscape Study with Veeva):
  "Time from last patient, last visit to database lock 36.3 38.7* 27.7*" (days; text says 36.1).

---

## 11. Licences (for THIRD_PARTY.md — A1)
| Data | Licence | How we use it |
|---|---|---|
| Griffiths et al. BMJ Open 2024 + supplements | CC BY 4.0 (stated in the article) | numbers transcribed, cited; PDFs **not** committed |
| DESNZ GHG conversion factors 2022/2025/2026 | Open Government Licence v3.0 (gov.uk footer: "All content is available under the Open Government Licence v3.0, except where otherwise stated") | values copied with cell references; workbooks not committed |
| DfT National Travel Survey tables | gov.uk statistics (OGL v3.0, same footer) | values copied |
| Ember yearly electricity data | CC BY 4.0 ("All content is released under a Creative Commons Attribution Licence") | values copied, attributed |
| Australian NGA Factors 2026 | CC BY 4.0 (DCCEEW) | values copied |
| Other papers and documents | various (several CC BY); only individual numbers (facts) with citations are used, short quotes only | no documents committed |

## 12. Searched but not found (→ assumptions in the library)
US commercial CRA day rate; ASPE per-unit values; airfare (BTS/DOT blocked); participant stipend averages; commercial
DCT home-nursing prices; refrigerated courier rates; sponsor IMP cost of goods; investigator-meeting cost per attendee;
local-lab harmonisation as a defined activity; peer-reviewed measured IMP waste %; TransCelerate RBM paper (404);
OPTIMON/START monitoring trials (not open); research-staff minutes for imaging/ECG; standard 2D mammography time;
measured query-resolution minutes; empirical kits per dispensing visit; Spanish/French official direct grid factors
(consumption basis); EEA country values (interactive only); UK national outpatient travel distance; Australian and
Spanish medical-trip surveys; global travel parameters.

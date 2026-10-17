# Peer cohort: all Phase 3 COPD registry records

Implemented on 2026-10-17. No commit was created.

## Download

Query (ClinicalTrials.gov API v2, every page followed with `nextPageToken`, 0.3 s between
requests):

```
https://clinicaltrials.gov/api/v2/studies?query.cond=COPD&filter.advanced=AREA[Phase]PHASE3&pageSize=100&countTotal=true
```

| Item | Value |
| --- | --- |
| `totalCount` reported by the API this run | **553** |
| Pages | 6 (100 + 100 + 100 + 100 + 100 + 53) |
| Studies downloaded | **553** (553 unique NCT IDs, no duplicates across pages) |
| Study files saved | **553** `data/fixtures/peers/registry/{NCT}.json` |
| Metadata files saved | 553 `data/fixtures/peers/registry/{NCT}.meta.json` |
| API version / `dataTimestamp` | 2.0.5 / `2026-10-16T09:00:05` (same at start and end of the run) |
| Fetched | 2026-10-17 05:34–05:35 UTC |
| Disk size | 43 MB |

Each study file is the study object exactly as the search endpoint returned it
(`protocolSection` complete, plus `derivedSection`, `resultsSection` when present and
`hasResults`), written as UTF-8 JSON with `indent=1` like the importer's cache. The file
name equals `protocolSection.identificationModule.nctId` (checked for every file in
`test_registry_cache_files_are_named_by_nct_and_carry_provenance`).

Each `.meta.json` holds `nct_id`, `source_url` (the exact page request, including its
`pageToken`), `fetched_at`, `api_version`, `data_timestamp`, the `query` parameters and
`attribution: "ClinicalTrials.gov, U.S. National Library of Medicine"`.

Nothing was written to `data/fixtures/ctgov/`. SHA-256 of NCT03930732, NCT04456673,
NCT04535986 and NCT04429503 was identical before and after the download. Three of them
(BOREAS, NOTUS, NCT04535986) are also in the search results, so a registry copy exists for
them; the cohort ignores those copies (below). NCT04429503 (PHOTON, DME) is not a COPD study.

## Cohort loader

`api/trialpilot_api/benchmark/cohort.py`

- `SOURCE_DIRS = (CACHE_DIR, REGISTRY_DIR)`: reads `data/fixtures/ctgov/NCT*.json` and
  `data/fixtures/peers/registry/NCT*.json`; `.meta.json` is still excluded.
- `source_paths()` keeps one file per NCT; the first directory wins, so the ctgov original is
  used whenever an NCT is in both. Tested by SHA-256 in
  `test_ctgov_original_wins_over_registry_copy_of_the_same_nct`.
- `source_file` stays the bare name for ctgov files (`NCT03930732.json`, unchanged contract);
  registry files are named relative to `data/fixtures` (`peers/registry/NCT01234567.json`)
  so the response says which cache a count came from.
- The `filename == nctId` check, `normalize_phase`, the 5-peer percentile threshold and the
  error envelope are unchanged. `PHASE2/PHASE3` is still never `PHASE3`.
- `condition_group` gained exactly two aliases (`chronic obstructive pulmonary disease copd`
  was already present):
  - `pulmonary disease chronic obstructive`
  - `copd chronic obstructive pulmonary disease`
- `METHODS["source"]` and `METHODS["condition_group"]` describe the two sources, the
  precedence rule and that no other disease is merged.
- `data/fixtures/peers/cohort.json` was regenerated (`python -m trialpilot_api.benchmark.cohort`),
  554 records.

## Counts

| Count | Value |
| --- | --- |
| Unique records in the combined cohort (550 registry-only + 4 ctgov) | 554 |
| Registry files with `normalize_phase == PHASE3` | 511 (the other 42 are `PHASE2/PHASE3`) |
| **Registry files with `normalize_phase == PHASE3` and `condition_group == copd`** | **439** |
| Same count in the combined cohort (ctgov preferred) | 439 |
| `PHASE2/PHASE3` + copd (excluded from the PHASE3 cohort) | 21 |
| Registry PHASE3 files whose first condition is not copd | 72 |
| **BOREAS (NCT03930732) peers** | **438** (439 minus itself; 2 from ctgov: NOTUS, NCT04535986) |

The 439 PHASE3 copd records by first-condition spelling: `chronic obstructive pulmonary
disease` 141, `pulmonary disease chronic obstructive` 165, `chronic obstructive pulmonary
disease copd` 72, `copd` 52, `copd chronic obstructive pulmonary disease` 9. Without the two
new aliases the cohort would have been 265.

Left out on purpose among the 72 PHASE3 non-copd files (first listed condition is not one
of the allowed spellings), e.g. emphysema 8, lung_diseases 7, asthma 6, pulmonary_hypertension 4, copd_exacerbation 3,
pulmonary_emphysema 2, chronic_obstructive_pulmonary_disorder 2,
chronic_obstructive_pulmonary_disease_severe 2, chronic_obstructive_pulmonary_disease_exacerbation 2,
moderate_to_very_severe_chronic_obstructive_pulmonary_disease 2, and single-study conditions.

BOREAS rows now get descriptive percentiles (cohort_n 438):

| Metric | BOREAS | available_n | Peer median | Percentile |
| --- | --- | --- | --- | --- |
| Primary outcomes | 1 | 438 | 1 | 37.4 |
| All outcomes | 17 | 438 | 6 | 84.4 |
| Inclusion lines | 8 | 411 | 5 | 74.3 |
| Exclusion lines | 11 | 406 | 11 | 51.5 |
| All eligibility lines | 19 | 435 | 17 | 58.3 |
| Countries | 24 | 388 | 2 | 93.2 |
| Sites | 275 | 391 | 34 | 92.8 |
| Target enrollment | not reported (ACTUAL) | 64 | 349 | none |

## Tests

`api/tests/test_benchmark.py`: 26 passed. Whole `api/` suite: 311 passed. `ruff check` clean.

- The sparse-cohort API test now runs against the ctgov-only cache through a `ctgov_only`
  fixture (2 peers, still `insufficient_peers`, no percentile).
- New: registry file naming/provenance, ctgov precedence, BOREAS full-cohort percentiles,
  the three COPD spellings, and emphysema / pulmonary hypertension / heart failure / asthma /
  COPD exacerbation not mapping to copd; Phase 2/3 COPD peers are disjoint from PHASE3 ones.
- Updated expected counts: uncached PHASE3 copd subject 439, pinned old version 438.

## Not done / notes

- Importer, designs and seeds are untouched: the registry files are not seeded as designs and
  there is no sponsor ranking.
- `load_cohort()` now reads 43 MB on every `/peers` request (about 0.4–0.5 s measured locally).
- Each `/peers` response lists 438 `peer_source_files` at the top level and in each of the 8
  rows. `PeerMirror.tsx` prints every row's list inline ("Peer files: …"), which will be long.

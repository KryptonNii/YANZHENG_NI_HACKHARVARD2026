# Added-country assumption correction

Date: 2026-10-17 (America/Toronto)

## Problem and implemented rule

The added-country lever previously rounded the median expected enrollment (a number of patients)
and used it as the number of sites to add per country. A median of 20 patients therefore created
20 sites for each country, mixing two different units.

Each `added_country_count` now adds exactly one assumed site:

- `id`: `assumed-country-{n}-site-1`; `country`: `assumed`.
- Its `expected_enrollment` is the median of positive, finite expected enrollment values from
  existing active sites, after excluded sites are removed.
- If none exists, the weight comes from `assume.design.patients_per_site`.
- Expected enrollment is used as an enrollment weight only; it does not set the number of sites.
- The warning `Added countries are assumptions, not registry sites.` is preserved verbatim.
  Both warnings and provenance notes explain one assumed site per country and the weight source.
- With the default `added_country_count=0`, the site construction and results are unchanged.

These are scenario assumptions, not registered sites or evidence that a named country can recruit
at the assumed rate. Forecast formulas and parameter values were not changed.

## Files changed for this correction

- `engine/trialpilot_engine/levers.py`: remove the enrollment-to-site-count conversion; add one
  site per country; disclose the assumption in warnings as well as notes.
- `engine/tests/test_levers.py`: verify that a median of 20 produces only two new sites for two
  countries, distributes patients to them, affects activity/cost, and leaves the source design
  unchanged. Cover invalid or absent enrollment values, exclusion before calculating the median,
  and identical scenario results when the zero default is explicit or omitted.
- `engine/tests/test_forecast.py`: verify two added countries contribute exactly two forecast
  sites with positive recruitment draws, keep retained sites' draws unchanged, and retain the
  default-lever golden forecast checks.
- `web/src/features/scenario/components/LeversPanel.tsx`: explain one assumed site per country
  and the enrollment-weight source next to the lever.
- `handoffs/COUNTRY_ASSUMPTION.md`: this receipt.

Other pre-existing working-tree changes were preserved. No commit, push, importer change,
contract change, forecast formula change, data update, or deployment was performed for this task.

## Validation

Executed from the `engine` directory using its existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/test_levers.py tests/test_forecast.py -p no:cacheprovider --basetemp C:\Users\ol735\AppData\Local\Temp\trialpilot-country-assumption-20261017-014125\pytest
```

Result: **68 passed in 1.02 seconds**, exit code 0.

Log: `C:\Users\ol735\AppData\Local\Temp\trialpilot-country-assumption-20261017-014125\engine-tests.txt`.

This is targeted engine validation of the correction, not a new full-project acceptance report.

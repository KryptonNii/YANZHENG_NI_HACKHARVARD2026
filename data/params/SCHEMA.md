# Parameter library format

Every number the engine uses lives here, as a `Parameter` (`contracts/trialpilot_contracts/models.py`).
A10 owns the YAML files; A1 owns this format and the loader (`trialpilot_contracts.params`).

**Rule (MASTER §2.1): never fabricate.** A value is either copied from an *opened* source
(`source_title`/`source_url` + `source_year`) or explicitly `assumption: true` with a `rationale` and a range.

## Files

- Any `*.yaml` / `*.yml` under `data/params/` (sub-folders allowed), grouped by topic, e.g.
  `emission_factors.yaml`, `costs.yaml`, `site_time.yaml`.
- Files whose name starts with `_` (e.g. `_example.yaml`) are examples/templates and are **not loaded** by default.

```yaml
# Optional: values merged into every entry of this file (an entry's own keys win).
defaults:
  source_title: "<exact title of the opened source>"
  source_url: "<URL you actually opened>"
  source_year: 2025                      # year of the edition you used
  region: "GB"

parameters:
  - id: ef.travel.car.average_km        # required, unique, lowercase dotted slug
    label: Average car, per km           # required, plain English
    value_low: 0.0                       # required, low <= mid <= high
    value_mid: 0.0                       #   (triangular distribution for Monte Carlo)
    value_high: 0.0
    unit: kg_co2e/km                     # required, "<internal unit>/<activity>"
    source_title: ...                    # optional (see rules)
    source_url: ...                      # optional; requires source_year
    source_year: 2024                    # optional int
    assumption: false                    # default false
    rationale: ...                       # required when assumption: true
    version: 1                           # bump when the value changes
    region: "GB"                         # ISO country code or "global" — QUOTE IT (YAML reads NO as false)
```

## Validation rules (enforced by `load_params`)

1. `id` is unique across all files and matches `^[a-z0-9_]+(\.[a-z0-9_]+)+$` (e.g. `cost.monitoring.onsite_visit`).
2. `value_low <= value_mid <= value_high`, all finite. A point estimate is low = mid = high.
3. `assumption: true` ⇒ non-empty `rationale`.
4. `source_url` set ⇒ `source_year` set.
5. `assumption: false` ⇒ `source_title` or `source_url`, and `source_year`.
6. No unknown keys (catches typos like `soruce_url`); `label` and `unit` non-empty; `version >= 1`.

All problems are reported at once. Check the library from the repo root:

```bash
uv run --project contracts python -m trialpilot_contracts.params data/params
# OK: 42 parameters (7 assumptions) in data/params, parameter_set_version=3f9a1c0b2d4e
```

## Units and ids

- Internal units (MASTER §3): money `usd`, time `hours` / `minutes`, carbon `kg_co2e`, distance `km`.
  Write the unit as `<unit>/<activity>`: `kg_co2e/km`, `usd/visit`, `minutes/procedure`, `kg_co2e/kg_shipped`.
- Id prefixes: `ef.` emission factors · `cost.` money · `time.` staff/patient time · `rate.` shares/probabilities ·
  `supply.` drug supply · `dist.` distances. Namespace by activity: `ef.travel.car.average_km`, `cost.monitoring.onsite_visit`.

## In code

```python
from trialpilot_contracts import load_params, param_set_version

params = load_params("data/params")            # dict[str, Parameter], sorted by id
version = param_set_version(params)            # -> ScenarioResult.parameter_set_version
```

`param_set_version` is the first 12 hex chars of sha256 over the id-sorted canonical JSON of every parameter,
so any change to any field gives a new version.

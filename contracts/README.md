# trialpilot_contracts

The shared data contract (§5 of the brief), verbatim, plus the parameter-library loader.
Owned by A1. Everyone else reads it and proposes changes in `handoffs/<agent>_CONTRACT_CHANGES.md`.

| File | What |
|---|---|
| `trialpilot_contracts/models.py` | §5 pydantic v2 models, verbatim |
| `trialpilot_contracts/constants.py` | §6 module ids (`CARBON_MODULES`, …), `ALERT_IMPACT_KEYS` |
| `trialpilot_contracts/params.py` | `load_params(dir)`, `param_set_version(params)`, CLI validator |
| `schema/*.json` | JSON Schema per model (generated) |
| `../web/src/contracts.ts` | TypeScript types (generated) |
| `CHANGELOG.md` | accepted / rejected contract changes |

## Use it from your package (run from the repo root)

```bash
uv add --project engine --editable ./contracts      # writes path = "../contracts" into engine/pyproject.toml
uv add --project api    --editable ./contracts
```

```python
from trialpilot_contracts import TrialDesign, Levers, ScenarioResult, MetricRange   # models
from trialpilot_contracts import load_params, param_set_version, CARBON_MODULES
# or, in your one shim file:  from trialpilot_contracts.models import *
```

TypeScript: `import type { ScenarioResult } from "../../contracts";` (from `web/src/features/<x>/`).

## Parameter library

```bash
uv run --project contracts python -m trialpilot_contracts data/params
```

Format and rules: `data/params/SCHEMA.md`.

## Regenerate / test (A1)

```bash
uv run --project contracts python contracts/gen.py          # write schema/ + web/src/contracts.ts
uv run --project contracts python contracts/gen.py --check  # CI: fail if stale
uv run --project contracts pytest contracts/tests
```

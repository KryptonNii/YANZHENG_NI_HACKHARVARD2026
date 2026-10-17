# Contract changelog

Decisions on `handoffs/*_CONTRACT_CHANGES.md`. Accepted changes are applied to `trialpilot_contracts/models.py`,
regenerated (`contracts/schema/`, `web/src/contracts.ts`) and listed here. A §2 rule is never weakened.

## v2 — 2026-10-16 21:40 ET — ACCEPTED: `MetricRange` can be unknown (A2 proposal 1, option b)
**Change.** `MetricRange.p10 / p50 / p90`: `float` → `Optional[float]` (TS `number | null`). Still required keys.
- All three numbers **or** all three `null` (= unknown). Partly known is rejected by pydantic *and* by the JSON Schema (`anyOf`).
- `NaN` is normalised to `null`; `±inf` is rejected ("must be a finite number, or null for unknown").
- Python helper: `MetricRange.known` (`p50 is not None`).

**Why accepted.** §2 rule 2 says unknown ≠ zero and must be reported as missing. Option (a) — NaN serialised as `null` —
is broken today: the API would emit `{"p10":null,…}` that the v1 contract itself rejects on read-back
(`ValidationError: Input should be a valid number`, checked 21:32 ET), and the TS type promised `number`. Option (b) puts
"unknown" in the type, so every consumer is forced (by mypy / tsc) to handle it instead of showing `NaN` or `0`. This makes the
rule stricter, not weaker. Cheaper now than at integration.

**Migration for consumers.**
- Engine (A2/A3): return `MetricRange(p10=None, p50=None, p90=None, unit=…)` (or NaN, which becomes None) when a term
  can't be computed, **and** add a `ScenarioResult.warnings` entry naming the missing parameter / input. Never return 0.
- Python readers (A5 exports, A6 impacts, A10 science): `r.p50` is `float | None`; check `r.known` before arithmetic, and
  print "unknown" (never 0 / blank) in CSV/PDF/tables.
- Web (A8/A9): `number | null`; render "Unknown" plus the warning/missing input, never `NaN`, `0` or an empty bar.
  A8: switching `src/app/contracts.ts` to `export * from "../contracts";` picks up the new type.
- Unaffected: every other model, all field names, units, JSON shape of known values.

**Tests.** `contracts/tests/test_metric_range_unknown.py` (+ `fixtures/invalid/MetricRange.partly_unknown.json`): 78 passed.

## v1 — 2026-10-16 21:07 ET
- Initial contract: §5 models verbatim, §6 constants, parameter loader.

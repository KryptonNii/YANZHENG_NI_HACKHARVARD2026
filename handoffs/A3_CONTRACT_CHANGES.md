# A3 — contract change record (for A1)

## 1. `MetricRange.unit` includes `"count"` — ACCEPTED in contract v4

**Request.** `SupplyResult.shipments` and `emergency_shipments` are counts of depot-to-site
shipments. They are not kits. v1–v3 had no `"count"` unit, so A3 built those ranges with
`MetricRange.model_construct` and they would have failed a re-validation.

**Status.** Accepted in `contracts/CHANGELOG.md` v4 (2026-10-16). The unit literal is
`"usd" | "hours" | "kg_co2e" | "months" | "patients" | "percent" | "kits" | "count"`.

**What A3 does now.** `_count_range` and the no-drug shipment zeros call `MetricRange(...)`.
They go through the normal validators (finite numbers, P10 ≤ P50 ≤ P90, all three present or
all three null). `engine/tests/test_supply.py` re-validates `shipments.model_dump()`. Shipment
counts are not relabelled as kits.

No further change is requested for this unit.

## 2. No new contract request this pass

`ForecastView` / `SupplyView` on `ScenarioResult` were accepted in the same v4 entry (A8's
proposal). A3's `to_dict()` is a superset; extra keys are ignored by those views. Producers may
pass the display subset. This pass did not add fields the contract has to grow.

Downsampling is reported on A3's own result (`draws_requested`, `draws_used`, curve draw counts
in warnings and provenance inputs). It is not a contract field.

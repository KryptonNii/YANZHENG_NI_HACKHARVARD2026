# A8 — contract change proposals (for A1)

No new proposal this round.

## Landed in contract v4

`contracts/CHANGELOG.md` accepted `ScenarioResult.forecast`, `ScenarioResult.supply`, and `MetricRange.unit` `"count"`.
`web/src/contracts.ts` is A1’s generated file. `web/src/app/contracts.ts` re-exports it and is not a second copy.

The UI reads those fields when the compute response includes them. A null `forecast` or `supply`, or a forecast with no enrollment curve, is shown as missing. The page does not draw a curve from `duration_months`, and it does not relabel shipment `count` as kits.

`MetricRange` p10/p50/p90 are `number | null`. The cards print unknown, not zero. `Signature.signer_name` and `ApprovalRequest.record_hash`, `created_at`, and `title` are required by the generated types.

## Final v5 alignment (2026-10-17)

Generated contracts remain backend-owned. The final frontend uses v5 ForecastView/SupplyView, carries requested/used/curve draw counts and nested provenance, and preserves nullable metrics. A missing design version or strong ETag is an explicit error; no v1 fallback is invented. Compute/save/compare are pinned to an explicit design version; mutations include If-Match. No additional contract change is requested. Source commit e425ca2, integrated with backend f91cdb2 and verified at e5c386b. See FRONTEND_FINAL.md.

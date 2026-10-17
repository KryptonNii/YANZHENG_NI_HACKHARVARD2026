# A6 contract proposal

## Add a CTMS site activation event

The operations feed needs to show when CTMS opens a site to enrollment, including backup sites activated after an intervention. The shared `OpsEvent.source_system` already permits `CTMS`. This proposal asked for a site-activation event type; contract v4 accepted it (see Status).

Proposed addition:

- Add `site_activated` to `EventType` and the generated `OpsEvent` JSON schema.
- Payload: `activation_date`, `country`, `region`, and `status` (initially `open_to_enrollment`).
- Keep `site_id` populated and `source_system="CTMS"`; keep the existing `simulated` label.

## Status

Accepted in contract v4: `site_activated` is on `EventType` and in the generated `OpsEvent` schema. A6 now emits CTMS site opens, including backup sites opened by an intervention, as `site_activated` with `site_id` set, `source_system="CTMS"`, `simulated=true`, and payload `activation_date`, `country`, `region`, `status="open_to_enrollment"`. The `vendor_milestone` workaround is no longer used for site activation. Vendor milestone reports stay `vendor_milestone` from `VENDOR`.

Rechecked 2026-10-16 ET against the current contract models and a live `GET /api/ops/demo-40/events?site_id=S39` event. `OpsEvent` still accepts that payload, and the ops adapter still calls A3 as `forecast(design, levers, params, seed, draws)` and `update_with_actuals(prior, design, actual_enrolment_by_site, params, seed)`. No further contract change.

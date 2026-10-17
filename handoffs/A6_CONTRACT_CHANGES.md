# A6 contract proposal

## Add a CTMS site activation event

The operations feed needs to show when CTMS opens a site to enrollment, including backup sites activated after an intervention. The shared `OpsEvent.source_system` already permits `CTMS`, but `EventType` has no site activation value.

Proposed addition:

- Add `site_activated` to `EventType` and the generated `OpsEvent` JSON schema.
- Payload: `activation_date`, `country`, `region`, and `status` (initially `open_to_enrollment`).
- Keep `site_id` populated and `source_system="CTMS"`; keep the existing `simulated` label.

Current A6 behavior stays within the existing contract by representing activation as a completed, non-critical-path `vendor_milestone`. A1 owns the shared contract, so this file records the request without changing it.

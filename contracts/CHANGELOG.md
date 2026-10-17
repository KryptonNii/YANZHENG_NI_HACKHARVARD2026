# Contract changelog

Decisions on `handoffs/*_CONTRACT_CHANGES.md`. Accepted changes are applied to `trialpilot_contracts/models.py`,
regenerated (`contracts/schema/`, `web/src/contracts.ts`) and listed here. A §2 rule is never weakened.

## v5 — 2026-10-17 ET — sampling and A3 provenance

ForecastView and SupplyView retain nullable `draws_requested` and `draws_used`;
ForecastView also has nullable `curve_draws_used`. Null means the producer or
historical record did not report a count. The engine supplies actual counts;
no sample budgets or threshold changed. Both views retain `provenance` items so
assumptions and source parameter references survive save, record hash and export.
The API now propagates both producers' warnings. These additions are optional
for older producers; existing unknown MetricRange percentiles remain null.

## Recorded rules — 2026-10-16 ET — no schema change

### A4 deterministic UUIDv5 — ACCEPTED as a producer convention
`id` fields stay `str`. The contract does not check the UUID version nibble, and it does not reject the
existing non-UUID fixture ids (`site-1`, `sig1`, and the same shape in the valid fixtures). Both UUID4 and
UUIDv5 strings already validate. No consumer migration.

**Rule.**
- Records created in the app may be UUID4 strings. A6's operations feed formats a deterministic SHA-256
  prefix as RFC 4122 version 4 (`api/trialpilot_api/ops/simulator.py` `event_uuid`). Fixture and test ids
  may remain plain strings.
- Records derived from an external identifier are UUIDv5 in a fixed namespace. A4's importer
  (`api/trialpilot_api/importers/ctgov.py`) uses namespace `6f1c3c3e-8a43-4d0e-9b55-1f2a5e0c7a11`:
  - `TrialDesign.id = uuid5(namespace, "ctgov:<NCT>")`
  - `Site.id = uuid5(namespace, "ctgov:<NCT>:site:<key>#<n>")` where `<n>` is the 1-based count of that site key
- Protocol extraction ids (`api/trialpilot_api/importers/protocol_extract.py`) use a second namespace,
  `0b8f5d0e-5a3c-4c55-9f7e-2c1d7a9e4b21`. They are not `TrialDesign.id`.
  - live extract: `uuid5(namespace, "<pdf_sha256>:<method>:<model>")`
  - BOREAS build-time cache: `uuid5(namespace, "<pdf_sha256>:transcription:<model>")`
- Re-importing the same study must keep the same design and site ids. The name strings above are the rule;
  do not hash the NCT id alone or the PDF sha256 alone.

**Why no schema change.** Tightening `id` to a UUID type would reject current fixtures and every in-app string
id. A4 already emits values that pass `uuid.UUID(...)`. Search at the time of the proposal found no consumer
that checks the version nibble.

### A10 `Visit.patient_share` — DEFERRED (known limitation)
Not added. `handoffs/A10_CONTRACT_CHANGES.md` asks for `Visit.patient_share: float = 1.0` so a visit can apply
to a fraction of `enrollment_target`. PRIMETIME's five mammogram visits would use 1623/1962. The current
`Visit` model has no such field, so every scheduled visit is counted for the full cohort.

This needs the engine activity math, the science designs, and any API or UI that builds visits to change
together. That sync is out of scope for this integration pass. The published engine gaps stay as A10 and A2
recorded them. Do not invent a share in one module only.

## v4 — 2026-10-16 ET — ACCEPTED: forecast / supply views, count unit, site activation (A3, A6, A8)
**Accepted changes.**
- A3's `handoffs/A3.md` unit request and A8's unit note: add `"count"` to `MetricRange.unit`.
  Shipment counts can now pass normal validation; they must not be relabelled as kits.
- A8 `handoffs/A8_CONTRACT_CHANGES.md`: add `ScenarioResult.forecast: Optional[ForecastView] = None`
  and `supply: Optional[SupplyView] = None`. Existing inputs may omit both or send null.
  `ForecastView` contains `months_to_full_enrollment: MetricRange`, `milestone_dates: dict[str, MetricRange]`
  (default empty) and `enrollment_curve: list[tuple[float, float, float, float]]` (default empty),
  with each JSON row `[month, p10, p50, p90]` representing cumulative patients.
  `SupplyView` requires `kits_needed`, `kits_produced`, `kits_wasted`, `waste_share`, `shipments`
  (all `MetricRange`) and `stockout_probability: float` (0..1, required, no zero default).
  Both views ignore extra producer fields, as A8 proposed. They are re-exported by the package.
- A6 `handoffs/A6_CONTRACT_CHANGES.md`: add `"site_activated"` to `EventType`.
  A6's producer convention is a populated `site_id`, `source_system="CTMS"`, the existing `simulated` label,
  and payload keys `activation_date`, `country`, `region`, `status="open_to_enrollment"`.
  The existing generic `OpsEvent.payload: dict` is unchanged.
- Generator: map tuple annotations to TypeScript tuples, so enrollment rows retain exactly four positions.
  Regenerate all schemas and `web/src/contracts.ts` from the models.

**Why accepted.** These are additive enum values and optional scenario fields; older scenario inputs remain valid.
Every nested `MetricRange` still requires all three numbers or all three null: unknown is never replaced with zero.
NaN normalization and infinity rejection are unchanged. Missing detail remains `None`, and missing stockout risk is
rejected inside a supplied `SupplyView` rather than silently converted to 0. No changes to science-check JSON.

**Rejected proposals.** None among the A3 count request, A6 site activation proposal and A8 forecast/supply proposal.
No other contract proposals were triaged in this scoped update.

**Consumer notes.** Producers may pass the display subset of A3's `to_dict()` output; additional producer keys are ignored.
The contract does not synthesize these views. Consumers must handle null details and unknown nested percentiles.
Generated TypeScript describes serialized output: both detail keys are present and nullable after model serialization.

**Validation.** Regression tests cover omitted/null details, nested unknowns (including count), partial-unknown rejection
in pydantic and JSON Schema, A3-style extra fields, four-number curve rows, stockout bounds and the CTMS activation event.

## v3 — 2026-10-16 21:44 ET — ACCEPTED (stricter than proposed): signature / approval fields (A7 proposals 1–3)
**Change.**
- `Signature.signer_name: str` — **required** (A7 proposed `Optional[str] = None`).
- `ApprovalRequest.record_hash: str` — required, as proposed.
- `ApprovalRequest.created_at: datetime` — **required** (A7 proposed optional).
- `ApprovalRequest.title: Optional[str] = None` — optional, as proposed.
- **Not** added to the contract: `current_record_hash`, `record_changed`, `manifestation`. They are computed per read and
  stay in A7's API *view* responses (a superset of the contract model), which is fine.

**Why.** 21 CFR 11.50(a): signed electronic records "shall contain" the printed name of the signer, the date and time,
and the meaning (text checked by A1 at https://www.law.cornell.edu/cfr/text/21/11.50 on 2026-10-16; eCFR blocked automated
fetches). The contract already had time (`signed_at`) and meaning, but not the printed name. Making it optional would let
the contract accept a signature that lacks a required element, so it is required (§2 rule 5: compliance enforced in code).
`record_hash` on the request binds the approval to one exact record version, which is the core of rule 5. Every approval
request has a submission time, and the queue sorts on it, so `created_at` is required too. All data already exists
where these models are built (signatures table stores `display_name`; approvals table stores `record_hash`, `created_at`, `title`).

**Migration for consumers (breaking for constructors only).**
- A7 `api/trialpilot_api/compliance/esign.py`: both `Signature(...)` calls need `signer_name=` (row `display_name` /
  `user.display_name`). `workflow.py` `_to_model`: add `record_hash=row["record_hash"]`, `created_at=parse_utc(row["created_at"])`,
  `title=row.get("title")`.
- A5 `api/trialpilot_api/compliance_adapter.py` stub `ApprovalRequest(...)`: add `record_hash=` (required, not None) and `created_at=`.
- A8/A9 (web): `Signature.signer_name` and `ApprovalRequest.record_hash` / `created_at` are now always present; `title` is
  `string | null`. Mock data that builds these objects must include them.
- Readers of JSON are unaffected (new fields only).

**Tests.** valid fixtures updated; new invalid fixtures `Signature.missing_printed_name`,
`ApprovalRequest.missing_record_hash`, `ApprovalRequest.missing_created_at`: 81 passed.

## v2 — 2026-10-16 21:33 ET — ACCEPTED: `MetricRange` can be unknown (A2 proposal 1, option b)
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

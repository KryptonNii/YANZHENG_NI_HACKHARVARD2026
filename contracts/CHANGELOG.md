# Contract changelog

Decisions on `handoffs/*_CONTRACT_CHANGES.md`. Accepted changes are applied to `trialpilot_contracts/models.py`,
regenerated (`contracts/schema/`, `web/src/contracts.ts`) and listed here. A §2 rule is never weakened.

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

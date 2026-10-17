# A7 — contract change proposals (for A1)

Until decided, A7 keeps the §5 models exactly and returns the extra fields only in API *view*
responses (a superset of the contract models), so nothing breaks either way.

## 1. `Signature.signer_name: Optional[str] = None` (printed name)
- Why: 21 CFR 11.50(a)(1) requires the signer's **printed name** in the signature manifestation
  (verified on eCFR 2026-10-16). §5 `Signature` only has `signer` (a username).
- Today: stored in the `signatures` table and returned as `signer_name` + `manifestation` in
  `/api/approvals/{id}` and `/api/signatures` (A8 already types this as `SignatureView`).

## 2. `ApprovalRequest.record_hash: str` (hash of the record version submitted)
- Why: an approval is for one exact record version; signatures bind to it, and the UI needs it to
  show "record changed since submission". §5 `ApprovalRequest` has no hash.
- Today: returned as `record_hash`, `current_record_hash`, `record_changed` in the approval view.

## 3. (optional) `ApprovalRequest.title: Optional[str] = None`, `created_at: Optional[datetime] = None`
- Why: the approvals queue (A9) needs something human-readable and sortable.
- Today: returned in the approval view.

No change requested to `AuditEntry` or `Role`.

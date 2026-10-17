# Roles and permission matrix

Source of truth: `api/trialpilot_api/compliance/roles.py` (`PERMISSIONS`, `APPROVER_ROLES`) and
`workflow.py` (`REQUIRED_MEANINGS`). The test `validation/tests/test_roles_doc.py` fails if this
table and the code disagree.

## Demo users (fictional; demo-only PINs)

| Username | Printed name | Role | Demo PIN |
|---|---|---|---|
| alex.author | Alex Author | author | 1111 |
| riley.reviewer | Riley Reviewer | reviewer | 2222 |
| sam.qa | Sam QA | qa | 3333 |
| admin | Admin | admin | 9999 |
| val.viewer | Val Viewer | viewer | 0000 |

Demo identity: the API trusts the `X-User` header to say who is acting (no login in this demo). What
that user may do comes from the registry above, never from the request. Every signature re-checks the
PIN (stored as an argon2id hash of `TP_SECRET_PEPPER` + PIN). Override PINs with
`TP_DEMO_PINS="alex.author=1234,..."`. A real deployment would replace this with SSO + per-user
credentials.

## Permission matrix

| Action | author | reviewer | qa | admin | viewer |
|---|---|---|---|---|---|
| audit.read | ✓ | ✓ | ✓ | ✓ | ✓ |
| audit.verify | ✓ | ✓ | ✓ | ✓ | ✓ |
| approval.submit | ✓ | ✓ | ✓ | – | – |
| approval.reject | – | ✓ | ✓ | – | – |
| sign.authored | ✓ | ✓ | ✓ | – | – |
| sign.reviewed | – | ✓ | ✓ | – | – |
| sign.approved | – | – | ✓ | – | – |
| sign.executed | ✓ | ✓ | ✓ | – | – |
| sign.verified | – | ✓ | ✓ | – | – |
| validation.package.read | ✓ | ✓ | ✓ | ✓ | ✓ |

## Approval workflows (signed in this order)

| Record type | Required meanings | Final approver role |
|---|---|---|
| scenario | reviewed → approved | qa |
| test_protocol | reviewed → approved | qa |
| validation_report | approved | qa |
| change_record | reviewed → approved | qa |

## Segregation of duties (enforced in `workflow.py`, on top of the matrix)

| Rule | Error |
|---|---|
| The author can't sign `reviewed`/`approved` on, or reject, their own record | 403 `self_approval_forbidden` |
| Steps must follow the order above | 409 `out_of_order` |
| One person signs at most one step of a request | 403 `duplicate_signer` |
| A record that changed since submission can't be signed | 409 `record_changed` |
| AI actors (`ai:*`) can never sign | 403 `ai_signature_forbidden` |
| Wrong PIN / 3rd wrong PIN (5-minute lock) | 401 `invalid_credential` / 423 `account_locked` |

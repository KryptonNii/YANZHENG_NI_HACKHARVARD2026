"""Electronic signatures (21 CFR Part 11 style).

- Re-authentication at signing: the signer's PIN is checked (argon2id + pepper). Wrong PIN → 401;
  the 3rd consecutive failure locks the signer for 5 minutes → 423. Failures and lockouts are audited.
- A signature binds to the hash of the exact record signed. On read, `signature_status` compares it
  with the record's current hash: a changed record shows its signatures as invalid.
- Manifestation (printed name, UTC date/time, meaning) per 21 CFR 11.50 via `manifestation()`.
- AI actors (`ai:*`) can never sign.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from . import audit, records, roles
from ._contracts import MEANINGS, Signature
from .config import LOCKOUT_SECONDS, MAX_FAILED_ATTEMPTS
from .errors import ComplianceError
from .hashing import iso_utc, now, parse_utc, record_hash
from .store import Store, get_store


def reauthenticate(signer: str, credential: str, *, store: Store | None = None) -> roles.User:
    """Check the signer's PIN. Raises 401 / 423; audits failures and lockouts."""
    st = store or get_store()
    if roles.is_ai_actor(signer):
        audit.append(signer, "viewer", "esign.denied", "user", signer, None, None,
                     "AI actors cannot sign", store=st)
        raise ComplianceError(403, "ai_signature_forbidden",
                              "AI may draft text but can never sign records.")
    row = st.query_one(
        "SELECT username, display_name, role, pin_hash, failed_attempts, locked_until"
        " FROM compliance_users WHERE username = ?",
        (signer,),
    )
    if row is None:
        raise ComplianceError(401, "invalid_credential", "Unknown user or wrong PIN.")
    current = now()
    if row["locked_until"] and parse_utc(row["locked_until"]) > current:
        audit.append(signer, row["role"], "esign.attempt_while_locked", "user", signer, None, None,
                     f"locked until {row['locked_until']}", store=st)
        raise ComplianceError(
            423, "account_locked",
            "Too many wrong PINs. Signing is locked for this user; try again later.",
            {"locked_until": row["locked_until"]},
        )
    if not credential or not roles.check_pin(row["pin_hash"], credential):
        failed = int(row["failed_attempts"]) + 1
        if failed >= MAX_FAILED_ATTEMPTS:
            until = iso_utc(current + timedelta(seconds=LOCKOUT_SECONDS))
            with st.tx() as conn:
                conn.execute(
                    "UPDATE compliance_users SET failed_attempts = 0, locked_until = ?"
                    " WHERE username = ?",
                    (until, signer),
                )
            audit.append(signer, row["role"], "esign.auth_failed", "user", signer, None, None,
                         f"wrong PIN (attempt {failed} of {MAX_FAILED_ATTEMPTS})", store=st)
            audit.append(signer, row["role"], "esign.lockout", "user", signer, None, None,
                         f"{MAX_FAILED_ATTEMPTS} wrong PINs; locked until {until}", store=st)
            raise ComplianceError(
                423, "account_locked",
                f"{MAX_FAILED_ATTEMPTS} wrong PINs. Signing is locked for "
                f"{LOCKOUT_SECONDS // 60} minutes.",
                {"locked_until": until},
            )
        with st.tx() as conn:
            conn.execute(
                "UPDATE compliance_users SET failed_attempts = ? WHERE username = ?",
                (failed, signer),
            )
        audit.append(signer, row["role"], "esign.auth_failed", "user", signer, None, None,
                     f"wrong PIN (attempt {failed} of {MAX_FAILED_ATTEMPTS})", store=st)
        raise ComplianceError(
            401, "invalid_credential", "Unknown user or wrong PIN.",
            {"attempts_left": MAX_FAILED_ATTEMPTS - failed},
        )
    if row["failed_attempts"] or row["locked_until"]:
        with st.tx() as conn:
            conn.execute(
                "UPDATE compliance_users SET failed_attempts = 0, locked_until = NULL"
                " WHERE username = ?",
                (signer,),
            )
    return roles.User(row["username"], row["display_name"], row["role"])


def _row_to_signature(row: Any) -> Signature:
    return Signature(
        id=row["id"],
        signer=row["signer"],
        signer_name=row["signer_name"],
        role=row["role"],
        meaning=row["meaning"],
        signed_at=parse_utc(row["signed_at"]),
        record_type=row["record_type"],
        record_id=row["record_id"],
        record_hash=row["record_hash"],
    )


def record_signature(
    user: roles.User,
    meaning: str,
    record_type: str,
    record_id: str,
    record_hash_value: str,
    *,
    approval_id: str | None = None,
    reason: str | None = None,
    store: Store | None = None,
) -> Signature:
    """Persist a signature for an already re-authenticated user and audit it.

    Callers must have run `reauthenticate` and all authorisation checks first.
    """
    st = store or get_store()
    sig_id = str(uuid.uuid4())
    signed_at = iso_utc(now())
    with st.tx() as conn:
        conn.execute(
            "INSERT INTO signatures (id, approval_id, signer, signer_name, role, meaning, signed_at,"
            " record_type, record_id, record_hash, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (sig_id, approval_id, user.username, user.display_name, user.role, meaning, signed_at,
             record_type, record_id, record_hash_value, reason),
        )
        sig = Signature(
            id=sig_id, signer=user.username, signer_name=user.display_name, role=user.role,
            meaning=meaning,  # type: ignore[arg-type]
            signed_at=parse_utc(signed_at), record_type=record_type, record_id=record_id,
            record_hash=record_hash_value,
        )
        audit.append(user.username, user.role, "signature.create", "signature", sig_id, None,
                     record_hash(sig), reason or f"{meaning} {record_type}/{record_id}", store=st)
    return sig


def sign(
    record_type: str,
    record_id: str,
    record_hash: str,
    signer: str,
    role: str,
    meaning: str,
    credential: str,
    *,
    reason: str | None = None,
    store: Store | None = None,
) -> Signature:
    """Sign a record outside an approval workflow (e.g. `executed` on a test run)."""
    st = store or get_store()
    if meaning not in MEANINGS:
        raise ComplianceError(422, "invalid_meaning", f"Unknown meaning {meaning!r}.",
                              {"allowed": list(MEANINGS)})
    if not record_hash or len(record_hash) != 64:
        raise ComplianceError(422, "invalid_record_hash",
                              "record_hash must be a sha256 hex digest.")
    user = reauthenticate(signer, credential, store=st)
    if role != user.role:
        raise ComplianceError(403, "role_mismatch",
                              f"{signer} is registered as {user.role!r}, not {role!r}.")
    if not roles.can(user.role, f"sign.{meaning}"):
        audit.append(user.username, user.role, "esign.denied", record_type, record_id, None, None,
                     f"role {user.role} may not sign '{meaning}'", store=st)
        raise ComplianceError(403, "role_not_permitted",
                              f"Role {user.role!r} may not sign with meaning {meaning!r}.")
    return record_signature(user, meaning, record_type, record_id, record_hash,
                            reason=reason, store=st)


def list_signatures(
    *,
    record_type: str | None = None,
    record_id: str | None = None,
    approval_id: str | None = None,
    store: Store | None = None,
) -> list[Signature]:
    st = store or get_store()
    clauses, params = [], []
    for col, val in (("record_type", record_type), ("record_id", record_id),
                     ("approval_id", approval_id)):
        if val is not None:
            clauses.append(f"{col} = ?")
            params.append(val)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = st.query(f"SELECT * FROM signatures{where} ORDER BY signed_at ASC, rowid ASC", params)
    return [_row_to_signature(r) for r in rows]


def display_name(username: str, store: Store | None = None) -> str:
    user = roles.get_user(username, store)
    return user.display_name if user else username


def manifestation(sig: Signature, store: Store | None = None) -> str:
    """Human-readable signature manifestation: printed name, UTC date/time, meaning (§11.50)."""
    when = sig.signed_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f"{sig.signer_name} ({sig.signer}, {sig.role}) — "
        f"{sig.meaning.upper()} — {when} — {sig.record_type}/{sig.record_id} "
        f"sha256:{sig.record_hash[:12]}…"
    )


def signature_status(
    sig: Signature, *, current: str | None | object = ..., store: Store | None = None
) -> dict[str, Any]:
    """`{valid, reason, current_record_hash}`; valid is None when the record can't be resolved."""
    cur = (
        records.current_hash(sig.record_type, sig.record_id, store=store)
        if current is ...
        else current
    )
    if cur is None:
        return {"valid": None, "reason": "record not resolvable; validity unknown",
                "current_record_hash": None}
    if cur != sig.record_hash:
        return {"valid": False, "reason": "record changed after signing",
                "current_record_hash": cur}
    return {"valid": True, "reason": None, "current_record_hash": cur}


def signature_view(sig: Signature, *, current: str | None | object = ...,
                   store: Store | None = None) -> dict[str, Any]:
    data = sig.model_dump(mode="json")
    data["manifestation"] = manifestation(sig, store)
    data.update(signature_status(sig, current=current, store=store))
    return data

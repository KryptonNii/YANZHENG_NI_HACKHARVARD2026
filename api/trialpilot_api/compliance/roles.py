"""Demo users, roles and the permission matrix (documented in `validation/ROLES.md`).

Identity in this demo is simple: the API trusts the `X-User` header to say *who is acting*
(demo identity only). What a user may do comes from the role registered here, never from the
request, and every signature re-authenticates the signer with their PIN.

Demo PINs are demo credentials for fictional users (listed in `validation/ROLES.md`); override them
with `TP_DEMO_PINS="alex.author=1234,sam.qa=5678"`. PINs are stored as argon2id hashes of
`pepper + PIN`, with the pepper from `TP_SECRET_PEPPER`.
"""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .config import AI_ACTOR_PREFIX, env, pepper
from .errors import ComplianceError
from .hashing import sha256_hex
from .store import Store, get_store


@dataclass(frozen=True)
class DemoUser:
    username: str
    display_name: str
    role: str
    default_pin: str


DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser("alex.author", "Alex Author", "author", "1111"),
    DemoUser("riley.reviewer", "Riley Reviewer", "reviewer", "2222"),
    DemoUser("sam.qa", "Sam QA", "qa", "3333"),
    DemoUser("admin", "Admin", "admin", "9999"),
    DemoUser("val.viewer", "Val Viewer", "viewer", "0000"),
)

# ---- permission matrix ---------------------------------------------------------------------------
# action -> roles allowed. Segregation of duties on top of this (signer != author, one signer per
# meaning, order) is enforced in workflow.py.
PERMISSIONS: dict[str, frozenset[str]] = {
    "audit.read": frozenset({"author", "reviewer", "qa", "admin", "viewer"}),
    "audit.verify": frozenset({"author", "reviewer", "qa", "admin", "viewer"}),
    "approval.submit": frozenset({"author", "reviewer", "qa"}),
    "approval.reject": frozenset({"reviewer", "qa"}),
    "sign.authored": frozenset({"author", "reviewer", "qa"}),
    "sign.reviewed": frozenset({"reviewer", "qa"}),
    "sign.approved": frozenset({"qa"}),
    "sign.executed": frozenset({"author", "reviewer", "qa"}),
    "sign.verified": frozenset({"reviewer", "qa"}),
    "validation.package.read": frozenset({"author", "reviewer", "qa", "admin", "viewer"}),
}

# Extra restriction per record type: who may give the final "approved" signature.
APPROVER_ROLES: dict[str, frozenset[str]] = {
    "scenario": frozenset({"qa"}),
    "test_protocol": frozenset({"qa"}),
    "validation_report": frozenset({"qa"}),
    "change_record": frozenset({"qa"}),
}

_hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)  # OWASP argon2id minimum


def is_ai_actor(username: str) -> bool:
    return username.startswith(AI_ACTOR_PREFIX)


def can(role: str, action: str) -> bool:
    return role in PERMISSIONS.get(action, frozenset())


def _configured_pins() -> dict[str, str]:
    pins = {u.username: u.default_pin for u in DEMO_USERS}
    raw = env("TP_DEMO_PINS")
    for part in raw.split(","):
        if "=" in part:
            name, pin = part.split("=", 1)
            if name.strip() in pins and pin.strip():
                pins[name.strip()] = pin.strip()
    return pins


def _pepper_id() -> str:
    return sha256_hex(pepper()[0])[:12]


def hash_pin(pin: str) -> str:
    return _hasher.hash(pepper()[0] + pin)


def check_pin(pin_hash: str, pin: str) -> bool:
    try:
        return _hasher.verify(pin_hash, pepper()[0] + pin)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def seed_demo_users(store: Store) -> None:
    """Insert the demo users once; re-hash a demo PIN only if the pepper changed."""
    pins = _configured_pins()
    pid = _pepper_id()
    with store.tx() as conn:
        for u in DEMO_USERS:
            row = conn.execute(
                "SELECT pepper_id FROM compliance_users WHERE username = ?", (u.username,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO compliance_users (username, display_name, role, pin_hash, pepper_id)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (u.username, u.display_name, u.role, hash_pin(pins[u.username]), pid),
                )
            elif row["pepper_id"] != pid:
                conn.execute(
                    "UPDATE compliance_users SET pin_hash = ?, pepper_id = ? WHERE username = ?",
                    (hash_pin(pins[u.username]), pid, u.username),
                )
    store.seeded = True


@dataclass(frozen=True)
class User:
    username: str
    display_name: str
    role: str


def get_user(username: str | None, store: Store | None = None) -> User | None:
    if not username:
        return None
    st = store or get_store()
    row = st.query_one(
        "SELECT username, display_name, role FROM compliance_users WHERE username = ?",
        (username,),
    )
    return User(row["username"], row["display_name"], row["role"]) if row else None


def require_identity(username: str | None) -> str:
    """The acting username; 401 `identity_required` when none was sent (no registry lookup)."""
    if not username:
        raise ComplianceError(
            401, "identity_required", "Send the acting user in the X-User header (demo identity)."
        )
    return username


def require_user(username: str | None, store: Store | None = None) -> User:
    username = require_identity(username)
    user = get_user(username, store)
    if user is None:
        raise ComplianceError(
            403,
            "unknown_user",
            f"{username!r} is not a registered user.",
            {"known_users": [u.username for u in DEMO_USERS]},
        )
    return user


def list_users(store: Store | None = None) -> list[User]:
    st = store or get_store()
    rows = st.query(
        "SELECT username, display_name, role FROM compliance_users ORDER BY rowid ASC"
    )
    return [User(r["username"], r["display_name"], r["role"]) for r in rows]


def permission_matrix() -> dict[str, list[str]]:
    return {action: sorted(roles) for action, roles in PERMISSIONS.items()}

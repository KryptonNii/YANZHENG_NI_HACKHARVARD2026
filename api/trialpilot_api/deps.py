"""Request dependencies: demo identity and shared services.

DEMO IDENTITY ONLY: the acting user comes from the `X-User` header. There is no login; this is a
prototype. Signing (A7) re-authenticates with a PIN.

The role comes from A7's user registry (URS-023), never from the request: `X-Role` is optional,
and if it is sent it must match the registered role (403 `role_mismatch`); an unregistered user
gets 403 `unknown_user`. Only when A7's package is not importable (stub mode, reported by
`/api/health` as `compliance.roles = "header"`) is the `X-Role` header used as the role.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fastapi import Header, Request

from ._contracts import ROLES
from .errors import ApiError

_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")


@dataclass(frozen=True)
class Identity:
    user: str
    role: str


def resolve_identity(
    request: Request, x_user: str | None, x_role: str | None
) -> Identity | None:
    if not x_user:
        return None
    if not _USER_RE.match(x_user):
        raise ApiError(400, "invalid_identity",
                       "X-User must be 1-64 characters: letters, digits, '.', '_', '@' or '-'.")
    claimed = x_role.strip().lower() if x_role and x_role.strip() else None
    if claimed is not None and claimed not in ROLES:
        raise ApiError(400, "invalid_identity", f"X-Role must be one of {', '.join(ROLES)}.",
                       {"role": x_role})
    compliance = getattr(getattr(request.app.state, "services", None), "compliance", None)
    if compliance is not None and compliance.has_user_registry:
        registered = compliance.registered_role(x_user)
        if registered is None:
            raise ApiError(403, "unknown_user", f"{x_user!r} is not a registered user.",
                           {"user": x_user})
        if claimed is not None and claimed != registered:
            raise ApiError(403, "role_mismatch",
                           f"{x_user!r} is registered as {registered!r}, not {claimed!r}. "
                           "The role comes from the user registry, not the request.",
                           {"user": x_user, "registered_role": registered,
                            "claimed_role": claimed})
        return Identity(user=x_user, role=registered)
    return Identity(user=x_user, role=claimed or "author")


def current_identity(
    request: Request,
    x_user: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> Identity | None:
    return resolve_identity(request, x_user, x_role)


def require_editor(
    request: Request,
    x_user: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> Identity:
    """Mutations need a registered demo identity whose role may change data (not `viewer`)."""
    ident = resolve_identity(request, x_user, x_role)
    if ident is None:
        raise ApiError(401, "identity_required",
                       "Send the demo identity header X-User with every change.")
    if ident.role == "viewer":
        raise ApiError(403, "forbidden_role", "The viewer role cannot change data.",
                       {"role": ident.role})
    return ident


def services(request: Request) -> Any:
    return request.app.state.services

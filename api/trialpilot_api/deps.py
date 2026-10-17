"""Request dependencies: demo identity and shared services.

DEMO IDENTITY ONLY: the acting user comes from the `X-User` header and the role from `X-Role`.
There is no login; this is a prototype. Signing (A7) re-authenticates with a PIN.
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


def current_identity(
    x_user: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> Identity | None:
    if not x_user:
        return None
    if not _USER_RE.match(x_user):
        raise ApiError(400, "invalid_identity",
                       "X-User must be 1-64 characters: letters, digits, '.', '_', '@' or '-'.")
    role = (x_role or "author").strip().lower()
    if role not in ROLES:
        raise ApiError(400, "invalid_identity", f"X-Role must be one of {', '.join(ROLES)}.",
                       {"role": x_role})
    return Identity(user=x_user, role=role)


def require_editor(
    x_user: str | None = Header(default=None),
    x_role: str | None = Header(default=None),
) -> Identity:
    """Mutations need a demo identity whose role may change data (not `viewer`)."""
    ident = current_identity(x_user, x_role)
    if ident is None:
        raise ApiError(401, "identity_required",
                       "Send the demo identity headers X-User and X-Role with every change.")
    if ident.role == "viewer":
        raise ApiError(403, "forbidden_role", "The viewer role cannot change data.",
                       {"role": ident.role})
    return ident


def services(request: Request) -> Any:
    return request.app.state.services

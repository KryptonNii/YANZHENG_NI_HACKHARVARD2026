"""Compliance errors carry an HTTP status and the shared error shape `{error, message, details}`."""

from __future__ import annotations

from typing import Any


class ComplianceError(Exception):
    def __init__(
        self, status: int, code: str, message: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, "details": self.details}

    def __repr__(self) -> str:
        return f"ComplianceError({self.status}, {self.code!r}, {self.message!r})"

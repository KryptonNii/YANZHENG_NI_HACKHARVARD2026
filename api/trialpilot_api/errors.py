"""MASTER §5 error shape for every endpoint:

    {"error": "<code>", "message": "<plain English>", "details": {...}}

Raise `ApiError(status, code, message, details)` anywhere; FastAPI's own errors (404 routes,
422 validation, unhandled exceptions) are rendered in the same shape.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logs import request_id_var

log = logging.getLogger("trialpilot.api")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    501: "not_ready",
    503: "unavailable",
}


class ApiError(Exception):
    """Raise anywhere in a request; rendered with the shared error shape."""

    def __init__(
        self,
        status_code: int,
        error: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error = error
        self.message = message
        self.details = details or {}
        self.headers = headers


def error_body(error: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": error, "message": message, "details": details or {}}


def _response(
    status: int, body: dict[str, Any], headers: dict[str, str] | None = None
) -> JSONResponse:
    rid = request_id_var.get()
    if rid:
        body["details"].setdefault("request_id", rid)
    return JSONResponse(status_code=status, content=body, headers=headers)


def _clean_validation_errors(errors: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "loc": [str(p) for p in e.get("loc", ())],
            "msg": str(e.get("msg", "")),
            "type": str(e.get("type", "")),
        }
        for e in errors
    ]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return _response(
            exc.status_code, error_body(exc.error, exc.message, dict(exc.details)), exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = _clean_validation_errors(list(exc.errors()))
        first = errors[0] if errors else {"loc": [], "msg": "invalid request"}
        where = ".".join(p for p in first["loc"] if p != "body") or "request"
        return _response(
            422,
            error_body(
                "validation_error", f"Invalid request: {where}: {first['msg']}", {"errors": errors}
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ")
        if exc.status_code == 404 and message == "Not Found":
            message = "No such endpoint."
        return _response(
            exc.status_code, error_body(code, message), headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", extra={"path": request.url.path})
        return _response(
            500,
            error_body(
                "internal_error", "Unexpected server error. The request id is in details.", {}
            ),
        )

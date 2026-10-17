"""Structured (JSON-lines) logging with a per-request id."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime
from typing import Any, TextIO

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or request_id_var.get(),
        }
        for k, v in record.__dict__.items():
            if k not in _RESERVED and k not in out and not k.startswith("_"):
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_var.get()
        return True


def configure_logging(
    level: str = "INFO", as_json: bool = True, stream: TextIO | None = None
) -> None:
    """One handler on the `trialpilot` logger (stdout by default; the MCP stdio server passes
    stderr because its stdout is the protocol channel). Later calls keep the first handler."""
    root = logging.getLogger("trialpilot")
    root.setLevel(level.upper())
    if any(getattr(h, "_trialpilot", False) for h in root.handlers):
        return
    handler = logging.StreamHandler(stream or sys.stdout)
    handler._trialpilot = True  # type: ignore[attr-defined]
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(JsonFormatter() if as_json else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"))
    root.addHandler(handler)
    root.propagate = False


access_log = logging.getLogger("trialpilot.access")


class RequestIdMiddleware:
    """Pure ASGI middleware (safe for SSE): accepts an incoming ``X-Request-ID`` or creates
    one, echoes it on the response and logs one structured line per request."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        rid = incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = {"code": 500}

        async def _send(message: dict) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + [(b"x-request-id", rid.encode("latin-1"))]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            access_log.info(
                "request",
                extra={
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status["code"],
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "user": headers.get("x-user"),
                },
            )
            request_id_var.reset(token)

"""LLM client for protocol extraction (Anthropic Messages API via the official SDK).

Provider: Anthropic (`ANTHROPIC_API_KEY`). Model from `EXTRACT_MODEL` (default `claude-sonnet-5-5`,
model ids per https://platform.claude.com/docs - checked 2026-10-16). Structured output
(`output_config.format` JSON schema), adaptive thinking, timeout, one retry, then a clear error.
LLM output is only ever a *candidate*; nothing here writes to a design.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any

DEFAULT_MODEL = "claude-sonnet-5-5"
TIMEOUT_S = 180.0
# Dense schedules repeat evidence for hundreds of procedures. Thinking also consumes
# this budget; 16k truncated the live BOREAS schedule. Stream the larger response.
MAX_OUTPUT_TOKENS = 64000
# Server-side refusal fallback ("default" routing) is accepted on these models only.
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}

# (content_blocks, json_schema, system_prompt) -> parsed JSON dict
LLMCall = Callable[[list[dict[str, Any]], dict[str, Any], str], dict[str, Any]]


class LLMUnavailable(Exception):
    """No credentials configured, or the provider failed twice."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def extract_model() -> str:
    return (os.environ.get("EXTRACT_MODEL") or "").strip() or DEFAULT_MODEL


def llm_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def anthropic_call(blocks: list[dict[str, Any]], schema: dict[str, Any], system: str) -> dict[str, Any]:
    """One structured-output request; retried once on timeouts / 429 / 5xx / connection errors."""
    if not llm_configured():
        raise LLMUnavailable(
            "llm_not_configured",
            "Protocol extraction needs an LLM: set ANTHROPIC_API_KEY (and optionally EXTRACT_MODEL) in .env.",
        )
    import anthropic  # imported lazily so the API starts without the SDK being exercised
    import httpx2  # Anthropic's transport errors propagate directly while reading a stream.

    model = extract_model()
    client = anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=0)  # we own the single retry
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": blocks}],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
    }
    if model in _FALLBACK_MODELS:
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
    last: Exception | None = None
    started = time.perf_counter()
    for attempt in (1, 2):
        try:
            messages = client.beta.messages if "betas" in kwargs else client.messages
            with messages.stream(**kwargs) as stream:
                resp = stream.get_final_message()
                request_id = stream.request_id
        except (anthropic.APIConnectionError, httpx2.TransportError) as exc:
            last = exc
            if attempt == 1:
                time.sleep(2.0)
            continue
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailable("llm_auth_failed", "The LLM provider rejected the API key.") from exc
        except anthropic.APIStatusError as exc:
            error = exc.body.get("error") if isinstance(exc.body, dict) else None
            error_type = error.get("type") if isinstance(error, dict) else None
            # An SSE error arrives after HTTP 200, so the SDK cannot infer a
            # retryable status exception from the response headers alone.
            if (exc.status_code == 429 or exc.status_code >= 500
                    or (exc.status_code == 200 and error_type in {
                        "rate_limit_error", "overloaded_error", "api_error", "timeout_error",
                    })):
                last = exc
                if attempt == 1:
                    time.sleep(2.0)
                continue
            message = (f"The LLM provider stopped the response ({error_type or 'stream error'})."
                       if exc.status_code == 200 else f"The LLM provider returned HTTP {exc.status_code}.")
            raise LLMUnavailable(
                "llm_request_failed", message,
                {"provider_message": getattr(exc, "message", str(exc))[:300]},
            ) from exc
        if resp.stop_reason == "refusal":
            raise LLMUnavailable("llm_refused", "The model declined to extract this document.",
                                 {"category": getattr(resp.stop_details, "category", None)})
        if resp.stop_reason == "max_tokens":
            raise LLMUnavailable("llm_truncated", "The model's answer was cut off (schedule too large).")
        text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), None)
        if text is None:
            raise LLMUnavailable("llm_empty", "The model returned no structured answer.")
        try:
            out: dict[str, Any] = json.loads(text)
        except ValueError as exc:
            raise LLMUnavailable("llm_bad_json", "The model's answer was not valid JSON.") from exc
        out["_model"] = getattr(resp, "model", model)
        out["_request_id"] = request_id
        usage = getattr(resp, "usage", None)
        out["_usage"] = usage.model_dump(mode="json") if usage is not None else {}
        out["_elapsed_ms"] = round((time.perf_counter() - started) * 1000, 1)
        return out
    raise LLMUnavailable(
        "llm_unavailable", "The LLM provider did not answer after one retry. Try again later.",
        {"cause": f"{type(last).__name__}: {last}"},
    )

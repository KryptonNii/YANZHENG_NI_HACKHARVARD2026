"""Exercise the live-client adapter with fake SDK streams, never provider requests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import pytest

from trialpilot_api.importers import llm


class FakeStream:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.request_id = "req-test-stream"
        self.entered = False
        self.closed = False

    def __enter__(self) -> FakeStream:
        self.entered = True
        return self

    def __exit__(self, *_: Any) -> None:
        self.closed = True

    def get_final_message(self) -> Any:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Credentials are local placeholders; the real SDK client is never instantiated."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-key")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("EXTRACT_MODEL", raising=False)

    def install(*outcomes: Any) -> SimpleNamespace:
        pending = list(outcomes)
        calls: list[dict[str, Any]] = []
        streams: list[FakeStream] = []
        sleeps: list[float] = []

        def stream(**kwargs: Any) -> FakeStream:
            calls.append(kwargs)
            context = FakeStream(pending.pop(0))
            streams.append(context)
            return context

        messages = SimpleNamespace(stream=stream)
        client = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
        monkeypatch.setattr(anthropic, "Anthropic", lambda **_: client)
        monkeypatch.setattr(llm.time, "sleep", sleeps.append)
        return SimpleNamespace(calls=calls, streams=streams, sleeps=sleeps)

    return install


def response(*, stop_reason: str = "end_turn", text: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        model="claude-sonnet-5-5",
        content=[SimpleNamespace(type="text", text=text or json.dumps({"visits": []}))],
        usage=SimpleNamespace(model_dump=lambda **_: {"input_tokens": 120, "output_tokens": 24000}),
    )


def test_dense_schedule_uses_large_stream_and_preserves_metadata(fake_provider: Any) -> None:
    provider = fake_provider(response())
    schema = {"type": "object", "properties": {"visits": {"type": "array"}}}
    blocks = [{"type": "text", "text": "Synthetic schedule for adapter verification."}]

    result = llm.anthropic_call(blocks, schema, "Extract candidate visits.")

    assert result["visits"] == []
    assert result["_model"] == "claude-sonnet-5-5"
    assert result["_request_id"] == "req-test-stream"
    assert result["_usage"] == {"input_tokens": 120, "output_tokens": 24000}
    assert isinstance(result["_elapsed_ms"], float) and result["_elapsed_ms"] >= 0
    assert len(provider.calls) == 1
    request = provider.calls[0]
    assert request["model"] == "claude-sonnet-5-5"
    assert request["max_tokens"] == 64000
    assert request["output_config"]["effort"] == "medium"
    assert request["output_config"]["format"] == {"type": "json_schema", "schema": schema}
    assert request["messages"] == [{"role": "user", "content": blocks}]
    assert provider.streams[0].entered and provider.streams[0].closed


def test_truncated_stream_is_rejected_before_parsing_partial_json(fake_provider: Any) -> None:
    provider = fake_provider(response(stop_reason="max_tokens", text='{"visits": ['))

    with pytest.raises(llm.LLMUnavailable) as error:
        llm.anthropic_call([], {}, "Extract candidate visits.")

    assert error.value.code == "llm_truncated"
    assert len(provider.calls) == 1
    assert provider.streams[0].closed


def test_transient_stream_error_retries_once_and_closes_each_context(fake_provider: Any) -> None:
    failure = anthropic.APIConnectionError(
        request=httpx.Request("POST", "https://provider.invalid/messages")
    )
    provider = fake_provider(failure, response())

    result = llm.anthropic_call([], {}, "Extract candidate visits.")

    assert result["visits"] == []
    assert len(provider.calls) == 2
    assert len(provider.sleeps) == 1
    assert all(context.entered and context.closed for context in provider.streams)


def test_authentication_failure_is_explicit_and_not_retried(fake_provider: Any) -> None:
    request = httpx.Request("POST", "https://provider.invalid/messages")
    failure = anthropic.AuthenticationError(
        "Invalid API key",
        response=httpx.Response(401, request=request),
        body={"error": {"type": "authentication_error"}},
    )
    provider = fake_provider(failure)

    with pytest.raises(llm.LLMUnavailable) as error:
        llm.anthropic_call([], {}, "Extract candidate visits.")

    assert error.value.code == "llm_auth_failed"
    assert len(provider.calls) == 1 and not provider.sleeps
    assert provider.streams[0].closed


@pytest.mark.parametrize("error_cls", [httpx2.ReadTimeout, httpx2.ReadError, httpx2.RemoteProtocolError])
def test_transport_failure_while_reading_stream_retries_once(
    fake_provider: Any, error_cls: type[httpx2.TransportError],
) -> None:
    provider = fake_provider(error_cls("Stream interrupted"), response())

    result = llm.anthropic_call([], {}, "Extract candidate visits.")

    assert result["visits"] == []
    assert len(provider.calls) == 2 and provider.sleeps == [2.0]
    assert all(context.closed for context in provider.streams)


def test_provider_overload_status_retries_once(fake_provider: Any) -> None:
    failure = anthropic.OverloadedError(
        "Overloaded",
        response=httpx2.Response(529, request=httpx2.Request("POST", "https://provider.invalid/messages")),
        body={"error": {"type": "overloaded_error"}},
    )
    provider = fake_provider(failure, response())

    assert llm.anthropic_call([], {}, "Extract candidate visits.")["visits"] == []
    assert len(provider.calls) == 2 and provider.sleeps == [2.0]


@pytest.mark.parametrize("error_type", ["overloaded_error", "api_error", "rate_limit_error", "timeout_error"])
def test_transient_sse_error_with_http_200_retries(fake_provider: Any, error_type: str) -> None:
    failure = anthropic.APIStatusError(
        "Provider stream interrupted",
        response=httpx2.Response(200, request=httpx2.Request("POST", "https://provider.invalid/messages")),
        body={"type": "error", "error": {"type": error_type}},
    )
    provider = fake_provider(failure, response())

    assert llm.anthropic_call([], {}, "Extract candidate visits.")["visits"] == []
    assert len(provider.calls) == 2 and provider.sleeps == [2.0]


def test_permanent_sse_error_is_not_retried_or_reported_as_http_200(fake_provider: Any) -> None:
    failure = anthropic.APIStatusError(
        "Invalid request",
        response=httpx2.Response(200, request=httpx2.Request("POST", "https://provider.invalid/messages")),
        body={"type": "error", "error": {"type": "invalid_request_error"}},
    )
    provider = fake_provider(failure)

    with pytest.raises(llm.LLMUnavailable) as error:
        llm.anthropic_call([], {}, "Extract candidate visits.")

    assert error.value.code == "llm_request_failed"
    assert "invalid_request_error" in error.value.message and "HTTP 200" not in error.value.message
    assert len(provider.calls) == 1 and not provider.sleeps


def test_transport_retry_exhaustion_is_translated_after_two_attempts(fake_provider: Any) -> None:
    provider = fake_provider(httpx2.ReadError("First stream failed"), httpx2.ReadTimeout("Retry failed"))

    with pytest.raises(llm.LLMUnavailable) as error:
        llm.anthropic_call([], {}, "Extract candidate visits.")

    assert error.value.code == "llm_unavailable"
    assert "ReadTimeout" in error.value.details["cause"]
    assert len(provider.calls) == 2 and provider.sleeps == [2.0]
    assert all(context.closed for context in provider.streams)


def test_actual_sdk_sse_error_retries_with_http_200(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use real SDK SSE parsing over a local mock transport; no provider is contacted."""
    requests: list[httpx2.Request] = []
    sleeps: list[float] = []
    events = [
        ("message_start", {"message": {
            "id": "msg-test", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 0},
        }}),
        ("content_block_start", {"index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"index": 0, "delta": {"type": "text_delta", "text": '{"visits": []}'}}),
        ("content_block_stop", {"index": 0}),
        ("message_delta", {"delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 5}}),
        ("message_stop", {}),
    ]
    success = "".join(f"event: {kind}\ndata: {json.dumps({'type': kind, **body})}\n\n" for kind, body in events)
    overload = 'event: error\ndata: {"type":"error","error":{"type":"overloaded_error","message":"Busy"}}\n\n'

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200, text=overload if len(requests) == 1 else success,
            headers={"Content-Type": "text/event-stream", "request-id": f"req-{len(requests)}"},
        )

    client = anthropic.Anthropic(
        api_key="test-placeholder-key", max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handle)),
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-placeholder-key")
    monkeypatch.delenv("EXTRACT_MODEL", raising=False)
    monkeypatch.setattr(anthropic, "Anthropic", lambda **_: client)
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)

    with client:
        result = llm.anthropic_call([], {}, "Extract candidate visits.")

    assert result["visits"] == [] and result["_request_id"] == "req-2"
    assert len(requests) == 2 and sleeps == [2.0]

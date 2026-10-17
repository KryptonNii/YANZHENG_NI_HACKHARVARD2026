"""Server-Sent Events helper (used by A6 for `/api/ops/{trial_id}/stream`).

    from trialpilot_api.sse import SSEMessage, sse_response

    @router.get("/{trial_id}/stream")
    async def stream(trial_id: str, request: Request):
        broker = request.app.state.services.broker
        return sse_response(request, f"ops:{trial_id}", broker)

    # anywhere (sync or async code, any thread):
    broker.publish(f"ops:{trial_id}", "ops_event", event.model_dump(mode="json"))

- Heartbeat: a comment line every 15 s keeps proxies (Caddy) and browsers from closing the stream.
- Reconnect: browsers resend the last id in the `Last-Event-ID` header (or `?last_event_id=`);
  everything after that id still in the replay buffer is sent first, then live messages.
  Ids are unique and increase per channel, so replay never duplicates or reorders.
- Optional `replay=` callback lets A6 replay from its own store (DB) instead of the buffer.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sse_starlette import EventSourceResponse, ServerSentEvent

HEARTBEAT_SECONDS = 15
RETRY_MS = 3000


@dataclass(frozen=True)
class SSEMessage:
    seq: int  # broker-assigned, increases per channel
    id: str  # what the client sees as the event id (defaults to str(seq))
    event: str  # e.g. "ops_event", "alert_new", "alert_update", "effect_update"
    data: Any  # JSON-serialisable payload

    def to_sse(self) -> ServerSentEvent:
        return ServerSentEvent(
            data=json.dumps(self.data, separators=(",", ":"), default=str),
            event=self.event,
            id=self.id,
        )


class _Subscriber:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[SSEMessage] = asyncio.Queue(maxsize=10_000)

    def push(self, msg: SSEMessage) -> None:
        def _put() -> None:
            if not self.queue.full():  # a stalled client drops live messages, replay recovers
                self.queue.put_nowait(msg)

        self.loop.call_soon_threadsafe(_put)


class EventBroker:
    """In-process pub/sub with a bounded replay buffer per channel. Thread-safe."""

    def __init__(self, buffer_size: int = 2000) -> None:
        self.buffer_size = buffer_size
        self._lock = threading.Lock()
        self._buffers: dict[str, deque[SSEMessage]] = {}
        self._seq: dict[str, int] = {}
        self._subs: dict[str, set[_Subscriber]] = {}

    def publish(self, channel: str, event: str, data: Any, id: str | None = None) -> SSEMessage:
        with self._lock:
            seq = self._seq.get(channel, 0) + 1
            self._seq[channel] = seq
            msg = SSEMessage(seq=seq, id=id or str(seq), event=event, data=data)
            self._buffers.setdefault(channel, deque(maxlen=self.buffer_size)).append(msg)
            subs = list(self._subs.get(channel, ()))
        for sub in subs:
            try:
                sub.push(msg)
            except RuntimeError:  # loop closed: subscriber is gone
                self._unsubscribe(channel, sub)
        return msg

    def replay(self, channel: str, last_event_id: str | None) -> list[SSEMessage]:
        """Buffered messages after `last_event_id` (all of them if the id is unknown/None)."""
        with self._lock:
            buf = list(self._buffers.get(channel, ()))
        if not last_event_id:
            return buf
        for i, m in enumerate(buf):
            if m.id == last_event_id:
                return buf[i + 1 :]
        return buf

    def _subscribe(self, channel: str) -> _Subscriber:
        sub = _Subscriber(asyncio.get_running_loop())
        with self._lock:
            self._subs.setdefault(channel, set()).add(sub)
        return sub

    def _unsubscribe(self, channel: str, sub: _Subscriber) -> None:
        with self._lock:
            self._subs.get(channel, set()).discard(sub)

    def subscriber_count(self, channel: str) -> int:
        with self._lock:
            return len(self._subs.get(channel, ()))

    async def subscribe(
        self,
        channel: str,
        last_event_id: str | None = None,
        replay: Callable[[str | None], Iterable[SSEMessage]] | None = None,
    ) -> AsyncIterator[SSEMessage]:
        sub = self._subscribe(channel)  # subscribe first, so nothing published meanwhile is lost
        try:
            sent_ids: set[str] = set()
            max_seq = 0
            backlog = list(replay(last_event_id)) if replay else self.replay(channel, last_event_id)
            for msg in backlog:
                sent_ids.add(msg.id)
                max_seq = max(max_seq, msg.seq)
                yield msg
            while True:
                msg = await sub.queue.get()
                if msg.id in sent_ids or (not replay and msg.seq <= max_seq):
                    continue
                yield msg
        finally:
            self._unsubscribe(channel, sub)


def last_event_id_of(request: Request) -> str | None:
    return request.headers.get("last-event-id") or request.query_params.get("last_event_id")


def sse_response(
    request: Request,
    channel: str,
    broker: EventBroker | None = None,
    *,
    replay: Callable[[str | None], Iterable[SSEMessage]] | None = None,
    heartbeat: float = HEARTBEAT_SECONDS,
    retry_ms: int = RETRY_MS,
) -> EventSourceResponse:
    """EventSourceResponse for one channel: replay after Last-Event-ID, then live, 15 s pings."""
    broker = broker or request.app.state.services.broker
    last_id = last_event_id_of(request)

    async def gen() -> AsyncIterator[ServerSentEvent]:
        yield ServerSentEvent(comment="connected", retry=retry_ms)
        async for msg in broker.subscribe(channel, last_id, replay):
            if await request.is_disconnected():
                break
            yield msg.to_sse()

    return EventSourceResponse(
        gen(),
        ping=heartbeat,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

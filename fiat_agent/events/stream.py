"""Session-scoped event streaming buffer (DEV_SPEC §K2).

Bridges the in-process :class:`~fiat_agent.events.bus.EventBus` to SSE clients.
The :class:`EventStreamManager` keeps a bounded ring buffer of recent
:class:`~fiat_agent.events.types.AgentEvent` envelopes (each tagged with a
monotonic ``seq``) and exposes an async iterator per session that:

1. first replays buffered events the client missed (by ``cursor`` / seq), and
2. then yields live events as they arrive on the bus.

Because the subscription queue is registered *before* snapshotting the current
``seq``, replay (``seq <= snapshot``) and live (``seq > snapshot``) are
disjoint and gap-free — a reconnecting client loses no events.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from fiat_agent.events.bus import EventBus, get_event_bus
from fiat_agent.events.types import AgentEvent


@dataclass
class BufferedEvent:
    """An event plus the monotonic sequence number assigned when buffered."""

    seq: int
    event: AgentEvent


class EventStreamManager:
    """Buffers recent events and fans them out to per-session SSE streams."""

    def __init__(
        self, bus: Optional[EventBus] = None, maxlen: int = 2000
    ) -> None:
        self._bus = bus or get_event_bus()
        self._buffer: deque[BufferedEvent] = deque(maxlen=maxlen)
        self._seq = 0
        self._listening = False
        self._queues: dict[str, list[asyncio.Queue[BufferedEvent]]] = {}

    # -- bus wiring -------------------------------------------------------
    def start(self) -> None:
        """Subscribe to the bus. Idempotent; safe to call on every request."""
        if not self._listening:
            self._bus.subscribe(self._on_event)
            self._listening = True

    async def _on_event(self, event: AgentEvent) -> None:
        self._buffer_event(event)

    # -- buffering --------------------------------------------------------
    def _buffer_event(self, event: AgentEvent) -> int:
        """Append ``event`` to the ring buffer and fan out to live queues.

        Returns the assigned ``seq``. Uses ``put_nowait`` so a stalled SSE
        client can never block the bus.
        """
        self._seq += 1
        buffered = BufferedEvent(seq=self._seq, event=event)
        self._buffer.append(buffered)
        if event.session_id:
            for q in self._queues.get(event.session_id, []):
                q.put_nowait(buffered)
        return self._seq

    # -- replay -----------------------------------------------------------
    def replay(
        self, cursor: int, *, session_id: Optional[str] = None
    ) -> list[BufferedEvent]:
        """Buffered events with ``seq > cursor`` (optionally session-scoped)."""
        out = [b for b in self._buffer if b.seq > cursor]
        if session_id is not None:
            out = [b for b in out if b.event.session_id == session_id]
        return out

    # -- live subscription ------------------------------------------------
    def subscribe(self, session_id: str) -> asyncio.Queue[BufferedEvent]:
        q: asyncio.Queue[BufferedEvent] = asyncio.Queue()
        self._queues.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue[BufferedEvent]) -> None:
        qs = self._queues.get(session_id)
        if qs and q in qs:
            qs.remove(q)
            if not qs:
                self._queues.pop(session_id, None)

    async def stream(
        self, session_id: str, *, cursor: int = 0
    ) -> AsyncIterator[BufferedEvent]:
        """Async-iterate this session's events: replayed first, then live."""
        q = self.subscribe(session_id)
        snapshot = self._seq  # registered before snapshot → gap-free
        try:
            for b in self.replay(cursor, session_id=session_id):
                if b.seq <= snapshot:
                    yield b
            while True:
                b = await q.get()
                if b.seq <= cursor:
                    continue
                yield b
        finally:
            self.unsubscribe(session_id, q)


_default_manager: Optional[EventStreamManager] = None


def get_event_stream_manager() -> EventStreamManager:
    """Return the process-wide :class:`EventStreamManager` singleton."""
    global _default_manager
    if _default_manager is None:
        _default_manager = EventStreamManager()
    return _default_manager


def reset_event_stream_manager() -> None:
    """Reset the singleton. Used by tests to get a clean manager per case."""
    global _default_manager
    _default_manager = None

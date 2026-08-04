"""In-process publish/subscribe Event Bus (DEV_SPEC §K1).

The bus is the final fan-out step of the agent loop (§7.1): once a session
event, tool call or audit record is written, the bus pushes the corresponding
:class:`~fiat_agent.events.types.AgentEvent` to every subscriber (CLI, Web
SSE, Lark notifications, ...).

It is intentionally dependency-free (only depends on :mod:`fiat_agent.events.types`)
so producers across the codebase can import it without cycles. A process-wide
singleton is available via :func:`get_event_bus` (mirrors the ``get_*_service``
dependency pattern used by the FastAPI app).

Subscription model
-------------------
* ``subscribe(handler)`` — receive *every* event (global subscriber).
* ``subscribe_topic(topic, handler)`` — receive only events whose ``topic``
  equals ``topic`` *or* whose ``kind.value`` equals ``topic``. This lets a
  subscriber register for ``"session"`` (all session events) or
  ``"session:<id>"`` (a single session's stream).

A single handler is never invoked twice for the same event even if it matches
both the exact topic and the kind.
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from fiat_agent.events.types import AgentEvent

EventHandler = Callable[[AgentEvent], Awaitable[None]]


class EventBus:
    """Simple async pub/sub bus for :class:`AgentEvent` envelopes."""

    def __init__(self) -> None:
        self._global: list[EventHandler] = []
        self._by_topic: dict[str, list[EventHandler]] = {}

    # -- subscription -----------------------------------------------------
    def subscribe(self, handler: EventHandler) -> EventHandler:
        """Subscribe to all events. Returns ``handler`` for use as a decorator."""
        self._global.append(handler)
        return handler

    def subscribe_topic(self, topic: str, handler: EventHandler) -> EventHandler:
        """Subscribe to events scoped to ``topic`` or to ``kind == topic``."""
        self._by_topic.setdefault(topic, []).append(handler)
        return handler

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a handler from all subscriptions it belongs to."""
        if handler in self._global:
            self._global.remove(handler)
        for handlers in self._by_topic.values():
            if handler in handlers:
                handlers.remove(handler)

    # -- publishing -------------------------------------------------------
    def _subscribers_for(self, event: AgentEvent) -> list[EventHandler]:
        """Resolve the de-duplicated handler list for an event."""
        handlers: list[EventHandler] = list(self._global)
        # Exact topic match.
        handlers += self._by_topic.get(event.topic, [])
        # Kind-level match (covers "session", "tool", "approval", "generic").
        handlers += self._by_topic.get(event.kind.value, [])
        # De-duplicate while preserving order.
        seen: set[EventHandler] = set()
        ordered: list[EventHandler] = []
        for h in handlers:
            if h not in seen:
                seen.add(h)
                ordered.append(h)
        return ordered

    async def publish(self, event: AgentEvent) -> None:
        """Broadcast ``event`` to all matching subscribers.

        A subscriber that raises is isolated: its failure is swallowed so it
        cannot break the broadcast for other subscribers. This keeps the bus
        resilient when, e.g., a flaky Lark notifier throws.
        """
        for handler in self._subscribers_for(event):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception:  # noqa: BLE001 - isolate misbehaving subscribers
                continue


_default_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Return the process-wide :class:`EventBus` singleton."""
    global _default_bus
    if _default_bus is None:
        _default_bus = EventBus()
    return _default_bus


def reset_event_bus() -> None:
    """Reset the singleton. Used by tests to get a clean bus per case."""
    global _default_bus
    _default_bus = None

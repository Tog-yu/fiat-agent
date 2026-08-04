"""Unit tests for the Event Bus (DEV_SPEC §K1).

Covers the acceptance criterion: session / tool / approval events can all be
broadcast. Also exercises topic filtering, unsubscribe and subscriber-fault
isolation. Follows the project's ``asyncio.run`` test convention (no
pytest-asyncio plugin required).
"""

from __future__ import annotations

import asyncio

from fiat_agent.events.bus import (
    EventBus,
    get_event_bus,
    reset_event_bus,
)
from fiat_agent.events.types import (
    AgentEvent,
    EventKind,
    approval_event,
    session_event,
    tool_event,
)


def test_three_kinds_broadcast():
    async def _run():
        bus = EventBus()
        received: list[AgentEvent] = []

        async def handler(e: AgentEvent) -> None:
            received.append(e)

        bus.subscribe(handler)

        await bus.publish(session_event({"seq": 1}, session_id="s1"))
        await bus.publish(tool_event({"tool": "es.query"}, session_id="s1"))
        await bus.publish(approval_event({"status": "pending"}))

        assert len(received) == 3
        kinds = {e.kind for e in received}
        assert kinds == {EventKind.SESSION, EventKind.TOOL, EventKind.APPROVAL}

    asyncio.run(_run())


def test_topic_kind_subscription():
    async def _run():
        bus = EventBus()
        session_only: list[AgentEvent] = []
        approval_only: list[AgentEvent] = []

        bus.subscribe_topic("session", _rec(session_only))
        bus.subscribe_topic("approval", _rec(approval_only))

        await bus.publish(session_event({"seq": 1}, session_id="s1"))
        await bus.publish(tool_event({"tool": "x"}))
        await bus.publish(approval_event({"status": "pending"}))

        # session subscriber gets the session event only (not tool/approval).
        assert [e.kind for e in session_only] == [EventKind.SESSION]
        # approval subscriber gets the approval event only.
        assert [e.kind for e in approval_only] == [EventKind.APPROVAL]

    asyncio.run(_run())


def test_session_scoped_topic():
    async def _run():
        bus = EventBus()
        scoped: list[AgentEvent] = []

        bus.subscribe_topic("session:s1", _rec(scoped))

        # Producers set a session-scoped topic so SSE can stream one session.
        await bus.publish(session_event({"seq": 1}, session_id="s1", topic="session:s1"))
        await bus.publish(session_event({"seq": 2}, session_id="s2", topic="session:s2"))

        # Only the s1 session event reaches the scoped subscriber.
        assert len(scoped) == 1
        assert scoped[0].session_id == "s1"

    asyncio.run(_run())


def test_unsubscribe():
    async def _run():
        bus = EventBus()
        received: list[AgentEvent] = []

        handler = _rec(received)
        bus.subscribe(handler)
        await bus.publish(session_event({"seq": 1}))

        bus.unsubscribe(handler)
        await bus.publish(session_event({"seq": 2}))

        assert len(received) == 1

    asyncio.run(_run())


def test_subscriber_fault_isolation():
    async def _run():
        bus = EventBus()
        received: list[AgentEvent] = []

        async def boom(_: AgentEvent) -> None:
            raise RuntimeError("subscriber down")

        bus.subscribe(boom)
        bus.subscribe(_rec(received))

        # The failing subscriber must not prevent delivery to the healthy one.
        await bus.publish(tool_event({"tool": "x"}))
        assert len(received) == 1

    asyncio.run(_run())


def test_singleton_and_reset():
    async def _run():
        reset_event_bus()
        a = get_event_bus()
        b = get_event_bus()
        assert a is b
        reset_event_bus()
        c = get_event_bus()
        assert c is not a

    asyncio.run(_run())


def _rec(store: list[AgentEvent]):
    """Return an async handler that appends events to ``store``."""

    async def handler(e: AgentEvent) -> None:
        store.append(e)

    return handler

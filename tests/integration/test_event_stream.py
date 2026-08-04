"""Integration tests for SSE event streaming (DEV_SPEC §K2).

Covers: buffered replay by cursor, per-session filtering, live delivery, the
SSE frame format, cursor-based resume and the FastAPI endpoint wiring.

The streaming layer is exercised directly via the route's SSE generator (the
same code path the HTTP endpoint uses) to avoid flaky ``TestClient`` streaming;
a final test asserts the endpoint returns a proper ``StreamingResponse``.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.responses import StreamingResponse

from fiat_agent.events.bus import EventBus
from fiat_agent.events.stream import EventStreamManager
from fiat_agent.events.types import session_event


# --------------------------------------------------------------------------- #
# Manager: replay + cursor + session filtering                                #
# --------------------------------------------------------------------------- #
def test_replay_after_cursor_filtered_by_session():
    async def _run():
        bus = EventBus()
        manager = EventStreamManager(bus=bus)
        manager.start()

        sid = "s1"
        await bus.publish(session_event({"seq": 1}, session_id=sid))
        await bus.publish(session_event({"seq": 2}, session_id="other"))
        await bus.publish(session_event({"seq": 3}, session_id=sid))
        await bus.publish(session_event({"tool": "x"}))  # no session_id

        # Cursor 1 → only the s1 event with seq 3 should replay (s1-scoped).
        replayed = manager.replay(1, session_id=sid)
        assert [b.seq for b in replayed] == [3]
        assert all(b.event.session_id == sid for b in replayed)

    asyncio.run(_run())


def test_stream_replays_buffered_then_stops_until_live():
    async def _run():
        bus = EventBus()
        manager = EventStreamManager(bus=bus)
        manager.start()
        sid = "s1"
        await bus.publish(session_event({"seq": 1}, session_id=sid))
        await bus.publish(session_event({"seq": 2}, session_id=sid))

        agen = manager.stream(sid, cursor=0)
        received = []
        async for b in agen:
            received.append(b)
            if len(received) >= 2:
                break
        await agen.aclose()
        assert [b.seq for b in received] == [1, 2]

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# Manager: live delivery                                                       #
# --------------------------------------------------------------------------- #
def test_stream_delivers_live_events():
    async def _run():
        bus = EventBus()
        manager = EventStreamManager(bus=bus)
        manager.start()
        sid = "live"

        agen = manager.stream(sid, cursor=0)

        async def publisher():
            for i in range(3):
                await bus.publish(
                    session_event({"i": i}, session_id=sid, topic=f"session:{sid}")
                )

        task = asyncio.create_task(publisher())
        received = []
        async for b in agen:
            received.append(b)
            if len(received) >= 3:
                break
        await agen.aclose()
        await task
        assert len(received) == 3
        assert [b.event.payload["i"] for b in received] == [0, 1, 2]

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# SSE generator: frame format + cursor resume                                  #
# --------------------------------------------------------------------------- #
def _build_manager_with(sid: str, n: int) -> EventStreamManager:
    bus = EventBus()
    manager = EventStreamManager(bus=bus)
    manager.start()
    for i in range(1, n + 1):
        manager._buffer_event(
            session_event({"n": i}, session_id=sid, topic=f"session:{sid}")
        )
    return manager


def _parse_sse_frame(chunk: str):
    seq = None
    data = None
    for line in chunk.split("\n"):
        if line.startswith("id: "):
            seq = int(line[4:])
        elif line.startswith("data: "):
            data = json.loads(line[6:])
    return seq, data


def test_sse_generator_emits_frames_with_cursor():
    from apps.api.routes.events import _event_generator

    async def _run():
        sid = "sse-1"
        manager = _build_manager_with(sid, 3)

        agen = _event_generator(sid, cursor=0, manager=manager)
        frames = []
        async for chunk in agen:
            seq, data = _parse_sse_frame(chunk)
            frames.append((seq, data))
            if len(frames) >= 3:
                break
        await agen.aclose()

        assert [s for s, _ in frames] == [1, 2, 3]
        assert all(d["session_id"] == sid for _, d in frames)
        # SSE frame shape: "id: X\ndata: {...}\n\n"
        assert chunk.startswith("id: ") and "data: " in chunk

    asyncio.run(_run())


def test_sse_generator_resumes_from_cursor():
    from apps.api.routes.events import _event_generator

    async def _run():
        sid = "sse-2"
        manager = _build_manager_with(sid, 3)

        # Resume after cursor=2 → only event 3 should be streamed.
        agen = _event_generator(sid, cursor=2, manager=manager)
        frames = []
        async for chunk in agen:
            seq, data = _parse_sse_frame(chunk)
            frames.append((seq, data))
            if len(frames) >= 1:
                break
        await agen.aclose()

        assert len(frames) == 1
        assert frames[0][0] == 3
        assert frames[0][1]["payload"]["n"] == 3

    asyncio.run(_run())


def test_resolve_cursor_reads_last_event_id():
    from apps.api.routes.events import _resolve_cursor

    req_with = SimpleNamespace(headers={"Last-Event-ID": "7"})
    req_without = SimpleNamespace(headers={})

    assert _resolve_cursor(req_with, default=0) == 7
    assert _resolve_cursor(req_without, default=0) == 0
    assert _resolve_cursor(SimpleNamespace(headers={"Last-Event-ID": "NaN"}), 0) == 0


def test_endpoint_returns_streaming_response():
    from apps.api.routes.events import stream_session_events

    async def _run():
        manager = _build_manager_with("sse-3", 2)
        req = SimpleNamespace(headers={})
        resp = await stream_session_events("sse-3", req, cursor=0, manager=manager)
        assert isinstance(resp, StreamingResponse)
        assert resp.media_type == "text/event-stream"

    asyncio.run(_run())

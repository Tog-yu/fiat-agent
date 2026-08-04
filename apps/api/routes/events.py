"""SSE event-stream API (DEV_SPEC §K2).

Exposes a Server-Sent Events endpoint so the Web Console can subscribe to a
session's live events and resume after a disconnect using a cursor:

* ``GET /api/events/{session_id}`` — SSE stream of that session's events.

The stream first replays buffered events the client missed (via ``?cursor=`` or
the SSE ``Last-Event-ID`` header) and then pushes live events as they arrive on
the Event Bus. Each frame carries ``id: <seq>`` so the client can persist its
cursor and resume without gaps.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from fiat_agent.events.stream import (
    BufferedEvent,
    EventStreamManager,
    get_event_stream_manager,
)

router = APIRouter(prefix="/api/events", tags=["events"])


def _to_sse(buffered: BufferedEvent) -> str:
    """Render a buffered event as an SSE frame with an ``id`` cursor."""
    return f"id: {buffered.seq}\ndata: {buffered.event.model_dump_json()}\n\n"


def _resolve_cursor(request: Optional[Request], default: int = 0) -> int:
    """Resolve the resume cursor from the SSE ``Last-Event-ID`` header.

    SSE clients send the last received ``id`` back as ``Last-Event-ID`` on
    reconnect; this lets the stream resume without gaps.
    """
    if request is None:
        return default
    last_id = request.headers.get("Last-Event-ID")
    if last_id is not None:
        try:
            return int(last_id)
        except ValueError:
            return default
    return default


async def _event_generator(
    session_id: str, cursor: int, manager: EventStreamManager
) -> None:
    manager.start()
    async for buffered in manager.stream(session_id, cursor=cursor):
        yield _to_sse(buffered)


@router.get("/{session_id}")
async def stream_session_events(
    session_id: str,
    request: Request,
    cursor: int = 0,
    manager: EventStreamManager = Depends(get_event_stream_manager),
) -> StreamingResponse:
    """Stream ``session_id`` events over SSE, resuming from ``cursor``."""
    cursor = _resolve_cursor(request, cursor)
    return StreamingResponse(
        _event_generator(session_id, cursor, manager),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

"""Session JSONL exporter (phase C7, DEV_SPEC C7).

Exports a session's active-branch events as newline-delimited JSON (JSONL),
one event per line, in root -> tip (active-branch) order. Used for debugging,
replay and evaluation (DEV_SPEC §7.3, §13.3). Every event on the active branch
is emitted, so message / tool_call / compaction / approval events are all
included by construction.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from fiat_agent.sessions.store import SessionStore


def _iso(ts) -> str | None:
    """Normalize a datetime to a UTC ISO-8601 string (``...Z``).

    SQLite has no timezone, so ``DateTime(timezone=True)`` returns naive
    datetimes on read; treat those as UTC. Tz-aware values are converted to UTC.
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    return str(ts)


async def export_session_jsonl(
    session: AsyncSession, session_id: str
) -> AsyncIterator[str]:
    """Yield the active-branch events of ``session_id`` as JSONL lines.

    The order matches the active branch (root -> tip), so a consumer replaying
    the lines reproduces the conversation exactly. Events that were rolled back
    off the active branch are excluded, and forked branches appear only when they
    are the active tip.

    Args:
        session: an open :class:`AsyncSession`.
        session_id: the session to export.

    Yields:
        ``str`` JSON lines, one per event, in active-branch order.
    """
    store = SessionStore()
    path = await store.get_active_path(session, session_id)
    for ev in path:
        record = {
            "seq": ev.seq,
            "id": ev.id,
            "parent_event_id": ev.parent_event_id,
            "event_type": ev.event_type,
            "created_at": _iso(ev.created_at),
            "content": ev.content,
        }
        yield json.dumps(record, ensure_ascii=False, sort_keys=True)

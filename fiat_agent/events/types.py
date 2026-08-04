"""Event envelope types for the in-process Event Bus (DEV_SPEC §K1).

The bus carries lightweight, JSON-serializable :class:`AgentEvent` envelopes so
they can be broadcast to CLI / Web / Lark subscribers and later streamed over
SSE (§K2). Each event wraps the underlying domain object (a session event, an
audit ``tool_call``, an :class:`~fiat_agent.approvals.service.Approval`, ...)
as a ``payload`` dict.

Design notes
------------
* ``AgentEvent`` extends :class:`~fiat_agent.schemas.common.FiatModel` so it is
  schema-validated and JSON-serializable (required for SSE export).
* ``kind`` is the coarse category used for kind-level subscriptions; ``topic``
  carries a finer scope (e.g. ``"session:<id>"``) used for session-scoped SSE
  streams. The bus dispatches to both exact-topic and kind-level subscribers.
* The bus is pure transport: it never makes policy/approval/audit decisions
  (those stay deterministic per §2.2).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from fiat_agent.schemas.common import FiatModel


class EventKind(str, Enum):
    """Coarse event categories broadcast on the bus."""

    SESSION = "session"
    TOOL = "tool"
    APPROVAL = "approval"
    GENERIC = "generic"


class AgentEvent(FiatModel):
    """Transport envelope for one broadcast event.

    Attributes:
        id: Unique event id (UUID hex).
        kind: Coarse category (see :class:`EventKind`).
        timestamp: UTC emission time.
        session_id: Optional owning session (for session-scoped streams).
        topic: Dispatch key. Defaults to ``kind.value`` but callers may set a
            finer scope such as ``"session:<id>"``.
        payload: The underlying domain object, serialized to a dict.
    """

    id: str
    kind: EventKind
    timestamp: datetime
    session_id: Optional[str] = None
    topic: str
    payload: dict[str, Any] = {}

    @classmethod
    def make(
        cls,
        kind: EventKind,
        payload: dict[str, Any],
        *,
        session_id: Optional[str] = None,
        topic: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> "AgentEvent":
        """Build an event with a fresh id and UTC timestamp.

        Args:
            kind: Event category.
            payload: Domain object serialized to a dict.
            session_id: Optional owning session id.
            topic: Optional finer dispatch key; defaults to ``kind.value``.
            timestamp: Optional emission time (defaults to ``now(UTC)``).
        """
        return cls(
            id=uuid4().hex,
            kind=kind,
            timestamp=timestamp or datetime.now(timezone.utc),
            session_id=session_id,
            topic=topic or kind.value,
            payload=payload,
        )


def session_event(
    payload: dict[str, Any],
    *,
    session_id: Optional[str] = None,
    topic: Optional[str] = None,
) -> AgentEvent:
    """Convenience builder for a session-kind event."""
    return AgentEvent.make(
        EventKind.SESSION, payload, session_id=session_id, topic=topic
    )


def tool_event(
    payload: dict[str, Any],
    *,
    session_id: Optional[str] = None,
    topic: Optional[str] = None,
) -> AgentEvent:
    """Convenience builder for a tool-call-kind event."""
    return AgentEvent.make(
        EventKind.TOOL, payload, session_id=session_id, topic=topic
    )


def approval_event(
    payload: dict[str, Any],
    *,
    session_id: Optional[str] = None,
    topic: Optional[str] = None,
) -> AgentEvent:
    """Convenience builder for an approval-kind event."""
    return AgentEvent.make(
        EventKind.APPROVAL, payload, session_id=session_id, topic=topic
    )

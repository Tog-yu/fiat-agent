"""Session Memory Store ORM models + repository (phase C1, DEV_SPEC C1).

Append-only session event store. The driver is chosen by ``database.url``
scheme (see ``fiat_agent/db.py``); defaults to SQLite, PostgreSQL is an
optional extension point (DEV_SPEC §13). Tables:

  - ``task_sessions``        : one conversation / task session
  - ``task_session_events``  : append-only events linked by ``parent_event_id``
  - ``task_artifacts``       : derived artifacts (e.g. compaction summaries)
  - ``tool_calls``           : tool invocation records (linked to events)
  - ``session_branches``     : Pi-style conversation branches

The C2 task adds the append-only write path and event-path traversal on top of
these models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fiat_agent.models.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskSession(Base):
    """A single task conversation / session."""

    __tablename__ = "task_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    task_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    environment: Mapped[str] = mapped_column(String(32), default="dev")
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="active")
    # Tip of the active branch (Pi-style session tree).
    active_event_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    events: Mapped[list["TaskSessionEvent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    branches: Mapped[list["SessionBranch"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class TaskSessionEvent(Base):
    """One append-only event in a session.

    Events form a tree via ``parent_event_id``; history is never updated
    (C2 enforces immutability), only new events are appended.
    """

    __tablename__ = "task_session_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("task_sessions.id", ondelete="CASCADE"), index=True
    )
    parent_event_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    # Monotonic per-session counter for stable ordering (C2 relies on this).
    seq: Mapped[int] = mapped_column(Integer, default=0)
    # Event payload (message / tool_call / compaction / approval / ...).
    content: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped["TaskSession"] = relationship(back_populates="events")


class TaskArtifact(Base):
    """Derived artifact attached to a session / event (e.g. compaction summary)."""

    __tablename__ = "task_artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("task_sessions.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("task_session_events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ToolCall(Base):
    """A single tool invocation record (linked to the producing event)."""

    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("task_sessions.id", ondelete="CASCADE"), index=True
    )
    event_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("task_session_events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    arguments: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="success")
    risk_level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    approval_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SessionBranch(Base):
    """Pi-style conversation branch: a named path rooted at ``base_event_id``."""

    __tablename__ = "session_branches"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("task_sessions.id", ondelete="CASCADE"), index=True
    )
    base_event_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(256), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    session: Mapped["TaskSession"] = relationship(back_populates="branches")


class SessionRepository:
    """Async CRUD for sessions and events (foundation for C2 store path).

    Methods take an ``AsyncSession`` so they remain trivially testable with a
    temporary sqlite database (DEV_SPEC §9).
    """

    async def create_session(
        self,
        session,
        *,
        title: str = "",
        task_type: str | None = None,
        environment: str = "dev",
        actor_id: str | None = None,
        id: str | None = None,
    ) -> TaskSession:
        ts = TaskSession(
            id=id or _uuid(),
            title=title,
            task_type=task_type,
            environment=environment,
            actor_id=actor_id,
        )
        session.add(ts)
        await session.flush()
        return ts

    async def get_session(
        self, session, session_id: str
    ) -> TaskSession | None:
        return await session.get(TaskSession, session_id)

    async def append_event(
        self,
        session,
        *,
        session_id: str,
        event_type: str,
        content: dict | None = None,
        parent_event_id: str | None = None,
        seq: int = 0,
        id: str | None = None,
    ) -> TaskSessionEvent:
        """Append a new event (C2 enforces that nothing else mutates history)."""
        ev = TaskSessionEvent(
            id=id or _uuid(),
            session_id=session_id,
            event_type=event_type,
            content=content,
            parent_event_id=parent_event_id,
            seq=seq,
        )
        session.add(ev)
        await session.flush()
        return ev

    async def set_active_event_id(
        self, session, session_id: str, event_id: str | None
    ) -> TaskSession | None:
        ts = await session.get(TaskSession, session_id)
        if ts is None:
            return None
        ts.active_event_id = event_id
        await session.flush()
        return ts

    async def get_event(
        self, session, event_id: str
    ) -> TaskSessionEvent | None:
        return await session.get(TaskSessionEvent, event_id)


def _uuid() -> str:
    from uuid import uuid4

    return uuid4().hex

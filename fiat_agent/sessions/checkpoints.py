"""LangGraph checkpoint store (phase C4, DEV_SPEC C4).

Stores graph-state snapshots so an interrupted task can resume from the last
checkpoint. Every checkpoint is bound to a ``session_id`` (and a LangGraph
``thread_id``); checkpoints form a chain via ``parent_checkpoint_id``.

This module is the storage layer only — the actual LangGraph wiring lands in
phase G. Keeping the store driver-agnostic (SQLite default, PostgreSQL optional
extension point, DEV_SPEC §13) means the same code path serves both.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, String, select
from sqlalchemy.orm import Mapped, mapped_column

from fiat_agent.models.orm import Base

# Ensure the referenced session tables are registered in the shared metadata
# (GraphCheckpoint.session_id FK targets task_sessions), so the ORM model can
# be used standalone without the consumer importing the store module.
from fiat_agent.sessions import store as _store  # noqa: F401


class GraphCheckpoint(Base):
    """One serialized graph-state snapshot."""

    __tablename__ = "graph_checkpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("task_sessions.id", ondelete="CASCADE"), index=True
    )
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    parent_checkpoint_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CheckpointStore:
    """Async save/load for graph checkpoints, bound to a session."""

    async def save_checkpoint(
        self,
        session,
        *,
        session_id: str,
        thread_id: str,
        state: dict,
        checkpoint_id: str | None = None,
        parent_checkpoint_id: str | None = None,
    ) -> GraphCheckpoint:
        from uuid import uuid4

        cp = GraphCheckpoint(
            id=checkpoint_id or uuid4().hex,
            session_id=session_id,
            thread_id=thread_id,
            parent_checkpoint_id=parent_checkpoint_id,
            state=state,
        )
        session.add(cp)
        await session.flush()
        return cp

    async def load_checkpoint(
        self, session, *, session_id: str, checkpoint_id: str
    ) -> Optional[GraphCheckpoint]:
        cp = await session.get(GraphCheckpoint, checkpoint_id)
        if cp is None or cp.session_id != session_id:
            return None
        return cp

    async def load_latest_checkpoint(
        self, session, *, session_id: str, thread_id: str
    ) -> Optional[GraphCheckpoint]:
        """Latest checkpoint for a (session, thread) by creation time."""
        stmt = (
            select(GraphCheckpoint)
            .where(
                GraphCheckpoint.session_id == session_id,
                GraphCheckpoint.thread_id == thread_id,
            )
            .order_by(GraphCheckpoint.created_at.desc())
            .limit(1)
        )
        return (await session.execute(stmt)).scalars().first()

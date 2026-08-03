"""Memory resolver (phase C6, DEV_SPEC C6).

Composes short-term and long-term memory into the agent context:

  - **Short-term memory** is concrete: it is derived from the active session
    path (Pi-style tree) plus the latest graph checkpoint, both of which are
    implemented in C2/C4.
  - **Long-term memory** sources — RAG retrieval, historical tasks, user
    profile/permissions — are *extension points* (DEV_SPEC §13). They are
    intentionally NOT implemented here; instead they plug in via a
    :class:`LongTermProvider` interface. The default provider returns an empty
    long-term memory so the system runs without those backends. Enabling a real
    long-term source is an optional extension point and must be confirmed with
    the user before implementation (per project convention).

Nothing here deletes history; it only reads.
"""

from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pydantic import Field

from fiat_agent.schemas.common import FiatModel
from fiat_agent.sessions.checkpoints import CheckpointStore
from fiat_agent.sessions.store import SessionStore


class ShortTermMemory(FiatModel):
    goal: str = ""
    recent_events: list[dict] = Field(default_factory=list)
    active_branch_id: Optional[str] = None
    last_checkpoint_state: Optional[dict] = None


class LongTermMemory(FiatModel):
    user_profile: dict = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    historical_tasks: list[dict] = Field(default_factory=list)
    rag_hits: list[dict] = Field(default_factory=list)


class MemoryContext(FiatModel):
    short_term: ShortTermMemory
    long_term: LongTermMemory


@runtime_checkable
class LongTermProvider(Protocol):
    """Pluggable source of long-term memory. Implementations are extension
    points (RAG, history, profile) — not shipped by default."""

    async def provide(self, session, *, actor_id: Optional[str] = None) -> LongTermMemory:
        ...


class NullLongTermProvider:
    """Default provider: no long-term backend wired up yet (§13 extension)."""

    async def provide(self, session, *, actor_id: Optional[str] = None) -> LongTermMemory:
        return LongTermMemory()


class MemoryResolver:
    """Builds the agent memory context from session + checkpoint + providers."""

    def __init__(
        self,
        store: SessionStore | None = None,
        checkpoint_store: CheckpointStore | None = None,
        long_term_provider: LongTermProvider | None = None,
    ) -> None:
        self._store = store or SessionStore()
        self._checkpoints = checkpoint_store or CheckpointStore()
        self._long_term = long_term_provider or NullLongTermProvider()

    async def load_short_term_memory(
        self, session, *, session_id: str, limit: int = 20
    ) -> ShortTermMemory:
        path = await self._store.get_active_path(session, session_id)
        goal = ""
        recent: list[dict] = []
        for ev in path[-limit:]:
            c = ev.content or {}
            if ev.event_type == "message" and c.get("role") == "user" and not goal:
                goal = (c.get("text") or c.get("goal") or "").strip()
            recent.append(
                {"id": ev.id, "event_type": ev.event_type, "seq": ev.seq, "summary": _brief(c)}
            )

        branch = await self._store._repo.get_session(session, session_id)
        active_branch_id = branch.active_event_id if branch else None
        cp = await self._checkpoints.load_latest_checkpoint(
            session, session_id=session_id, thread_id=session_id
        )
        return ShortTermMemory(
            goal=goal,
            recent_events=recent,
            active_branch_id=active_branch_id,
            last_checkpoint_state=cp.state if cp else None,
        )

    async def load_long_term_memory(
        self, session, *, actor_id: Optional[str] = None
    ) -> LongTermMemory:
        return await self._long_term.provide(session, actor_id=actor_id)

    async def build_memory_context(
        self, session, *, session_id: str, actor_id: Optional[str] = None
    ) -> MemoryContext:
        short = await self.load_short_term_memory(session, session_id=session_id)
        long = await self.load_long_term_memory(session, actor_id=actor_id)
        return MemoryContext(short_term=short, long_term=long)


def _brief(content: dict) -> str:
    if not content:
        return ""
    if "text" in content:
        return str(content["text"])[:160]
    if "tool_name" in content:
        return f"tool:{content['tool_name']}"
    return (content.get("event_type") or "event")

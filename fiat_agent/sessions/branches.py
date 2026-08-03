"""Session rollback & branching (phase C3, DEV_SPEC C3).

Pi-style conversation tree. Rolling back never deletes history: it only moves
the session ``active_event_id`` pointer so that subsequent appends fork a new
branch off the target event. Production tool effects are NOT auto-reverted by a
rollback (DEV_SPEC C3: "生产操作不因会话回退自动撤销") — callers must undo side
effects explicitly if required.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from fiat_agent.sessions.store import SessionBranch, SessionRepository, SessionStore


class BranchManager:
    """Rollback pointer moves + named branches on top of :class:`SessionStore`."""

    def __init__(
        self,
        store: SessionStore | None = None,
        repo: SessionRepository | None = None,
    ) -> None:
        self._store = store or SessionStore()
        self._repo = repo or SessionRepository()

    async def rollback_to_event(
        self, session, *, session_id: str, event_id: str
    ) -> str:
        """Move the active tip to ``event_id`` (no history deleted).

        Subsequent ``append_event(parent_event_id=event_id)`` calls fork a new
        branch. Returns the new ``active_event_id``.
        """
        ev = await self._repo.get_event(session, event_id)
        if ev is None or ev.session_id != session_id:
            raise KeyError(f"event {event_id} not found in session {session_id}")
        ts = await self._repo.set_active_event_id(session, session_id, event_id)
        if ts is None:
            raise KeyError(f"session {session_id} not found")
        return ts.active_event_id  # type: ignore[return-value]

    async def create_branch(
        self,
        session,
        *,
        session_id: str,
        base_event_id: str,
        name: str = "",
    ) -> SessionBranch:
        """Create a named branch rooted at ``base_event_id`` and make it active.

        Moves the active tip to ``base_event_id`` (history preserved) and
        deactivates other branches of the session so ``get_active_branch`` is
        well-defined. Returns the new :class:`SessionBranch`.
        """
        ev = await self._repo.get_event(session, base_event_id)
        if ev is None or ev.session_id != session_id:
            raise KeyError(f"event {base_event_id} not found in session {session_id}")

        # Deactivate existing branches so only one is active.
        existing = (
            await session.execute(
                select(SessionBranch).where(
                    SessionBranch.session_id == session_id,
                    SessionBranch.active.is_(True),
                )
            )
        ).scalars().all()
        for b in existing:
            b.active = False

        from uuid import uuid4

        branch = SessionBranch(
            id=uuid4().hex,
            session_id=session_id,
            base_event_id=base_event_id,
            name=name,
            active=True,
        )
        session.add(branch)
        await session.flush()
        # Point the conversation tip at the branch base; new messages extend it.
        await self._repo.set_active_event_id(session, session_id, base_event_id)
        return branch

    async def get_active_branch(
        self, session, session_id: str
    ) -> Optional[SessionBranch]:
        """Return the active branch for the session, or ``None`` if none."""
        stmt = select(SessionBranch).where(
            SessionBranch.session_id == session_id,
            SessionBranch.active.is_(True),
        )
        return (await session.execute(stmt)).scalars().first()

    async def get_branch_path(
        self, session, *, session_id: str, branch_id: str
    ) -> list:
        """Events from the branch base up to the current active tip.

        Used for replay/export of a specific branch. If ``base_event_id`` is
        ``None``, the path runs from the root.
        """
        from fiat_agent.sessions.store import TaskSessionEvent

        branch = await session.get(SessionBranch, branch_id)
        if branch is None or branch.session_id != session_id:
            raise KeyError(f"branch {branch_id} not found in session {session_id}")

        active = (await self._repo.get_session(session, session_id)).active_event_id
        if active is None:
            return []
        full = await self._store.get_event_path(
            session, session_id=session_id, event_id=active
        )
        if branch.base_event_id is None:
            return full
        # Trim to start at the branch base.
        for i, ev in enumerate(full):
            if ev.id == branch.base_event_id:
                return full[i:]
        return []

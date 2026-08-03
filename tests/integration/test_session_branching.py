"""C3 integration test: rollback & branching (DEV_SPEC C3).

Builds the real schema via Alembic on a temporary sqlite database, then
exercises :class:`BranchManager`. Verifies that rollback preserves history and
that new messages fork a new branch.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from fiat_agent.config import DatabaseConfig, Settings
from fiat_agent.db import get_async_engine, session_scope
from fiat_agent.sessions.branches import BranchManager
from fiat_agent.sessions.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'branching.db'}"


def _migrate(url: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.mark.integration
def test_rollback_preserves_history_and_forks(tmp_path: Path) -> None:
    url = _url(tmp_path)
    _migrate(url)
    engine = get_async_engine(Settings(database=DatabaseConfig(url=url)))
    store = SessionStore()
    branches = BranchManager(store=store)

    async def _run() -> None:
        async with session_scope(engine=engine) as s:
            session = await store.create_session(s, title="rollback")
            await s.commit()
            sid = session.id

            e1 = await store.append_event(s, session_id=sid, event_type="message", content={"n": 1})
            e2 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e1.id, content={"n": 2})
            e3 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e2.id, content={"n": 3})
            await s.commit()

            # Roll back to e2: history (e3) is NOT deleted.
            await branches.rollback_to_event(s, session_id=sid, event_id=e2.id)
            await s.commit()
            events = await store.list_session_events(s, sid)
            assert len(events) == 3  # e3 still present
            assert (await store._repo.get_session(s, sid)).active_event_id == e2.id

            # New message forks off e2 -> forms a new branch (new event id).
            e4 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e2.id, content={"n": 4})
            await s.commit()
            assert e4.id != e3.id
            path = await store.get_active_path(s, sid)
            assert [e.id for e in path] == [e1.id, e2.id, e4.id]

    asyncio.run(_run())
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_create_branch_and_active_branch(tmp_path: Path) -> None:
    url = _url(tmp_path)
    _migrate(url)
    engine = get_async_engine(Settings(database=DatabaseConfig(url=url)))
    store = SessionStore()
    branches = BranchManager(store=store)

    async def _run() -> None:
        async with session_scope(engine=engine) as s:
            session = await store.create_session(s, title="branch")
            await s.commit()
            sid = session.id
            e1 = await store.append_event(s, session_id=sid, event_type="message")
            e2 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e1.id)
            await s.commit()

            b = await branches.create_branch(s, session_id=sid, base_event_id=e1.id, name="alt")
            await s.commit()
            assert b.active is True
            assert b.base_event_id == e1.id
            assert (await store._repo.get_session(s, sid)).active_event_id == e1.id

            active = await branches.get_active_branch(s, sid)
            assert active is not None
            assert active.id == b.id

            # Branch checks out the base as the active tip, so its path is [e1]
            # (e2 stays in the DB but is off the active path until re-appended).
            bpath = await branches.get_branch_path(s, session_id=sid, branch_id=b.id)
            assert [e.id for e in bpath] == [e1.id]

    asyncio.run(_run())
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_second_branch_deactivates_previous(tmp_path: Path) -> None:
    url = _url(tmp_path)
    _migrate(url)
    engine = get_async_engine(Settings(database=DatabaseConfig(url=url)))
    store = SessionStore()
    branches = BranchManager(store=store)

    async def _run() -> None:
        async with session_scope(engine=engine) as s:
            session = await store.create_session(s, title="multibranch")
            await s.commit()
            sid = session.id
            e1 = await store.append_event(s, session_id=sid, event_type="message")
            await s.commit()
            b1 = await branches.create_branch(s, session_id=sid, base_event_id=e1.id, name="b1")
            b2 = await branches.create_branch(s, session_id=sid, base_event_id=e1.id, name="b2")
            await s.commit()
            assert b1.active is False
            assert b2.active is True
            active = await branches.get_active_branch(s, sid)
            assert active is not None and active.id == b2.id

    asyncio.run(_run())
    asyncio.run(engine.dispose())

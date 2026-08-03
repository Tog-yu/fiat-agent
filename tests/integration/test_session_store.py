"""C2 integration test: append-only session write path + event-path (DEV_SPEC C2).

Builds the real schema via Alembic on a temporary sqlite database (no external
PostgreSQL service, per §9), then exercises :class:`SessionStore`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from fiat_agent.config import DatabaseConfig, Settings
from fiat_agent.db import get_async_engine, session_scope
from fiat_agent.sessions.store import SessionStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'session_store.db'}"


def _migrate(url: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.mark.integration
def test_append_advances_active_event_id(tmp_path: Path) -> None:
    url = _url(tmp_path)
    _migrate(url)
    engine = get_async_engine(Settings(database=DatabaseConfig(url=url)))
    store = SessionStore()

    async def _run() -> None:
        async with session_scope(engine=engine) as s:
            session = await store.create_session(s, title="t", environment="dev")
            await s.commit()
            sid = session.id

            e1 = await store.append_event(s, session_id=sid, event_type="message", content={"t": 1})
            active = (await store._repo.get_session(s, sid)).active_event_id
            assert active == e1.id

            e2 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e1.id, content={"t": 2})
            active = (await store._repo.get_session(s, sid)).active_event_id
            assert active == e2.id

            path = await store.get_active_path(s, sid)
            assert [e.id for e in path] == [e1.id, e2.id]

    asyncio.run(_run())
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_get_event_path_root_to_event(tmp_path: Path) -> None:
    url = _url(tmp_path)
    _migrate(url)
    engine = get_async_engine(Settings(database=DatabaseConfig(url=url)))
    store = SessionStore()

    async def _run() -> None:
        async with session_scope(engine=engine) as s:
            session = await store.create_session(s, title="chain")
            await s.commit()
            sid = session.id
            e1 = await store.append_event(s, session_id=sid, event_type="message")
            e2 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e1.id)
            e3 = await store.append_event(s, session_id=sid, event_type="message", parent_event_id=e2.id)
            await s.commit()

            path = await store.get_event_path(s, session_id=sid, event_id=e3.id)
            assert [e.id for e in path] == [e1.id, e2.id, e3.id]
            active = await store.get_active_path(s, sid)
            assert [e.id for e in active] == [e1.id, e2.id, e3.id]

    asyncio.run(_run())
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_list_session_events_ordered_by_seq(tmp_path: Path) -> None:
    url = _url(tmp_path)
    _migrate(url)
    engine = get_async_engine(Settings(database=DatabaseConfig(url=url)))
    store = SessionStore()

    async def _run() -> None:
        async with session_scope(engine=engine) as s:
            session = await store.create_session(s, title="order")
            await s.commit()
            sid = session.id
            for _ in range(3):
                await store.append_event(s, session_id=sid, event_type="message")
            events = await store.list_session_events(s, sid)
            seqs = [e.seq for e in events]
            assert seqs == sorted(seqs)
            assert len(seqs) == 3

    asyncio.run(_run())
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_history_is_immutable_by_design(tmp_path: Path) -> None:
    # The store must not expose any mutation API for existing event content;
    # writers only ever append.
    store = SessionStore()
    mutators = [n for n in dir(store) if n.startswith("update") or n.startswith("set_")]
    # Only append + the active-event pointer setter are allowed; no content edits.
    assert not any("event_content" in n or "edit" in n for n in mutators)
    assert hasattr(store, "append_event")
    assert not hasattr(store, "update_event")

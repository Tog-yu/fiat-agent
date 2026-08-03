"""C1 unit test: Session Memory Store models + repository (DEV_SPEC C1).

Uses a temporary sqlite database (no external Postgres), per §9.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fiat_agent.models.base import Base
from fiat_agent.sessions.store import (
    SessionBranch,
    SessionRepository,
    TaskArtifact,
    TaskSession,
    TaskSessionEvent,
    ToolCall,
)


def _engine(tmp_path: Path):
    return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}")


@pytest.mark.unit
def test_session_model_defaults(tmp_path: Path) -> None:
    async def _run() -> None:
        engine = _engine(tmp_path)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        repo = SessionRepository()
        async with maker() as s:
            ts = await repo.create_session(s, title="诊断任务", task_type="diagnose", environment="staging")
            await s.commit()
            assert ts.id
            assert ts.title == "诊断任务"
            assert ts.task_type == "diagnose"
            assert ts.environment == "staging"
            assert ts.status == "active"
            assert ts.active_event_id is None
        await engine.dispose()

    asyncio.run(_run())


@pytest.mark.unit
def test_event_parent_linking(tmp_path: Path) -> None:
    async def _run() -> None:
        engine = _engine(tmp_path)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        repo = SessionRepository()
        async with maker() as s:
            ts = await repo.create_session(s, title="t")
            await s.commit()

            root = await repo.append_event(
                s, session_id=ts.id, event_type="message", content={"role": "user", "text": "hi"}, seq=1
            )
            child = await repo.append_event(
                s,
                session_id=ts.id,
                event_type="message",
                content={"role": "assistant", "text": "hello"},
                parent_event_id=root.id,
                seq=2,
            )
            await s.commit()

            assert child.parent_event_id == root.id
            fetched_root = await repo.get_event(s, root.id)
            assert fetched_root is not None
            assert fetched_root.seq == 1
            assert child.seq == 2

            updated = await repo.set_active_event_id(s, ts.id, child.id)
            await s.commit()
            assert updated is not None
            assert updated.active_event_id == child.id
        await engine.dispose()

    asyncio.run(_run())


@pytest.mark.unit
def test_all_session_tables_exist(tmp_path: Path) -> None:
    async def _run() -> None:
        engine = _engine(tmp_path)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as s:
            s.add(TaskSession(id="s1", title="t"))
            s.add(TaskSessionEvent(id="e1", session_id="s1", event_type="message"))
            s.add(TaskArtifact(id="a1", session_id="s1", kind="compaction"))
            s.add(ToolCall(id="tc1", session_id="s1", tool_name="shell"))
            s.add(SessionBranch(id="b1", session_id="s1"))
            await s.commit()
        await engine.dispose()

    asyncio.run(_run())

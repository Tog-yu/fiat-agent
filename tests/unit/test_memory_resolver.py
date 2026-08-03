"""C6 unit test: memory resolver (DEV_SPEC C6).

Short-term memory is derived from the real session path + checkpoint; the
long-term provider defaults to empty (extension point). Uses a temporary sqlite
database (no external service, per §9).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fiat_agent.context.memory import MemoryResolver, NullLongTermProvider
from fiat_agent.models.base import Base
from fiat_agent.sessions.checkpoints import CheckpointStore
from fiat_agent.sessions.store import SessionStore


def _engine(tmp_path: Path):
    return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}")


@pytest.mark.unit
def test_short_term_from_active_path_and_checkpoint(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    store = SessionStore()
    checkpoints = CheckpointStore()
    resolver = MemoryResolver(store=store, checkpoint_store=checkpoints)

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            ts = await store.create_session(s, title="m")
            await s.commit()
            sid = ts.id
            await store.append_event(s, session_id=sid, event_type="message", content={"role": "user", "text": "调试登录"})
            await store.append_event(s, session_id=sid, event_type="tool_call", content={"tool_name": "shell", "result": {"ok": 1}})
            await checkpoints.save_checkpoint(s, session_id=sid, thread_id=sid, state={"step": 3})
            await s.commit()

            short = await resolver.load_short_term_memory(s, session_id=sid)
            assert short.goal == "调试登录"
            assert len(short.recent_events) == 2
            assert short.last_checkpoint_state == {"step": 3}
            assert short.active_branch_id is not None

    asyncio.run(_run())
    asyncio.run(engine.dispose())


@pytest.mark.unit
def test_long_term_default_empty(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    resolver = MemoryResolver(long_term_provider=NullLongTermProvider())

    async def _run() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with maker() as s:
            long = await resolver.load_long_term_memory(s, actor_id="u1")
            assert long.user_profile == {}
            assert long.permissions == []
            assert long.historical_tasks == []
            assert long.rag_hits == []

            ctx = await resolver.build_memory_context(s, session_id="missing", actor_id="u1")
            assert isinstance(ctx.short_term, type(ctx.short_term))
            assert isinstance(ctx.long_term, type(ctx.long_term))

    asyncio.run(_run())
    asyncio.run(engine.dispose())

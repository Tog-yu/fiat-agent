"""C4 integration test: LangGraph checkpoint store (DEV_SPEC C4).

Builds the real schema via Alembic on a temporary sqlite database, then
exercises :class:`CheckpointStore` — save, load by id, load latest, and resume
from an interrupted (parent) checkpoint, all bound to a ``session_id``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from fiat_agent.config import DatabaseConfig, Settings
from fiat_agent.db import get_async_engine, session_scope
from fiat_agent.sessions.checkpoints import CheckpointStore

REPO_ROOT = Path(__file__).resolve().parents[2]


def _url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'checkpoints.db'}"


def _migrate(url: str) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")


@pytest.mark.integration
def test_save_and_load_checkpoint(tmp_path: Path) -> None:
    url = _url(tmp_path)
    _migrate(url)
    engine = get_async_engine(Settings(database=DatabaseConfig(url=url)))
    store = CheckpointStore()

    async def _run() -> None:
        async with session_scope(engine=engine) as s:
            cp = await store.save_checkpoint(
                s, session_id="s1", thread_id="t1", state={"step": 1, "x": 10}
            )
            await s.commit()
            loaded = await store.load_checkpoint(s, session_id="s1", checkpoint_id=cp.id)
            assert loaded is not None
            assert loaded.state == {"step": 1, "x": 10}
            # Wrong session must not resolve the checkpoint.
            assert await store.load_checkpoint(s, session_id="other", checkpoint_id=cp.id) is None

    asyncio.run(_run())
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_load_latest_and_resume_chain(tmp_path: Path) -> None:
    url = _url(tmp_path)
    _migrate(url)
    engine = get_async_engine(Settings(database=DatabaseConfig(url=url)))
    store = CheckpointStore()

    async def _run() -> None:
        async with session_scope(engine=engine) as s:
            c1 = await store.save_checkpoint(s, session_id="s1", thread_id="t1", state={"step": 1})
            c2 = await store.save_checkpoint(
                s, session_id="s1", thread_id="t1", state={"step": 2}, parent_checkpoint_id=c1.id
            )
            await s.commit()

            latest = await store.load_latest_checkpoint(s, session_id="s1", thread_id="t1")
            assert latest is not None
            assert latest.id == c2.id
            assert latest.parent_checkpoint_id == c1.id
            # Resume: the latest state is the recovery point.
            assert latest.state == {"step": 2}

    asyncio.run(_run())
    asyncio.run(engine.dispose())

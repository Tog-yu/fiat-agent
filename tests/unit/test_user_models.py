"""B2 unit test: user enable/disable + multi-role binding (DEV_SPEC B2).

Uses a temporary sqlite database (no external Postgres), per §9.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from fiat_agent.models.orm import Base
from fiat_agent.users.models import Role, User
from fiat_agent.users.repository import UserRepository


def _engine(tmp_path: Path):
    return create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'users.db'}")


@pytest.mark.unit
def test_user_enable_disable(tmp_path: Path) -> None:
    async def _run() -> None:
        engine = _engine(tmp_path)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        repo = UserRepository()
        async with maker() as s:
            user = await repo.create_user(s, username="alice")
            await s.commit()
            assert user.enabled is True

            await repo.set_enabled(s, user.id, False)
            await s.commit()
            refreshed = await repo.get(s, user.id)
            assert refreshed is not None
            assert refreshed.enabled is False
        await engine.dispose()

    asyncio.run(_run())


@pytest.mark.unit
def test_user_multiple_roles(tmp_path: Path) -> None:
    async def _run() -> None:
        engine = _engine(tmp_path)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        repo = UserRepository()
        async with maker() as s:
            user = await repo.create_user(s, username="bob")
            ops = await repo.create_role(s, name="ops")
            oncall = await repo.create_role(s, name="oncall")
            await s.commit()

            await repo.assign_role(s, user.id, ops.id)
            await repo.assign_role(s, user.id, oncall.id)
            await s.commit()

            roles = await repo.list_roles(s, user.id)
            assert {r.name for r in roles} == {"ops", "oncall"}
        await engine.dispose()

    asyncio.run(_run())

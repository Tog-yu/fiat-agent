"""Async database engine + session (phase B1, DEV_SPEC B1).

DB-agnostic SQLAlchemy 2.0 async layer. The driver is selected purely by the
``database.url`` scheme, so switching databases is a config change, not a code
change:

  - SQLite  (current default): ``sqlite+aiosqlite:///...`` — zero-ops, no
    external service. Used for development, single-node and low-risk scenarios.
  - PostgreSQL (extension point, not yet enabled):
    ``postgresql+asyncpg://...`` — install the optional ``[postgres]`` extra
    and set ``FIAT_DB_URL``. Provides concurrency, JSONB, replication and the
    scale needed for the append-only session event store.

Tests use a temporary sqlite+aiosqlite database so they run without any
external service (DEV_SPEC §9: tests must not depend on external services).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from fiat_agent.config import Settings
from fiat_agent.errors import FiatAgentError

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_async_engine(settings: Settings) -> AsyncEngine:
    """Create (and cache) the async engine from ``settings.database.url``.

    Raises:
        FiatAgentError: if ``database.url`` is empty (fail-fast, deterministic).
    """
    global _engine, _sessionmaker
    url = settings.database.url
    if not url:
        raise FiatAgentError(
            code="DB_NO_URL", message="database.url 未配置，无法创建引擎"
        )
    connect_args: dict = {}
    if url.startswith("sqlite"):
        # Only the synchronous pysqlite driver needs check_same_thread=False.
        connect_args = {"check_same_thread": False}
        # Auto-create the parent directory for file-based sqlite URLs so the
        # default `sqlite+aiosqlite:///./data/fiat_agent.db` works out of the box.
        if ":///" in url:
            file_part = url.split("///", 1)[1].split("?", 1)[0].split("#", 1)[0]
            if file_part and not file_part.startswith(":"):
                from pathlib import Path

                Path(file_part).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_async_engine(
        url, future=True, pool_pre_ping=True, connect_args=connect_args
    )
    _sessionmaker = async_sessionmaker(
        _engine, expire_on_commit=False, class_=AsyncSession
    )
    return _engine


def get_session(engine: AsyncEngine | None = None) -> AsyncSession:
    """Return a new :class:`AsyncSession`.

    Uses the ``engine`` passed in, or the globally cached engine from the last
    :func:`get_async_engine` call.
    """
    if engine is not None:
        return async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )()
    if _sessionmaker is None:
        raise FiatAgentError(
            code="DB_NO_ENGINE",
            message="engine 未初始化，请先调用 get_async_engine(settings)",
        )
    return _sessionmaker()


@asynccontextmanager
async def session_scope(
    engine: AsyncEngine | None = None,
) -> AsyncIterator[AsyncSession]:
    """Async context manager yielding a session with commit/rollback."""
    session = get_session(engine=engine)
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def ping(engine: AsyncEngine | None = None) -> int:
    """Run ``SELECT 1`` and return the scalar — used by health checks/tests."""
    async with session_scope(engine=engine) as session:
        result = await session.execute(text("SELECT 1"))
        return result.scalar_one()

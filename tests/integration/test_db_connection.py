"""B1 integration test: DB connection + migration (DEV_SPEC B1).

Uses a temporary sqlite+aiosqlite database so the test is deterministic and
does not require an external PostgreSQL service (DEV_SPEC §9: tests must not
depend on external services). The same code path serves PostgreSQL in prod.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from fiat_agent.config import DatabaseConfig, Settings
from fiat_agent.db import get_async_engine, get_session, session_scope

REPO_ROOT = Path(__file__).resolve().parents[2]


def _sqlite_file_url(tmp_path: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"


@pytest.mark.integration
def test_get_async_engine_creates_engine(tmp_path: Path) -> None:
    settings = Settings(database=DatabaseConfig(url=_sqlite_file_url(tmp_path)))
    engine = get_async_engine(settings)
    assert engine is not None
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_session_select_one(tmp_path: Path) -> None:
    settings = Settings(database=DatabaseConfig(url=_sqlite_file_url(tmp_path)))
    engine = get_async_engine(settings)

    async def _run() -> int:
        async with session_scope(engine=engine) as session:
            from sqlalchemy import text

            result = await session.execute(text("SELECT 1"))
            return result.scalar_one()

    assert asyncio.run(_run()) == 1
    asyncio.run(engine.dispose())


@pytest.mark.integration
def test_get_session_requires_engine(tmp_path: Path) -> None:
    # A fresh global engine cache must be populated first.
    settings = Settings(database=DatabaseConfig(url=_sqlite_file_url(tmp_path)))
    get_async_engine(settings)
    session = get_session()
    assert session is not None
    asyncio.run(session.close())


@pytest.mark.integration
def test_migration_creates_empty_schema(tmp_path: Path) -> None:
    url = _sqlite_file_url(tmp_path)
    cfg = Config()
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")

    # Alembic creates the version table even for an empty migration.
    db_path = url.replace("sqlite+aiosqlite:///", "")
    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()
    assert "alembic_version" in tables

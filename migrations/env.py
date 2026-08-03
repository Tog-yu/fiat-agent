"""Alembic async env (phase B1, DEV_SPEC B1).

Reads the database URL from the alembic config's ``sqlalchemy.url`` (set by
``alembic.ini`` or by the test), falling back to the ``DATABASE_URL`` env var.
Supports PostgreSQL (asyncpg) in production and sqlite+aiosqlite for tests.
"""

from __future__ import annotations

import asyncio
import os

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from fiat_agent.config import DatabaseConfig, Settings
from fiat_agent.models.orm import Base

config = context.config

# C1: ORM models are now declared (users, sessions, ...). Point Alembic at the
# shared metadata so ``alembic revision --autogenerate`` can diff against it.
target_metadata = Base.metadata


def get_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    env_url = os.environ.get("DATABASE_URL")
    if env_url:
        return env_url
    raise RuntimeError("未配置 sqlalchemy.url 或 DATABASE_URL，无法运行 migration")


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": get_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online_sync() -> None:
    asyncio.run(run_migrations_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online_sync()

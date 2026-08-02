"""Shared SQLAlchemy declarative base (phase B2, DEV_SPEC B2)."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base for all ORM models.

    Metadata is shared, so Alembic autogenerate and test-time table creation
    see every model registered under ``Base``.
    """

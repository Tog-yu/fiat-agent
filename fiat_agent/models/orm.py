"""ORM declarative base (phase B2, DEV_SPEC B2).

Single shared SQLAlchemy ``Base`` for all ORM models. It lives in its own
module so the persistence layer is cleanly separated from the LLM interface in
:mod:`fiat_agent.models.base` — importing one does not drag in the other.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base for all ORM models.

    Metadata is shared, so Alembic autogenerate and test-time table creation
    see every model registered under ``Base``.
    """

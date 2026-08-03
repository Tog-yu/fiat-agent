"""Create session Memory Store tables (phase C1, DEV_SPEC C1).

Five tables back the append-only session event store (Pi-style session tree):

  - ``task_sessions``        : one task conversation / session
  - ``task_session_events``  : append-only events linked by ``parent_event_id``
  - ``task_artifacts``       : derived artifacts (e.g. compaction summaries)
  - ``tool_calls``           : tool invocation records (linked to events)
  - ``session_branches``     : Pi-style conversation branches

Tables are dialect-agnostic (``sa.JSON`` works on both SQLite and PostgreSQL;
``render_as_batch=True`` in env.py keeps ALTER-compatible on SQLite). PostgreSQL
is an optional extension point (DEV_SPEC §13) — no PG-specific types are used.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_sessions"
down_revision: str | None = "0001_empty"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_sessions",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("title", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("task_type", sa.String(length=64), nullable=True),
        sa.Column("environment", sa.String(length=32), nullable=False, server_default="dev"),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("active_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_sessions_task_type", "task_sessions", ["task_type"])
    op.create_index("ix_task_sessions_actor_id", "task_sessions", ["actor_id"])
    op.create_index("ix_task_sessions_active_event_id", "task_sessions", ["active_event_id"])

    op.create_table(
        "task_session_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=64),
            sa.ForeignKey("task_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("parent_event_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_session_events_session_id", "task_session_events", ["session_id"])
    op.create_index(
        "ix_task_session_events_parent_event_id", "task_session_events", ["parent_event_id"]
    )
    op.create_index("ix_task_session_events_event_type", "task_session_events", ["event_type"])

    op.create_table(
        "task_artifacts",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=64),
            sa.ForeignKey("task_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.String(length=64),
            sa.ForeignKey("task_session_events.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_artifacts_session_id", "task_artifacts", ["session_id"])
    op.create_index("ix_task_artifacts_event_id", "task_artifacts", ["event_id"])
    op.create_index("ix_task_artifacts_kind", "task_artifacts", ["kind"])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=64),
            sa.ForeignKey("task_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            sa.String(length=64),
            sa.ForeignKey("task_session_events.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="success"),
        sa.Column("risk_level", sa.String(length=16), nullable=True),
        sa.Column("approval_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tool_calls_session_id", "tool_calls", ["session_id"])
    op.create_index("ix_tool_calls_event_id", "tool_calls", ["event_id"])
    op.create_index("ix_tool_calls_tool_name", "tool_calls", ["tool_name"])

    op.create_table(
        "session_branches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=64),
            sa.ForeignKey("task_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("base_event_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_session_branches_session_id", "session_branches", ["session_id"])
    op.create_index(
        "ix_session_branches_base_event_id", "session_branches", ["base_event_id"]
    )


def downgrade() -> None:
    op.drop_table("session_branches")
    op.drop_table("tool_calls")
    op.drop_table("task_artifacts")
    op.drop_table("task_session_events")
    op.drop_table("task_sessions")

"""Create graph_checkpoints table (phase C4, DEV_SPEC C4).

Stores LangGraph state snapshots bound to a session, enabling interrupted-task
resume. Dialect-agnostic (``sa.JSON`` works on SQLite and PostgreSQL); the
PostgreSQL backend is an optional extension point (DEV_SPEC §13).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_checkpoints"
down_revision: str | None = "0002_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_checkpoints",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(length=64),
            sa.ForeignKey("task_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(length=64), nullable=True),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_graph_checkpoints_session_id", "graph_checkpoints", ["session_id"]
    )
    op.create_index(
        "ix_graph_checkpoints_thread_id", "graph_checkpoints", ["thread_id"]
    )
    op.create_index(
        "ix_graph_checkpoints_parent_checkpoint_id",
        "graph_checkpoints",
        ["parent_checkpoint_id"],
    )


def downgrade() -> None:
    op.drop_table("graph_checkpoints")

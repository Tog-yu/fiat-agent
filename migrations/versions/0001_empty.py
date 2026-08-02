"""Initial empty schema (phase B1).

At B1 there are no domain models yet (User/Role arrive in B2), so this
migration is intentionally empty. Running ``alembic upgrade head`` still
creates the ``alembic_version`` table, proving the migration pipeline can
build an empty schema. Later phases add real tables via new revisions.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_empty"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

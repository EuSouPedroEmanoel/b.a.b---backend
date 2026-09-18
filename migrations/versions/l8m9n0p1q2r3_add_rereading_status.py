"""Add the rereading personal reading status."""

from typing import Sequence, Union

from alembic import op


revision: str = 'l8m9n0p1q2r3'
down_revision: Union[str, Sequence[str], None] = 'k7l8m9n0p1q2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE readingstatus ADD VALUE IF NOT EXISTS 'rereading'"
    )


def downgrade() -> None:
    # PostgreSQL does not safely remove enum values in place. The value is
    # harmless for existing rows and can be removed in a deliberate rewrite.
    pass

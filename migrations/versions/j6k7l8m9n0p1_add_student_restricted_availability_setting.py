"""Add school setting for student restricted availability filters."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'j6k7l8m9n0p1'
down_revision: Union[str, Sequence[str], None] = 'j5k6l7m8n9o0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'schools',
        sa.Column(
            'allow_student_restricted_availability',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column('schools', 'allow_student_restricted_availability', server_default=None)


def downgrade() -> None:
    op.drop_column('schools', 'allow_student_restricted_availability')

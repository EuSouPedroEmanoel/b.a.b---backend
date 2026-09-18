"""Add school setting for student condition filtering."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'j5k6l7m8n9o0'
down_revision: Union[str, Sequence[str], None] = 'j4k5l6m7n8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'schools',
        sa.Column(
            'allow_student_condition_filter',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column('schools', 'allow_student_condition_filter', server_default=None)


def downgrade() -> None:
    op.drop_column('schools', 'allow_student_condition_filter')

"""Remove legacy terms acceptance fields."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 't6u7v8w9x0y1'
down_revision: Union[str, Sequence[str], None] = 's5t6u7v8w9x0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('users', 'terms_accepted_at')
    op.drop_column('users', 'terms_accepted_version')


def downgrade() -> None:
    op.add_column(
        'users',
        sa.Column('terms_accepted_version', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'users', sa.Column('terms_accepted_at', sa.DateTime(), nullable=True)
    )

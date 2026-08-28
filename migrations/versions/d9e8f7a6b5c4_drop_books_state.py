"""drop books.state

Revision ID: d9e8f7a6b5c4
Revises: a1b2c3d4e5f6
Create Date: 2026-08-28

Remove the persisted Book.state column. The book's state is now derived
dynamically from its BookCopy states (per school), see Book.derived_state.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd9e8f7a6b5c4'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('books', 'state')


def downgrade() -> None:
    op.add_column(
        'books',
        sa.Column(
            'state',
            sa.Enum(
                'available',
                'borrowed',
                'reserved',
                'lost',
                'archived',
                name='booksstate',
                native_enum=False,
            ),
            nullable=False,
            server_default='available',
        ),
    )

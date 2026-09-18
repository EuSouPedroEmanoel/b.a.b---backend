"""Add personal reading statuses for students."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'k7l8m9n0p1q2'
down_revision: Union[str, Sequence[str], None] = 'j6k7l8m9n0p1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    reading_status = sa.Enum(
        'want_to_read', 'reading', 'read', name='readingstatus'
    )
    op.create_table(
        'user_reading_statuses',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('status', reading_status, nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'book_id', name='uq_user_reading_status_user_book'
        ),
    )
    op.create_index(
        'ix_user_reading_status_user_status',
        'user_reading_statuses',
        ['user_id', 'status'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_user_reading_status_user_status',
        table_name='user_reading_statuses',
    )
    op.drop_table('user_reading_statuses')
    sa.Enum(name='readingstatus').drop(op.get_bind(), checkfirst=True)

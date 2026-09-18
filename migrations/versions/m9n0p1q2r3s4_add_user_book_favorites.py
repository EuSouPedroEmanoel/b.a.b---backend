"""Add personal book favorites for students."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'm9n0p1q2r3s4'
down_revision: Union[str, Sequence[str], None] = 'l8m9n0p1q2r3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_book_favorites',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'user_id', 'book_id', name='uq_user_book_favorite_user_book'
        ),
    )
    op.create_index(
        'ix_user_book_favorite_user', 'user_book_favorites', ['user_id']
    )


def downgrade() -> None:
    op.drop_index(
        'ix_user_book_favorite_user', table_name='user_book_favorites'
    )
    op.drop_table('user_book_favorites')

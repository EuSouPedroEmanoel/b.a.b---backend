"""add genres N:N

Revision ID: 9a8b7c6d5e4f
Revises: e5f6a7b8c9d0
Create Date: 2026-08-29

Add genres table and book_genres association for many-to-many Book <-> Genre.
Auto-creation of genres on ISBN bip is handled in application layer.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9a8b7c6d5e4f'
down_revision: Union[str, Sequence[str], None] = 'a3f9d2c1b4e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'genres',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('slug', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('slug', name='uq_genres_slug'),
    )
    op.create_index('ix_genres_slug', 'genres', ['slug'])
    op.create_index('ix_genres_name', 'genres', ['name'])

    op.create_table(
        'book_genres',
        sa.Column('book_id', sa.Integer, sa.ForeignKey('books.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('genre_id', sa.Integer, sa.ForeignKey('genres.id', ondelete='CASCADE'), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table('book_genres')
    op.drop_index('ix_genres_name', table_name='genres')
    op.drop_index('ix_genres_slug', table_name='genres')
    op.drop_table('genres')

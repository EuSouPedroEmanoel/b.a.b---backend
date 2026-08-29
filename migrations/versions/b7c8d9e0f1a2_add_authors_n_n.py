"""add authors N:N

Revision ID: b7c8d9e0f1a2
Revises: 9a8b7c6d5e4f
Create Date: 2026-08-29

Add authors table and book_authors association for many-to-many Book <-> Author.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = '9a8b7c6d5e4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'authors',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('slug', name='uq_authors_slug'),
    )
    op.create_index('ix_authors_slug', 'authors', ['slug'])
    op.create_index('ix_authors_name', 'authors', ['name'])

    op.create_table(
        'book_authors',
        sa.Column('book_id', sa.Integer, sa.ForeignKey('books.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('author_id', sa.Integer, sa.ForeignKey('authors.id', ondelete='CASCADE'), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table('book_authors')
    op.drop_index('ix_authors_name', table_name='authors')
    op.drop_index('ix_authors_slug', table_name='authors')
    op.drop_table('authors')

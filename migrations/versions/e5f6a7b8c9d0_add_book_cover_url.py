"""add book cover_url

Revision ID: e5f6a7b8c9d0
Revises: d9e8f7a6b5c4
Create Date: 2026-08-28

Add a nullable cover_url column to books for the book cover image (e.g. from
Google Books / BrasilAPI lookup).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd9e8f7a6b5c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'books',
        sa.Column('cover_url', sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('books', 'cover_url')

"""Add school-specific book metadata overrides."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'g1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'book_school_overrides',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('title_overridden', sa.Boolean(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('description_overridden', sa.Boolean(), nullable=False),
        sa.Column('cover_url', sa.String(), nullable=True),
        sa.Column('cover_url_overridden', sa.Boolean(), nullable=False),
        sa.Column('published_date', sa.Date(), nullable=True),
        sa.Column('published_date_overridden', sa.Boolean(), nullable=False),
        sa.Column('genres_overridden', sa.Boolean(), nullable=False),
        sa.Column('authors_overridden', sa.Boolean(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('edited_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            'NOT title_overridden OR title IS NOT NULL',
            name='ck_book_override_title_value',
        ),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['edited_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('school_id', 'book_id', name='uq_book_school_override'),
    )
    op.create_table(
        'book_school_override_genres',
        sa.Column('override_id', sa.Integer(), nullable=False),
        sa.Column('genre_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['override_id'], ['book_school_overrides.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['genre_id'], ['genres.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('override_id', 'genre_id'),
    )
    op.create_table(
        'book_school_override_authors',
        sa.Column('override_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['override_id'], ['book_school_overrides.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['authors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('override_id', 'author_id'),
    )


def downgrade() -> None:
    op.drop_table('book_school_override_authors')
    op.drop_table('book_school_override_genres')
    op.drop_table('book_school_overrides')

"""rename user_id to added_by and add edited_by on books/book_copies

Revision ID: a1b2c3d4e5f6
Revises: 49d6e1e30a69
Create Date: 2026-08-28
Preserves existing data: rename moves values, edited_by NULL for old rows
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '49d6e1e30a69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- books ---
    op.execute('ALTER TABLE books RENAME COLUMN user_id TO added_by')
    # rename FK if exists (name varies)
    op.execute('ALTER TABLE books DROP CONSTRAINT IF EXISTS books_user_id_fkey')
    op.execute('ALTER TABLE books DROP CONSTRAINT IF EXISTS books_added_by_fkey')
    op.create_foreign_key(
        'fk_books_added_by', 'books', 'users', ['added_by'], ['id']
    )
    op.add_column('books', sa.Column('edited_by', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_books_edited_by', 'books', 'users', ['edited_by'], ['id']
    )

    # --- book_copies ---
    op.execute('ALTER TABLE book_copies RENAME COLUMN user_id TO added_by')
    op.execute('ALTER TABLE book_copies DROP CONSTRAINT IF EXISTS book_copies_user_id_fkey')
    op.execute('ALTER TABLE book_copies DROP CONSTRAINT IF EXISTS book_copies_added_by_fkey')
    op.create_foreign_key(
        'fk_book_copies_added_by', 'book_copies', 'users', ['added_by'], ['id']
    )
    op.add_column('book_copies', sa.Column('edited_by', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_book_copies_edited_by', 'book_copies', 'users', ['edited_by'], ['id']
    )


def downgrade() -> None:
    # book_copies
    op.drop_constraint('fk_book_copies_edited_by', 'book_copies', type_='foreignkey')
    op.drop_column('book_copies', 'edited_by')
    op.drop_constraint('fk_book_copies_added_by', 'book_copies', type_='foreignkey')
    op.execute('ALTER TABLE book_copies RENAME COLUMN added_by TO user_id')
    op.create_foreign_key(
        'book_copies_user_id_fkey', 'book_copies', 'users', ['user_id'], ['id']
    )

    # books
    op.drop_constraint('fk_books_edited_by', 'books', type_='foreignkey')
    op.drop_column('books', 'edited_by')
    op.drop_constraint('fk_books_added_by', 'books', type_='foreignkey')
    op.execute('ALTER TABLE books RENAME COLUMN added_by TO user_id')
    op.create_foreign_key(
        'books_user_id_fkey', 'books', 'users', ['user_id'], ['id']
    )

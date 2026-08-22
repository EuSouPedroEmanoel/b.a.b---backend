"""add book_copies table and nullable description

Revision ID: 69c19fa0d8cf
Revises: c7277a051ca2
Create Date: 2026-08-22 16:49:24.209477

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '69c19fa0d8cf'
down_revision: Union[str, Sequence[str], None] = 'c7277a051ca2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tipos já criados por migrações anteriores (tabela 'books');
# não devem ser recriados nem removidos aqui.
books_states = postgresql.ENUM(
    'available',
    'borrowed',
    'reserved',
    'lost',
    'archived',
    name='booksstates',
    create_type=False,
)
book_condition = postgresql.ENUM(
    'new', 'good', 'fair', 'poor', 'bad',
    name='bookcondition',
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    # Tipo novo introduzido por esta migração; o guard evita erro
    # caso ele já exista em algum ambiente.
    op.execute(
        """DO $$
        BEGIN
            CREATE TYPE bookcondition AS ENUM
                ('new', 'good', 'fair', 'poor', 'bad');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END
        $$;"""
    )
    op.create_table('book_copies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('internal_code', sa.String(), nullable=False),
    sa.Column('state', books_states, nullable=False),
    sa.Column('condition', book_condition, nullable=False),
    sa.Column('book_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('acquisition_date', sa.Date(), nullable=True),
    sa.Column('notes', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['book_id'], ['books.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('internal_code')
    )
    op.alter_column('books', 'description',
               existing_type=sa.VARCHAR(),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('books', 'description',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.drop_table('book_copies')
    op.execute('DROP TYPE bookcondition')

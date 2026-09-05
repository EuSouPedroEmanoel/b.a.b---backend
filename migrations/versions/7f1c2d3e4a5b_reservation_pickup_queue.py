"""add reservation pickup queue state

Revision ID: 7f1c2d3e4a5b
Revises: e32e54fd7af7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7f1c2d3e4a5b'
down_revision: Union[str, Sequence[str], None] = 'e32e54fd7af7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE reservationstatus ADD VALUE IF NOT EXISTS 'ready'")
        op.execute("ALTER TYPE reservationstatus ADD VALUE IF NOT EXISTS 'expired'")
    op.add_column('reservations', sa.Column('copy_id', sa.Integer(), nullable=True))
    op.add_column('reservations', sa.Column('ready_at', sa.DateTime(), nullable=True))
    op.add_column('reservations', sa.Column('pickup_expires_at', sa.DateTime(), nullable=True))
    op.create_foreign_key(
        'fk_reservations_copy_id_book_copies', 'reservations', 'book_copies',
        ['copy_id'], ['id'],
    )
    # Older versions marked a reservation fulfilled when a copy was returned.
    # Pair those records with reserved copies deterministically so they retain
    # their intended "ready for pickup" meaning.
    op.execute("""
        WITH ranked_reservations AS (
          SELECT id, book_id, school_id,
                 row_number() OVER (PARTITION BY book_id, school_id ORDER BY created_at, id) AS rn
          FROM reservations WHERE status = 'fulfilled'
        ), ranked_copies AS (
          SELECT id, book_id, school_id,
                 row_number() OVER (PARTITION BY book_id, school_id ORDER BY id) AS rn
          FROM book_copies WHERE state = 'reserved'
        )
        UPDATE reservations r
        SET status = 'ready', copy_id = c.id, ready_at = r.updated_at
        FROM ranked_reservations rr
        JOIN ranked_copies c ON c.book_id = rr.book_id
          AND c.school_id = rr.school_id AND c.rn = rr.rn
        WHERE r.id = rr.id
    """)
    op.create_index(
        'uq_reservations_ready_copy', 'reservations', ['copy_id'], unique=True,
        postgresql_where=sa.text("status = 'ready'"),
    )


def downgrade() -> None:
    op.drop_index('uq_reservations_ready_copy', table_name='reservations')
    op.drop_constraint('fk_reservations_copy_id_book_copies', 'reservations', type_='foreignkey')
    op.drop_column('reservations', 'pickup_expires_at')
    op.drop_column('reservations', 'ready_at')
    op.drop_column('reservations', 'copy_id')

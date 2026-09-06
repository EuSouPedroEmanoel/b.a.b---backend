"""enforce one active reservation per user, book, and school

Revision ID: 8a2b3c4d5e6f
Revises: 7f1c2d3e4a5b
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '8a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = '7f1c2d3e4a5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX_NAME = 'uq_reservations_active_user_book_school'
_ACTIVE_STATUSES = "status IN ('active', 'ready')"


def upgrade() -> None:
    # Do not silently discard or merge reservations that violate the new
    # invariant.  The migration must stop and identify the conflicting rows
    # so an operator can resolve them deliberately before retrying it.
    op.execute(
        sa.text(
            """
            DO $$
            DECLARE duplicate_group RECORD;
            BEGIN
                SELECT user_id, book_id, school_id,
                       array_agg(id ORDER BY id) AS reservation_ids
                INTO duplicate_group
                FROM reservations
                WHERE status IN ('active', 'ready')
                GROUP BY user_id, book_id, school_id
                HAVING COUNT(*) > 1
                LIMIT 1;

                IF FOUND THEN
                    RAISE EXCEPTION
                        'Cannot create %: conflicting active reservations '
                        '(user_id=%, book_id=%, school_id=%, '
                        'reservation_ids=%)',
                        'uq_reservations_active_user_book_school',
                        duplicate_group.user_id,
                        duplicate_group.book_id,
                        duplicate_group.school_id,
                        duplicate_group.reservation_ids;
                END IF;
            END $$;
            """
        )
    )
    op.create_index(
        _INDEX_NAME,
        'reservations',
        ['user_id', 'book_id', 'school_id'],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_STATUSES),
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name='reservations')

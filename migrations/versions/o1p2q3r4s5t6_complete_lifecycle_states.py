"""Complete lifecycle state storage and remove persisted overdue loans."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'o1p2q3r4s5t6'
down_revision: Union[str, Sequence[str], None] = 'n0p1q2r3s4t5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user_situation_audit',
        sa.Column(
            'previous_account_status',
            sa.String(length=40),
            nullable=True,
            server_default=sa.text("'active'"),
        ),
    )
    op.add_column(
        'user_situation_audit',
        sa.Column(
            'new_account_status',
            sa.String(length=40),
            nullable=True,
            server_default=sa.text("'active'"),
        ),
    )
    op.execute(
        """
        UPDATE user_situation_audit
        SET previous_account_status = CASE
            WHEN previous_active THEN 'active' ELSE 'disabled' END,
            new_account_status = CASE
            WHEN new_active THEN 'active' ELSE 'disabled' END
        """
    )
    op.alter_column(
        'user_situation_audit',
        'previous_account_status',
        nullable=False,
        server_default=None,
    )
    op.alter_column(
        'user_situation_audit',
        'new_account_status',
        nullable=False,
        server_default=None,
    )

    op.add_column(
        'authors',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'genres',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column('authors', 'is_active', server_default=None)
    op.alter_column('genres', 'is_active', server_default=None)

    op.execute("UPDATE loans SET status = 'active' WHERE status = 'overdue'")
    op.execute('ALTER TYPE loanstatus RENAME TO loanstatus_old')
    op.execute("CREATE TYPE loanstatus AS ENUM ('active', 'returned')")
    op.execute(
        """
        ALTER TABLE loans
        ALTER COLUMN status TYPE loanstatus
        USING status::text::loanstatus
        """
    )
    op.execute('DROP TYPE loanstatus_old')


def downgrade() -> None:
    op.execute("CREATE TYPE loanstatus_old AS ENUM ('active', 'returned', 'overdue')")
    op.execute(
        """
        ALTER TABLE loans
        ALTER COLUMN status TYPE loanstatus_old
        USING status::text::loanstatus_old
        """
    )
    op.execute('DROP TYPE loanstatus')
    op.execute('ALTER TYPE loanstatus_old RENAME TO loanstatus')

    op.drop_column('genres', 'is_active')
    op.drop_column('authors', 'is_active')
    op.drop_column('user_situation_audit', 'new_account_status')
    op.drop_column('user_situation_audit', 'previous_account_status')

"""Add school identifiers, privacy contacts, due dates and retention fields."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'u7v8w9x0y1z2'
down_revision: Union[str, Sequence[str], None] = 't6u7v8w9x0y1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('loans_user_id_fkey', 'loans', type_='foreignkey')
    op.drop_constraint(
        'privacy_requests_user_id_fkey', 'privacy_requests', type_='foreignkey'
    )
    op.add_column(
        'users', sa.Column('school_identifier', sa.String(120), nullable=True)
    )
    op.execute(
        sa.text(
            'UPDATE users SET school_identifier = username '
            'WHERE school_id IS NOT NULL'
        )
    )
    op.create_unique_constraint(
        'uq_users_school_identifier',
        'users',
        ['school_id', 'school_identifier'],
    )
    op.add_column('users', sa.Column('deactivated_at', sa.DateTime()))
    op.add_column(
        'school_privacy_policies',
        sa.Column('privacy_contact_email', sa.String(320), nullable=True),
    )
    op.add_column(
        'privacy_requests', sa.Column('due_at', sa.DateTime(), nullable=True)
    )
    op.execute(
        sa.text(
            'UPDATE privacy_requests SET due_at = created_at + '
            "INTERVAL '15 days'"
        )
    )
    op.alter_column('privacy_requests', 'due_at', nullable=False)
    op.alter_column('privacy_requests', 'user_id', nullable=True)
    op.alter_column('loans', 'user_id', nullable=True)
    op.create_foreign_key(
        'loans_user_id_fkey', 'loans', 'users', ['user_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_foreign_key(
        'privacy_requests_user_id_fkey', 'privacy_requests', 'users',
        ['user_id'], ['id'], ondelete='SET NULL'
    )


def downgrade() -> None:
    op.drop_constraint('loans_user_id_fkey', 'loans', type_='foreignkey')
    op.drop_constraint(
        'privacy_requests_user_id_fkey', 'privacy_requests', type_='foreignkey'
    )
    op.alter_column('loans', 'user_id', nullable=False)
    op.alter_column('privacy_requests', 'user_id', nullable=False)
    op.drop_column('privacy_requests', 'due_at')
    op.drop_column('school_privacy_policies', 'privacy_contact_email')
    op.drop_column('users', 'deactivated_at')
    op.drop_constraint('uq_users_school_identifier', 'users', type_='unique')
    op.drop_column('users', 'school_identifier')
    op.create_foreign_key(
        'loans_user_id_fkey', 'loans', 'users', ['user_id'], ['id']
    )
    op.create_foreign_key(
        'privacy_requests_user_id_fkey', 'privacy_requests', 'users',
        ['user_id'], ['id']
    )

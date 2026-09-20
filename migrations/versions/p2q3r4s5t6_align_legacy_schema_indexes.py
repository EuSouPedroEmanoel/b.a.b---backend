"""Align historical index names with the SQLAlchemy metadata.

Revision ID: p2q3r4s5t6
Revises: o1p2q3r4s5t6
"""

from typing import Sequence, Union

from alembic import op


revision: str = 'p2q3r4s5t6'
down_revision: Union[str, Sequence[str], None] = 'o1p2q3r4s5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename indexes without touching indexed data or constraints."""
    renames = (
        (
            'ix_activation_attempt_created',
            'ix_account_activation_attempts_created_at',
        ),
        (
            'ix_activation_attempt_origin',
            'ix_account_activation_attempts_origin_hash',
        ),
        (
            'ix_activation_attempt_username',
            'ix_account_activation_attempts_username_hash',
        ),
        (
            'ix_activation_audit_created',
            'ix_account_activation_audit_created_at',
        ),
        (
            'ix_activation_audit_user',
            'ix_account_activation_audit_user_id',
        ),
    )
    for old_name, new_name in renames:
        op.execute(
            f'ALTER INDEX "{old_name}" RENAME TO "{new_name}"'
        )


def downgrade() -> None:
    """Restore the historical names used by the previous migration."""
    renames = (
        (
            'ix_account_activation_audit_user_id',
            'ix_activation_audit_user',
        ),
        (
            'ix_account_activation_audit_created_at',
            'ix_activation_audit_created',
        ),
        (
            'ix_account_activation_attempts_username_hash',
            'ix_activation_attempt_username',
        ),
        (
            'ix_account_activation_attempts_origin_hash',
            'ix_activation_attempt_origin',
        ),
        (
            'ix_account_activation_attempts_created_at',
            'ix_activation_attempt_created',
        ),
    )
    for old_name, new_name in renames:
        op.execute(
            f'ALTER INDEX "{old_name}" RENAME TO "{new_name}"'
        )

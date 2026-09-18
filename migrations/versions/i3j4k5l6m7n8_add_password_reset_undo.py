"""Add reversible password reset records."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'i3j4k5l6m7n8'
down_revision: Union[str, Sequence[str], None] = 'h2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'password_reset_undos',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column('previous_password_hash', sa.LargeBinary(), nullable=True),
        sa.Column('previous_account_status', sa.String(length=40), nullable=False),
        sa.Column('previous_activated_at', sa.DateTime(), nullable=True),
        sa.Column('previous_auth_version', sa.Integer(), nullable=False),
        sa.Column('previous_invitation_id', sa.Integer(), nullable=True),
        sa.Column('reset_invitation_id', sa.Integer(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('undone_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.ForeignKeyConstraint(['previous_invitation_id'], ['account_activation_tokens.id']),
        sa.ForeignKeyConstraint(['reset_invitation_id'], ['account_activation_tokens.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_password_reset_undos_user_id',
        'password_reset_undos',
        ['user_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_password_reset_undos_user_id', table_name='password_reset_undos')
    op.drop_table('password_reset_undos')

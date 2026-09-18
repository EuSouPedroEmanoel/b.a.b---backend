"""Add secure first-access account activation."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'h2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'g1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

account_status = sa.Enum(
    'pending_activation', 'active', 'disabled', name='accountstatus'
)


def upgrade() -> None:
    account_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'users',
        sa.Column(
            'account_status',
            account_status,
            nullable=False,
            server_default='active',
        ),
    )
    op.add_column('users', sa.Column('activated_at', sa.DateTime(), nullable=True))
    op.add_column(
        'users',
        sa.Column('auth_version', sa.Integer(), nullable=False, server_default='0'),
    )
    op.execute(
        "UPDATE users SET account_status = CASE "
        "WHEN is_active THEN 'active'::accountstatus "
        "ELSE 'disabled'::accountstatus END, "
        'activated_at = CASE WHEN is_active THEN created_at ELSE NULL END'
    )
    op.alter_column('users', 'account_status', server_default=None)
    op.alter_column('users', 'auth_version', server_default=None)

    op.create_table(
        'account_activation_tokens',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code_hash', sa.LargeBinary(length=32), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_account_activation_tokens_user_id',
        'account_activation_tokens',
        ['user_id'],
    )
    op.create_table(
        'account_activation_attempts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username_hash', sa.LargeBinary(length=32), nullable=False),
        sa.Column('origin_hash', sa.LargeBinary(length=32), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('event', sa.String(length=40), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_activation_attempt_created', 'account_activation_attempts', ['created_at'])
    op.create_index('ix_activation_attempt_origin', 'account_activation_attempts', ['origin_hash'])
    op.create_index('ix_activation_attempt_username', 'account_activation_attempts', ['username_hash'])
    op.create_table(
        'account_activation_audit',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event', sa.String(length=40), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('origin_hash', sa.LargeBinary(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_activation_audit_created', 'account_activation_audit', ['created_at'])
    op.create_index('ix_activation_audit_user', 'account_activation_audit', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_activation_audit_user', table_name='account_activation_audit')
    op.drop_index('ix_activation_audit_created', table_name='account_activation_audit')
    op.drop_table('account_activation_audit')
    op.drop_index('ix_activation_attempt_username', table_name='account_activation_attempts')
    op.drop_index('ix_activation_attempt_origin', table_name='account_activation_attempts')
    op.drop_index('ix_activation_attempt_created', table_name='account_activation_attempts')
    op.drop_table('account_activation_attempts')
    op.drop_index('ix_account_activation_tokens_user_id', table_name='account_activation_tokens')
    op.drop_table('account_activation_tokens')
    op.drop_column('users', 'auth_version')
    op.drop_column('users', 'activated_at')
    op.drop_column('users', 'account_status')
    account_status.drop(op.get_bind(), checkfirst=True)

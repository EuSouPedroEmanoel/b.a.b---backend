"""Add privacy requests and school processing policies."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 's5t6u7v8w9x0'
down_revision: Union[str, Sequence[str], None] = 'r4s5t6u7v8w9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    privacy_mode = sa.Enum(
        'automatic_anonymization',
        'administrative_review',
        name='privacyprocessingmode',
    )
    request_type = sa.Enum(
        'access',
        'information',
        'correction',
        'portability',
        'anonymization',
        'blocking',
        'erasure',
        'consent_revocation',
        name='privacyrequesttype',
    )
    request_status = sa.Enum(
        'pending',
        'in_review',
        'fulfilled',
        'partially_fulfilled',
        'denied',
        'cancelled',
        name='privacyrequeststatus',
    )
    op.create_table(
        'school_privacy_policies',
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column(
            'processing_mode',
            privacy_mode,
            nullable=False,
            server_default='automatic_anonymization',
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['school_id'], ['schools.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('school_id'),
    )
    op.create_table(
        'privacy_requests',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('request_type', request_type, nullable=False),
        sa.Column(
            'status', request_status, nullable=False, server_default='pending'
        ),
        sa.Column('description', sa.String(length=1000), nullable=True),
        sa.Column('resolution', sa.String(length=1000), nullable=True),
        sa.Column('decided_by', sa.Integer(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(
            ['school_id'], ['schools.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['decided_by'], ['users.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_privacy_requests_user_id', 'privacy_requests', ['user_id']
    )
    op.create_index(
        'ix_privacy_requests_school_id', 'privacy_requests', ['school_id']
    )
    op.create_index(
        'ix_privacy_requests_status', 'privacy_requests', ['status']
    )


def downgrade() -> None:
    op.drop_index('ix_privacy_requests_status', table_name='privacy_requests')
    op.drop_index(
        'ix_privacy_requests_school_id', table_name='privacy_requests'
    )
    op.drop_index('ix_privacy_requests_user_id', table_name='privacy_requests')
    op.drop_table('privacy_requests')
    op.drop_table('school_privacy_policies')
    sa.Enum(name='privacyrequeststatus').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='privacyrequesttype').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='privacyprocessingmode').drop(op.get_bind(), checkfirst=True)

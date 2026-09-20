"""Add immutable lifecycle audit records for copies and users."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'n0p1q2r3s4t5'
down_revision: Union[str, Sequence[str], None] = 'm9n0p1q2r3s4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'book_copy_situation_audit',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('copy_id', sa.Integer(), nullable=False),
        sa.Column('previous_state', sa.String(20), nullable=False),
        sa.Column('new_state', sa.String(20), nullable=False),
        sa.Column('justification', sa.String(1000), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.ForeignKeyConstraint(['copy_id'], ['book_copies.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_book_copy_situation_audit_copy_id',
        'book_copy_situation_audit',
        ['copy_id'],
    )
    op.create_index(
        'ix_book_copy_situation_audit_created_at',
        'book_copy_situation_audit',
        ['created_at'],
    )
    op.create_table(
        'user_situation_audit',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('previous_active', sa.Boolean(), nullable=False),
        sa.Column('new_active', sa.Boolean(), nullable=False),
        sa.Column('justification', sa.String(1000), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_user_situation_audit_user_id', 'user_situation_audit', ['user_id']
    )
    op.create_index(
        'ix_user_situation_audit_created_at',
        'user_situation_audit',
        ['created_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_user_situation_audit_created_at', table_name='user_situation_audit'
    )
    op.drop_index(
        'ix_user_situation_audit_user_id', table_name='user_situation_audit'
    )
    op.drop_table('user_situation_audit')
    op.drop_index(
        'ix_book_copy_situation_audit_created_at',
        table_name='book_copy_situation_audit',
    )
    op.drop_index(
        'ix_book_copy_situation_audit_copy_id',
        table_name='book_copy_situation_audit',
    )
    op.drop_table('book_copy_situation_audit')

"""add school circulation policies

Revision ID: c8d9e0f1a2b3
Revises: 8a2b3c4d5e6f
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c8d9e0f1a2b3'
down_revision: Union[str, Sequence[str], None] = '8a2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'circulation_policies',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column(
            'reader_role',
            postgresql.ENUM(
                'super_admin', 'school_admin', 'librarian', 'teacher', 'student',
                name='userrole',
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column('max_active_loans', sa.Integer(), nullable=False),
        sa.Column('loan_duration_days', sa.Integer(), nullable=False),
        sa.Column('max_renewals', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('can_reserve', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('max_active_reservations', sa.Integer(), nullable=False),
        sa.Column('block_new_loans_when_overdue', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('post_overdue_suspension_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("reader_role IN ('student', 'teacher')", name='ck_circulation_policy_reader_role'),
        sa.CheckConstraint('max_active_loans >= 0', name='ck_circulation_policy_max_active_loans'),
        sa.CheckConstraint('loan_duration_days >= 1', name='ck_circulation_policy_loan_duration_days'),
        sa.CheckConstraint('max_renewals >= 0', name='ck_circulation_policy_max_renewals'),
        sa.CheckConstraint('max_active_reservations >= 0', name='ck_circulation_policy_max_active_reservations'),
        sa.CheckConstraint('post_overdue_suspension_days >= 0', name='ck_circulation_policy_post_overdue_suspension_days'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('school_id', 'reader_role', name='uq_circulation_policy_school_role'),
    )


def downgrade() -> None:
    op.drop_table('circulation_policies')

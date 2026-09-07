"""add school calendar and delegated administrative capabilities

Revision ID: d7e8f9a0b1c2
Revises: c8d9e0f1a2b3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'circulation_policies',
        sa.Column(
            'count_only_business_days',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        'school_non_working_days',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('school_id', 'date', name='uq_school_non_working_day'),
    )
    op.create_table(
        'user_administrative_capabilities',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('capability', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "capability IN ('manage_library_calendar', 'manage_circulation_rules')",
            name='ck_user_administrative_capability_value',
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'capability', name='uq_user_administrative_capability'),
    )


def downgrade() -> None:
    op.drop_table('user_administrative_capabilities')
    op.drop_table('school_non_working_days')
    op.drop_column('circulation_policies', 'count_only_business_days')

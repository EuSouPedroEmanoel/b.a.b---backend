"""add configurable progressive overdue penalty fields

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('circulation_policies', sa.Column(
        'apply_overdue_due_date_reduction', sa.Boolean(), nullable=False,
        server_default=sa.true(),
    ))
    op.add_column('circulation_policies', sa.Column(
        'overdue_due_date_reduction_days', sa.Integer(), nullable=False,
        server_default='1',
    ))
    op.add_column('circulation_policies', sa.Column(
        'max_overdue_reductions', sa.Integer(), nullable=False,
        server_default='14',
    ))
    op.add_column('circulation_policies', sa.Column(
        'minimum_loan_days_after_penalties', sa.Integer(), nullable=False,
        server_default='1',
    ))
    op.add_column('circulation_policies', sa.Column(
        'overdue_recovery_mode', sa.String(length=32), nullable=False,
        server_default='on_time_returns',
    ))
    op.add_column('circulation_policies', sa.Column(
        'overdue_recovery_on_time_returns', sa.Integer(), nullable=True,
        server_default='3',
    ))
    op.add_column('circulation_policies', sa.Column(
        'overdue_recovery_days', sa.Integer(), nullable=True,
    ))
    op.create_check_constraint(
        'ck_circulation_policy_overdue_reduction_days',
        'circulation_policies',
        'overdue_due_date_reduction_days >= 0',
    )
    op.create_check_constraint(
        'ck_circulation_policy_max_overdue_reductions',
        'circulation_policies',
        'max_overdue_reductions >= 0',
    )
    op.create_check_constraint(
        'ck_circulation_policy_minimum_penalty_days',
        'circulation_policies',
        'minimum_loan_days_after_penalties >= 1',
    )
    op.create_check_constraint(
        'ck_circulation_policy_recovery_mode',
        'circulation_policies',
        "overdue_recovery_mode IN ('on_time_returns', 'elapsed_days')",
    )


def downgrade() -> None:
    for name in (
        'ck_circulation_policy_recovery_mode',
        'ck_circulation_policy_minimum_penalty_days',
        'ck_circulation_policy_max_overdue_reductions',
        'ck_circulation_policy_overdue_reduction_days',
    ):
        op.drop_constraint(name, 'circulation_policies', type_='check')
    for column in (
        'overdue_recovery_days', 'overdue_recovery_on_time_returns',
        'overdue_recovery_mode', 'minimum_loan_days_after_penalties',
        'max_overdue_reductions', 'overdue_due_date_reduction_days',
        'apply_overdue_due_date_reduction',
    ):
        op.drop_column('circulation_policies', column)

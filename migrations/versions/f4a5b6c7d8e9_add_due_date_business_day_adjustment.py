"""add due date adjustment option

Revision ID: f4a5b6c7d8e9
Revises: e1f2a3b4c5d6
"""
from alembic import op
import sqlalchemy as sa

revision = 'f4a5b6c7d8e9'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('circulation_policies', sa.Column(
        'move_due_date_to_next_business_day', sa.Boolean(), nullable=False,
        server_default=sa.false(),
    ))


def downgrade() -> None:
    op.drop_column('circulation_policies', 'move_due_date_to_next_business_day')

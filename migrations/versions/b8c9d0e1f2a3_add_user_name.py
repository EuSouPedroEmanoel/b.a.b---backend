"""add display name to users

Revision ID: b8c9d0e1f2a3
Revises: a6b7c8d9e0f1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('name', sa.String(120), nullable=True))
    op.execute(sa.text("UPDATE users SET name = username WHERE name IS NULL"))
    op.alter_column('users', 'name', nullable=False)


def downgrade() -> None:
    op.drop_column('users', 'name')

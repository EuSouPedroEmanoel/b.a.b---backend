"""add student fields to users (cpf, birthdate, turma)

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-08-28

Add cpf (unique global), birthdate and turma to users for student accounts.
All are nullable so existing staff/super_admin users are unaffected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('cpf', sa.String(), nullable=True))
    op.add_column('users', sa.Column('birthdate', sa.Date(), nullable=True))
    op.add_column('users', sa.Column('turma', sa.String(), nullable=True))
    op.create_unique_constraint(None, 'users', ['cpf'])


def downgrade() -> None:
    op.drop_constraint(None, 'users', type_='unique')
    op.drop_column('users', 'turma')
    op.drop_column('users', 'birthdate')
    op.drop_column('users', 'cpf')

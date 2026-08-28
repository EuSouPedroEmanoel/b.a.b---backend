"""replace turma with turma_numero + turma_letra

Revision ID: a3f9d2c1b4e7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-28

Turmas são compostas de número + letra (ex.: "7A", "8B"). Remove a string
única `turma` e adiciona duas colunas separadas.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a3f9d2c1b4e7'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('turma_numero', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('turma_letra', sa.String(length=1), nullable=True))
    op.drop_column('users', 'turma')


def downgrade() -> None:
    op.add_column('users', sa.Column('turma', sa.String(), nullable=True))
    op.drop_column('users', 'turma_letra')
    op.drop_column('users', 'turma_numero')

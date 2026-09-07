"""restore the CPF collision guard column for databases with partial migration"""
from alembic import op
import sqlalchemy as sa

revision = 'a6b7c8d9e0f1'
down_revision = 'f7a8b9c0d1e2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {item['name'] for item in inspector.get_columns('users')}
    if 'cpf_collision_guard' in columns:
        return
    op.add_column(
        'users', sa.Column('cpf_collision_guard', sa.LargeBinary(32), nullable=True)
    )
    op.execute(sa.text(
        'UPDATE users SET cpf_collision_guard = cpf_lookup_hash '
        'WHERE cpf_lookup_hash IS NOT NULL'
    ))
    op.create_unique_constraint(
        'uq_users_cpf_lookup_collision_guard',
        'users', ['cpf_lookup_hash', 'cpf_collision_guard'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'uq_users_cpf_lookup_collision_guard', 'users', type_='unique'
    )
    op.drop_column('users', 'cpf_collision_guard')

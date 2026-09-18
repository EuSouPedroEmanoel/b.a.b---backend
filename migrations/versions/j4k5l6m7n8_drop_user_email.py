"""Remove the email attribute from users."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'j4k5l6m7n8'
down_revision: Union[str, Sequence[str], None] = 'i3j4k5l6m7n8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column['name'] for column in inspector.get_columns('users')}
    if 'email' not in columns:
        return
    constraint = next(
        (
            item['name']
            for item in inspector.get_unique_constraints('users')
            if item.get('columns') == ['email']
        ),
        None,
    )
    if constraint:
        op.drop_constraint(constraint, 'users', type_='unique')
    op.drop_column('users', 'email')


def downgrade() -> None:
    op.add_column('users', sa.Column('email', sa.String(), nullable=True))
    op.create_unique_constraint('uq_users_email', 'users', ['email'])

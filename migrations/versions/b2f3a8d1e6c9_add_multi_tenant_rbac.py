"""add multi-tenant rbac

Revision ID: b2f3a8d1e6c9
Revises: 69c19fa0d8cf
Create Date: 2026-08-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2f3a8d1e6c9'
down_revision: Union[str, Sequence[str], None] = '69c19fa0d8cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

user_role = postgresql.ENUM(
    'super_admin',
    'school_admin',
    'librarian',
    'teacher',
    'student',
    name='userrole',
    create_type=False,
)


def upgrade() -> None:
    op.execute(
        """DO $$
        BEGIN
            CREATE TYPE userrole AS ENUM
                ('super_admin','school_admin','librarian','teacher','student');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END
        $$;"""
    )

    op.create_table(
        'schools',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )

    op.add_column(
        'users',
        sa.Column(
            'role',
            user_role,
            nullable=False,
            server_default='librarian',
        ),
    )
    op.add_column(
        'users',
        sa.Column('school_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_users_school_id', 'users', 'schools', ['school_id'], ['id']
    )
    op.create_check_constraint(
        'ck_user_school_required',
        'users',
        "(role = 'super_admin') OR (school_id IS NOT NULL)",
    )

    op.add_column(
        'book_copies',
        sa.Column('school_id', sa.Integer(), nullable=False),
    )
    op.create_foreign_key(
        'fk_book_copies_school_id',
        'book_copies',
        'schools',
        ['school_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_book_copies_school_id', 'book_copies', type_='foreignkey')
    op.drop_column('book_copies', 'school_id')
    op.drop_constraint('ck_user_school_required', 'users', type_='check')
    op.drop_constraint('fk_users_school_id', 'users', type_='foreignkey')
    op.drop_column('users', 'school_id')
    op.drop_column('users', 'role')
    op.drop_table('schools')
    op.execute('DROP TYPE userrole')

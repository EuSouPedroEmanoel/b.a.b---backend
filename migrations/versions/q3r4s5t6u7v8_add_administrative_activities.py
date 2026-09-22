"""Add the append-only administrative activity stream."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'q3r4s5t6u7v8'
down_revision: Union[str, Sequence[str], None] = 'p2q3r4s5t6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'administrative_activities',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('occurred_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_display_name', sa.String(length=120), nullable=False),
        sa.Column('actor_role', sa.String(length=40), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('operation', sa.String(length=40), nullable=False),
        sa.Column('entity_type', sa.String(length=40), nullable=False),
        sa.Column('entity_id', sa.String(length=80), nullable=True),
        sa.Column('summary', sa.String(length=240), nullable=False),
        sa.Column('changed_fields', sa.JSON(), nullable=True),
        sa.Column('justification', sa.String(length=1000), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_administrative_activities_occurred_at', 'administrative_activities', ['occurred_at'])
    op.create_index('ix_administrative_activities_school_occurred', 'administrative_activities', ['school_id', 'occurred_at'])
    op.create_index('ix_administrative_activities_actor_occurred', 'administrative_activities', ['actor_id', 'occurred_at'])
    op.create_index('ix_administrative_activities_entity', 'administrative_activities', ['entity_type', 'entity_id'])


def downgrade() -> None:
    op.drop_index('ix_administrative_activities_entity', table_name='administrative_activities')
    op.drop_index('ix_administrative_activities_actor_occurred', table_name='administrative_activities')
    op.drop_index('ix_administrative_activities_school_occurred', table_name='administrative_activities')
    op.drop_index('ix_administrative_activities_occurred_at', table_name='administrative_activities')
    op.drop_table('administrative_activities')

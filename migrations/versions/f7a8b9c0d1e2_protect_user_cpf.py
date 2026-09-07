"""Replace plaintext user CPF with an HMAC lookup index.

Revision ID: f7a8b9c0d1e2
Revises: f4a5b6c7d8e9
"""

import hashlib
import hmac
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from src.settings import Settings
from src.utils.cpf import normalize_cpf, validate_cpf

revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, Sequence[str], None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _digest(cpf: str, secret: bytes) -> bytes:
    return hmac.new(secret, cpf.encode('ascii'), hashlib.sha256).digest()


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('cpf_lookup_hash', sa.LargeBinary(32), nullable=True),
    )
    op.add_column(
        'users',
        sa.Column('cpf_collision_guard', sa.LargeBinary(32), nullable=True),
    )
    op.add_column('users', sa.Column('cpf_last2', sa.String(2), nullable=True))

    bind = op.get_bind()
    secret = Settings().CPF_HMAC_SECRET.get_secret_value().encode('utf-8')
    rows = bind.execute(
        sa.text('SELECT id, cpf FROM users WHERE cpf IS NOT NULL')
    ).mappings().all()

    migrated: dict[tuple[bytes, bytes], tuple[int, str]] = {}
    for row in rows:
        normalized = normalize_cpf(row['cpf'])
        if not normalized or not validate_cpf(normalized):
            raise RuntimeError(
                f'CPF migration failed: invalid CPF for user id={row["id"]}'
            )
        digest = _digest(normalized, secret)
        guard = hmac.new(
            secret,
            b'cpf-collision-guard:' + normalized.encode('ascii'),
            hashlib.sha256,
        ).digest()
        pair = (digest, guard)
        previous = migrated.get(pair)
        if previous is not None:
            raise RuntimeError(
                'CPF migration failed: duplicate normalized CPF for '
                f'user ids {previous[0]} and {row["id"]}'
            )
        migrated[pair] = (row['id'], normalized[-2:])
        bind.execute(
            sa.text(
                'UPDATE users SET cpf_lookup_hash=:lookup_hash, '
                'cpf_collision_guard=:collision_guard, cpf_last2=:last2 '
                'WHERE id=:id'
            ),
            {
                'lookup_hash': digest,
                'collision_guard': guard,
                'last2': normalized[-2:],
                'id': row['id'],
            },
        )

    count = bind.execute(
        sa.text(
            'SELECT count(*) FROM users '
            'WHERE cpf IS NOT NULL AND '
            '(cpf_lookup_hash IS NULL OR cpf_collision_guard IS NULL '
            'OR cpf_last2 IS NULL)'
        )
    ).scalar_one()
    if count:
        raise RuntimeError(
            f'CPF migration failed: {count} user records were not migrated'
        )

    op.create_unique_constraint(
        'uq_users_cpf_lookup_collision_guard',
        'users',
        ['cpf_lookup_hash', 'cpf_collision_guard'],
    )
    op.create_check_constraint(
        'ck_user_cpf_fields_consistent',
        'users',
        '(cpf_lookup_hash IS NULL) = (cpf_collision_guard IS NULL) '
        'AND (cpf_lookup_hash IS NULL) = (cpf_last2 IS NULL)',
    )

    inspector = sa.inspect(bind)
    legacy_constraint = next(
        (
            item['name']
            for item in inspector.get_unique_constraints('users')
            if item.get('columns') == ['cpf']
        ),
        None,
    )
    if legacy_constraint:
        op.drop_constraint(legacy_constraint, 'users', type_='unique')
    op.drop_column('users', 'cpf')


def downgrade() -> None:
    raise RuntimeError(
        'CPF protection migration cannot be downgraded: plaintext CPF was '
        'intentionally removed.'
    )

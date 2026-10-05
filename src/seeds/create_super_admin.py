import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.models import User, UserRole
from src.security import get_password_hash
from src.settings import Settings
from src.utils.cpf import cpf_storage_values

settings = Settings()


async def seed_super_admin():
    if not settings.SUPER_ADMIN_USERNAME or not settings.SUPER_ADMIN_PASSWORD:
        raise RuntimeError(
            'SUPER_ADMIN_USERNAME and SUPER_ADMIN_PASSWORD are required '
            'when SEED_SUPER_ADMIN=1'
        )
    engine = create_async_engine(settings.DATABASE_URL)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        existing = await session.scalar(
            select(User).where(User.username == settings.SUPER_ADMIN_USERNAME)
        )
        if existing:
            if existing.cpf_lookup_hash is None:
                lookup_hash, collision_guard, last2 = cpf_storage_values(
                    '12345678909'
                )
                existing.cpf_lookup_hash = lookup_hash
                existing.cpf_collision_guard = collision_guard
                existing.cpf_last2 = last2
                await session.commit()
            print(f'SUPER_ADMIN {existing.username} already exists')
            await engine.dispose()
            return existing

        user = User(
            username=settings.SUPER_ADMIN_USERNAME,
            name=settings.SUPER_ADMIN_USERNAME,
            cpf_lookup_hash=cpf_storage_values('12345678909')[0],
            cpf_collision_guard=cpf_storage_values('12345678909')[1],
            cpf_last2=cpf_storage_values('12345678909')[2],
            password=get_password_hash(settings.SUPER_ADMIN_PASSWORD),
            role=UserRole.SUPER_ADMIN,
            school_id=None,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f'SUPER_ADMIN {user.username} created (id={user.id})')
        await engine.dispose()
        return user


if __name__ == '__main__':  # pragma: no cover
    asyncio.run(seed_super_admin())  # pragma: no cover

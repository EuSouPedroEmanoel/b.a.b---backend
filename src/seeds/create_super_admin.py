import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.models import User, UserRole
from src.security import get_password_hash
from src.settings import Settings

settings = Settings()


async def seed_super_admin():
    engine = create_async_engine(settings.DATABASE_URL)
    async with AsyncSession(engine, expire_on_commit=False) as session:
        existing = await session.scalar(
            select(User).where(User.username == settings.SUPER_ADMIN_USERNAME)
        )
        if existing:
            print(f'SUPER_ADMIN {existing.username} already exists')
            await engine.dispose()
            return existing

        user = User(
            username=settings.SUPER_ADMIN_USERNAME,
            email=settings.SUPER_ADMIN_EMAIL,
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

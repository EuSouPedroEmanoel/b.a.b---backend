import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from src.database import engine
from src.services.privacy_retention import run_privacy_retention


async def main() -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        metrics = await run_privacy_retention(session)
    print(metrics)


if __name__ == '__main__':
    asyncio.run(main())

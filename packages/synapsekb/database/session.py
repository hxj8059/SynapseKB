from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from synapsekb.config import Settings, get_settings

settings = get_settings()


def create_database_engine(config: Settings) -> AsyncEngine:
    common_options = {
        "pool_pre_ping": True,
    }
    if config.database_pool_mode == "null":
        # Dramatiq executes sync actors in multiple threads and each actor uses
        # asyncio.run(), so event loops are short-lived. Asyncpg connections are
        # bound to the loop that created them and must not be reused by another
        # actor invocation.
        return create_async_engine(
            config.database_url,
            poolclass=NullPool,
            **common_options,
        )
    return create_async_engine(
        config.database_url,
        pool_size=10,
        max_overflow=20,
        pool_recycle=1800,
        **common_options,
    )


engine = create_database_engine(settings)
AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionFactory() as session:
        yield session

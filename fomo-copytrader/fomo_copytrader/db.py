from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .models import Base


def make_engine(url: str) -> AsyncEngine:
    if url.startswith("sqlite"):
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return create_async_engine(url, pool_pre_ping=True)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)

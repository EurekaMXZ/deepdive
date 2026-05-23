from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncConnection as SqlAlchemyAsyncConnection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class AsyncTransactionFactory(Protocol):
    def begin(self):
        ...


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[SqlAlchemyAsyncConnection]:
        async with self._engine.begin() as connection:
            yield connection

    async def dispose(self) -> None:
        await self._engine.dispose()


def create_database(database_url: str) -> Database:
    return Database(create_async_engine(database_url))


def create_database_from_env() -> Database:
    database_url = os.environ["DATABASE_URL"]
    return create_database(database_url)

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import cast

from sqlalchemy.ext.asyncio import AsyncConnection as SqlAlchemyAsyncConnection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from backend.db.connections import AsyncDbConnection


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[AsyncDbConnection]:
        async with self._engine.begin() as connection:
            yield cast(AsyncDbConnection, connection)

    async def dispose(self) -> None:
        await self._engine.dispose()

    def transaction(self) -> AbstractAsyncContextManager[SqlAlchemyAsyncConnection]:
        return self._engine.begin()


def create_database(database_url: str) -> Database:
    return Database(create_async_engine(database_url))


def create_database_from_env() -> Database:
    database_url = os.environ["DATABASE_URL"]
    return create_database(database_url)

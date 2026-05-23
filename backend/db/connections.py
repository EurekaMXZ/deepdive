from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


@asynccontextmanager
async def connection_from(connection_or_database) -> AsyncIterator:
    if hasattr(connection_or_database, "dispose"):
        async with connection_or_database.begin() as connection:
            yield connection
        return
    yield connection_or_database

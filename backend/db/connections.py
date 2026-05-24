from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, Protocol, TypeGuard, cast, runtime_checkable

DbRow = Mapping[str, Any]


class DbMappingResult(Protocol):
    def all(self) -> Sequence[DbRow]: ...

    def first(self) -> DbRow | None: ...


class DbExecuteResult(Protocol):
    rowcount: int

    def mappings(self) -> DbMappingResult: ...


@runtime_checkable
class AsyncDbConnection(Protocol):
    async def execute(self, statement: Any, params: Any = None) -> DbExecuteResult: ...

    async def scalar(self, statement: Any, params: Any = None) -> Any: ...


class AsyncConnectionProvider(Protocol):
    def begin(self) -> AbstractAsyncContextManager[AsyncDbConnection]: ...


@asynccontextmanager
async def connection_from(connection_or_database: ConnectionSource) -> AsyncGenerator[AsyncDbConnection]:
    if _is_connection_like(connection_or_database):
        yield connection_or_database
        return

    provider = cast(AsyncConnectionProvider, connection_or_database)
    async with provider.begin() as connection:
        yield connection


ConnectionSource = AsyncDbConnection | AsyncConnectionProvider


def _is_connection_like(value: object) -> TypeGuard[AsyncDbConnection]:
    return callable(getattr(value, "execute", None))

from __future__ import annotations

import inspect
from collections.abc import Awaitable


async def maybe_await[T](value: T | Awaitable[T]) -> T:
    if inspect.isawaitable(value):
        return await value
    return value

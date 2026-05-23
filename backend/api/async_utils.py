from __future__ import annotations

import inspect


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value

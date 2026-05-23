from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def run_forever(
    once: Callable[[], Awaitable[int]],
    *,
    idle_sleep_seconds: float = 1.0,
    error_backoff_seconds: float = 5.0,
    should_stop: Callable[[], bool] | None = None,
) -> None:
    while should_stop is None or not should_stop():
        try:
            processed = await once()
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(error_backoff_seconds)
            continue

        if processed <= 0:
            await asyncio.sleep(idle_sleep_seconds)

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
import selectors
import sys
from typing import Any


def run_async_worker(coro: Coroutine[Any, Any, Any]) -> Any:
    if sys.platform == "win32":
        return asyncio.run(
            coro,
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    return asyncio.run(coro)

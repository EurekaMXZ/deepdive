from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from backend.workers.asyncio_compat import run_async_worker


class WorkerAsyncioCompatTest(unittest.TestCase):
    def test_run_async_worker_uses_selector_loop_factory_on_windows(self) -> None:
        async def noop() -> None:
            return None

        captured = {}

        def fake_run(coro, *, loop_factory=None):
            captured["loop_factory"] = loop_factory
            coro.close()

        with (
            patch("backend.workers.asyncio_compat.sys.platform", "win32"),
            patch("backend.workers.asyncio_compat.asyncio.run", side_effect=fake_run),
        ):
            run_async_worker(noop())

        self.assertIsNotNone(captured["loop_factory"])
        loop = captured["loop_factory"]()
        try:
            self.assertIsInstance(loop, asyncio.SelectorEventLoop)
        finally:
            loop.close()

    def test_run_async_worker_uses_default_asyncio_run_off_windows(self) -> None:
        async def noop() -> None:
            return None

        captured = {}

        def fake_run(coro, **kwargs):
            captured["kwargs"] = kwargs
            coro.close()

        with (
            patch("backend.workers.asyncio_compat.sys.platform", "linux"),
            patch("backend.workers.asyncio_compat.asyncio.run", side_effect=fake_run),
        ):
            run_async_worker(noop())

        self.assertEqual(captured["kwargs"], {})


if __name__ == "__main__":
    unittest.main()

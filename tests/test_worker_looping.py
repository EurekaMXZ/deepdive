from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.workers.looping import run_forever


class WorkerLoopingTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_forever_repeats_until_stop_condition(self) -> None:
        calls = 0

        async def once() -> int:
            nonlocal calls
            calls += 1
            return 1

        await run_forever(once, should_stop=lambda: calls >= 3, idle_sleep_seconds=0, error_backoff_seconds=0)

        self.assertEqual(calls, 3)

    async def test_run_forever_backs_off_after_error_and_continues(self) -> None:
        calls = 0

        async def once() -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary failure")
            return 1

        with patch("backend.workers.looping.asyncio.sleep") as sleep_mock:
            await run_forever(once, should_stop=lambda: calls >= 2, idle_sleep_seconds=0, error_backoff_seconds=7)

        sleep_mock.assert_awaited_once_with(7)
        self.assertEqual(calls, 2)


if __name__ == "__main__":
    unittest.main()

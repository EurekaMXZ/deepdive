from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api.runtime import ApiRuntimeSettings, load_api_runtime_settings, main


class ApiRuntimeTest(unittest.TestCase):
    def test_api_runtime_settings_load_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "API_HOST=127.0.0.2",
                        "API_PORT=8123",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(env_file)}, clear=True):
                settings = load_api_runtime_settings()

        self.assertEqual(settings, ApiRuntimeSettings(host="127.0.0.2", port=8123))

    def test_api_runtime_uses_windows_safe_async_runner(self) -> None:
        captured = []

        def fake_run_async_worker(coro):
            captured.append(coro)
            coro.close()

        with patch("backend.api.runtime.run_async_worker", side_effect=fake_run_async_worker) as run_async_worker:
            main()

        self.assertEqual(run_async_worker.call_count, 1)
        self.assertEqual(len(captured), 1)


if __name__ == "__main__":
    unittest.main()

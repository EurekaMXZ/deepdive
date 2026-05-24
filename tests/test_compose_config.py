from __future__ import annotations

import re
import unittest
from pathlib import Path

COMPOSE_PATH = Path("docker-compose.yml")


class ComposeConfigTest(unittest.TestCase):
    def test_app_services_database_url_uses_postgres_environment_variables(self) -> None:
        compose = COMPOSE_PATH.read_text(encoding="utf-8")
        urls = re.findall(r"DATABASE_URL:\s+(.+)", compose)

        self.assertGreaterEqual(len(urls), 6)
        for value in urls:
            with self.subTest(database_url=value):
                self.assertIn("${POSTGRES_USER:-deepdive}", value)
                self.assertIn("${POSTGRES_PASSWORD:-deepdive}", value)
                self.assertIn("${POSTGRES_DB:-deepdive}", value)
                self.assertNotIn("deepdive:deepdive@postgres:5432/deepdive", value)


if __name__ == "__main__":
    unittest.main()

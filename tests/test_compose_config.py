from __future__ import annotations

import re
import unittest
from pathlib import Path

COMPOSE_PATH = Path("docker-compose.yml")
DOCKERFILE_PATH = Path("Dockerfile")


class ComposeConfigTest(unittest.TestCase):
    def test_app_profile_runs_analysis_batch_scheduler_worker(self) -> None:
        compose = COMPOSE_PATH.read_text(encoding="utf-8")

        self.assertIn("analysis-batch-scheduler-worker:", compose)
        self.assertIn("container_name: deepdive-analysis-batch-scheduler-worker", compose)
        self.assertIn(
            'command: ["python", "-m", "backend.workers.batch_scheduler_runtime"]',
            compose,
        )
        self.assertIn('profiles: ["app"]', compose)
        self.assertIn('ANALYSIS_BATCH_SCHEDULER_WORKER_RUN_FOREVER: "true"', compose)

    def test_app_services_database_url_uses_postgres_environment_variables(self) -> None:
        compose = COMPOSE_PATH.read_text(encoding="utf-8")
        urls = re.findall(r"DATABASE_URL:\s+(.+)", compose)

        self.assertGreaterEqual(len(urls), 7)
        for value in urls:
            with self.subTest(database_url=value):
                self.assertIn("${POSTGRES_USER:-deepdive}", value)
                self.assertIn("${POSTGRES_PASSWORD:-deepdive}", value)
                self.assertIn("${POSTGRES_DB:-deepdive}", value)
                self.assertNotIn("deepdive:deepdive@postgres:5432/deepdive", value)

    def test_backend_image_includes_runtime_prompt_and_profile_files(self) -> None:
        dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

        self.assertIn("COPY prompts ./prompts", dockerfile)
        self.assertIn("COPY profiles ./profiles", dockerfile)


if __name__ == "__main__":
    unittest.main()

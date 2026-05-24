from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api.app import create_app_from_env, create_postgres_app
from backend.api.services import InMemoryAnalysisService, PostgresAnalysisService
from backend.config import AppConfig, OpenAIConfig
from backend.document import DocumentService


class AppFactoryTest(unittest.TestCase):
    def test_create_app_from_env_uses_in_memory_service_without_database_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_env_file = Path(tmpdir) / "missing.env"
            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(missing_env_file)}, clear=True):
                app = create_app_from_env()

        self.assertIsInstance(app.state.analysis_service, InMemoryAnalysisService)
        self.assertIsInstance(app.state.document_service, DocumentService)
        self.assertTrue(hasattr(app.state, "auth_service"))

    def test_create_app_from_env_uses_postgres_service_when_database_url_exists(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "MINIO_ENDPOINT": "localhost:9000",
            },
            clear=True,
        ):
            app = create_app_from_env()

        self.assertIsInstance(app.state.analysis_service, PostgresAnalysisService)
        self.assertIsInstance(app.state.document_service, DocumentService)
        self.assertTrue(hasattr(app.state, "auth_service"))

    def test_create_app_from_env_loads_database_url_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "DATABASE_URL=postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(env_file)}, clear=True):
                app = create_app_from_env()

        self.assertIsInstance(app.state.analysis_service, PostgresAnalysisService)
        self.assertIsInstance(app.state.document_service, DocumentService)
        self.assertTrue(hasattr(app.state, "auth_service"))

    def test_create_postgres_app_does_not_expose_live_model_stream_state(self) -> None:
        app = create_postgres_app(
            database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
            config=AppConfig(openai=OpenAIConfig(show_reasoning_summary=False)),
        )

        self.assertFalse(hasattr(app.state, "live_stream_hub"))
        self.assertFalse(hasattr(app.state, "live_stream_subscriber"))
        self.assertFalse(hasattr(app.state, "show_model_reasoning_summary"))


if __name__ == "__main__":
    unittest.main()

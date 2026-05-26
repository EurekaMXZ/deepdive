from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from backend.api.app import create_app, create_app_from_env, create_postgres_app
from backend.api.services import InMemoryAnalysisService, PostgresAnalysisService
from backend.document import DocumentService
from fastapi.testclient import TestClient


class AppFactoryTest(unittest.TestCase):
    def test_installs_backend_routes_under_api_prefix(self) -> None:
        client = TestClient(create_app())

        prefixed = client.get("/api/auth/me")
        legacy = client.get("/auth/me")

        self.assertEqual(prefixed.status_code, 401)
        self.assertEqual(legacy.status_code, 404)

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

    def test_create_postgres_app_bootstraps_admin_during_lifespan_startup(self) -> None:
        database = FakeDatabase()
        with (
            patch("backend.api.app.create_database", return_value=database),
            patch("backend.api.app.bootstrap_admin_from_env", new_callable=AsyncMock) as bootstrap,
            TestClient(create_postgres_app(database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive")),
        ):
            pass

        bootstrap.assert_awaited_once_with(database)
        self.assertTrue(database.disposed)


class FakeDatabase:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


if __name__ == "__main__":
    unittest.main()

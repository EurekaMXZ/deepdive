from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.events import EventEnvelope, EventType
from backend.workers.analysis_runtime import (
    AnalysisWorkerSettings,
    build_analysis_command_topics,
    load_analysis_worker_settings,
)
from backend.workers.outbox import WorkerSettings, load_worker_settings
from backend.workers.snapshot_runtime import (
    SnapshotWorkerSettings,
    build_snapshot_command_topics,
    load_snapshot_worker_settings,
)


class WorkerEntrypointTest(unittest.TestCase):
    def test_outbox_worker_settings_load_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
                "OUTBOX_BATCH_SIZE": "25",
            },
            clear=True,
        ):
            settings = load_worker_settings()

        self.assertEqual(
            settings,
            WorkerSettings(
                database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                kafka_bootstrap_servers="localhost:9092",
                batch_size=25,
                run_forever=True,
            ),
        )

    def test_outbox_worker_settings_load_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "DATABASE_URL=postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                        "KAFKA_BOOTSTRAP_SERVERS=localhost:19092",
                        "OUTBOX_BATCH_SIZE=7",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(env_file)}, clear=True):
                settings = load_worker_settings()

        self.assertEqual(
            settings,
            WorkerSettings(
                database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                kafka_bootstrap_servers="localhost:19092",
                batch_size=7,
                run_forever=True,
            ),
        )

    def test_outbox_worker_defaults_to_run_forever_for_runtime_service(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPDIVE_ENV_FILE": "D:/path/that/does/not/exist/.env",
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
            },
            clear=True,
        ):
            settings = load_worker_settings()

        self.assertTrue(settings.run_forever)

    def test_outbox_worker_accepts_compose_run_forever_alias(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
                "OUTBOX_WORKER_RUN_FOREVER": "true",
            },
            clear=True,
        ):
            settings = load_worker_settings()

        self.assertTrue(settings.run_forever)

    def test_outbox_publish_forever_reuses_database_and_producer(self) -> None:
        import backend.workers.outbox as outbox

        database = FakeDatabase()
        producer = FakeProducer()
        captured_once = []

        async def fake_run_forever(once, **kwargs):
            del kwargs
            captured_once.append(once)
            await once()
            await once()

        with (
            patch.object(outbox, "create_database", return_value=database) as create_database,
            patch.object(outbox, "AiokafkaEventProducer", return_value=producer) as create_producer,
            patch.object(outbox, "run_forever", fake_run_forever),
        ):
            asyncio.run(
                outbox.publish_forever(
                    WorkerSettings(
                        database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                        kafka_bootstrap_servers="localhost:9092",
                        batch_size=2,
                    )
                )
            )

        create_database.assert_called_once()
        create_producer.assert_called_once()
        self.assertEqual(producer.starts, 1)
        self.assertEqual(producer.stops, 1)
        self.assertTrue(database.disposed)
        self.assertEqual(database.begin_calls, 2)
        self.assertEqual(len(captured_once), 1)

    def test_analysis_worker_subscribes_to_analysis_commands_topic(self) -> None:
        event = EventEnvelope.new(event_type=EventType.ANALYSIS_REQUESTED)

        self.assertEqual(build_analysis_command_topics(), ("deepdive.analysis.commands",))
        self.assertEqual(event.event_type, EventType.ANALYSIS_REQUESTED)

    def test_analysis_worker_settings_load_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "DATABASE_URL=postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                        "KAFKA_BOOTSTRAP_SERVERS=localhost:19092",
                        "ANALYSIS_WORKER_GROUP=analysis-dotenv",
                        "ANALYSIS_WORKER_MAX_MESSAGES=11",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(env_file)}, clear=True):
                settings = load_analysis_worker_settings()

        self.assertEqual(
            settings,
            AnalysisWorkerSettings(
                database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                kafka_bootstrap_servers="localhost:19092",
                consumer_group="analysis-dotenv",
                max_messages=11,
                run_forever=True,
            ),
        )

    def test_analysis_worker_defaults_to_run_forever_for_runtime_service(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPDIVE_ENV_FILE": "D:/path/that/does/not/exist/.env",
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
            },
            clear=True,
        ):
            settings = load_analysis_worker_settings()

        self.assertTrue(settings.run_forever)

    def test_snapshot_worker_settings_load_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
                "SNAPSHOT_WORKER_GROUP": "snapshot-group",
                "SNAPSHOT_WORKER_MAX_MESSAGES": "5",
                "MINIO_ENDPOINT": "localhost:9000",
                "MINIO_ACCESS_KEY": "deepdive",
                "MINIO_SECRET_KEY": "deepdive-secret",
                "MINIO_BUCKET": "deepdive-objects-custom",
                "MINIO_SECURE": "false",
                "SNAPSHOT_GIT_TIMEOUT_SECONDS": "120",
                "SNAPSHOT_MAX_FILE_BYTES": "1024",
                "SNAPSHOT_MAX_GIT_BUNDLE_BYTES": "4096",
            },
            clear=True,
        ):
            settings = load_snapshot_worker_settings()

        self.assertEqual(
            settings,
            SnapshotWorkerSettings(
                database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                kafka_bootstrap_servers="localhost:9092",
                consumer_group="snapshot-group",
                max_messages=5,
                minio_endpoint="localhost:9000",
                minio_access_key="deepdive",
                minio_secret_key="deepdive-secret",
                minio_bucket="deepdive-objects-custom",
                minio_secure=False,
                git_timeout_seconds=120,
                max_file_bytes=1024,
                max_git_bundle_bytes=4096,
                run_forever=True,
            ),
        )

    def test_snapshot_worker_settings_load_from_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "DATABASE_URL=postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                        "KAFKA_BOOTSTRAP_SERVERS=localhost:19092",
                        "SNAPSHOT_WORKER_GROUP=snapshot-dotenv",
                        "SNAPSHOT_WORKER_MAX_MESSAGES=9",
                        "MINIO_ENDPOINT=localhost:19000",
                        "MINIO_ACCESS_KEY=dotenv-access",
                        "MINIO_SECRET_KEY=dotenv-secret",
                        "MINIO_BUCKET=dotenv-bucket",
                        "MINIO_SECURE=true",
                        "SNAPSHOT_GIT_TIMEOUT_SECONDS=121",
                        "SNAPSHOT_MAX_FILE_BYTES=2048",
                        "SNAPSHOT_MAX_GIT_BUNDLE_BYTES=8192",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPDIVE_ENV_FILE": str(env_file)}, clear=True):
                settings = load_snapshot_worker_settings()

        self.assertEqual(
            settings,
            SnapshotWorkerSettings(
                database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                kafka_bootstrap_servers="localhost:19092",
                consumer_group="snapshot-dotenv",
                max_messages=9,
                minio_endpoint="localhost:19000",
                minio_access_key="dotenv-access",
                minio_secret_key="dotenv-secret",
                minio_bucket="dotenv-bucket",
                minio_secure=True,
                git_timeout_seconds=121,
                max_file_bytes=2048,
                max_git_bundle_bytes=8192,
                run_forever=True,
            ),
        )

    def test_snapshot_worker_defaults_to_run_forever_for_runtime_service(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPDIVE_ENV_FILE": "D:/path/that/does/not/exist/.env",
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
            },
            clear=True,
        ):
            settings = load_snapshot_worker_settings()

        self.assertTrue(settings.run_forever)
        self.assertEqual(settings.minio_bucket, "deepdive-objects")

    def test_snapshot_worker_subscribes_to_snapshot_commands_topic(self) -> None:
        self.assertEqual(build_snapshot_command_topics(), ("deepdive.snapshot.commands",))

    def test_all_worker_modules_import(self) -> None:
        import backend.workers.agent_runtime
        import backend.workers.execution_runtime

        self.assertIsNotNone(backend.workers.agent_runtime)
        self.assertIsNotNone(backend.workers.execution_runtime)


if __name__ == "__main__":
    unittest.main()


class FakeDatabase:
    def __init__(self) -> None:
        self.connection = FakeOutboxConnection()
        self.disposed = False
        self.begin_calls = 0

    def begin(self):
        self.begin_calls += 1
        return FakeTransaction(self.connection)

    async def dispose(self) -> None:
        self.disposed = True


class FakeTransaction:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None


class FakeOutboxConnection:
    def __init__(self) -> None:
        self.executed = []

    async def execute(self, statement, params=None):
        self.executed.append((statement, params or {}))
        return FakeResult([])


class FakeResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeProducer:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    async def start(self):
        self.starts += 1

    async def stop(self):
        self.stops += 1

    async def send_and_wait(self, topic, *, key, value):
        del topic, key, value

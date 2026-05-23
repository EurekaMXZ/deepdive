from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

from backend.events import EventEnvelope, EventType
from backend.events.kafka import ConsumedKafkaMessage
from backend.ids import new_uuid7
from backend.workers.execution_runtime import ExecutionWorkerSettings, build_execution_command_topics, load_execution_worker_settings


class ExecutionWorkerRuntimeTest(unittest.TestCase):
    def test_execution_worker_subscribes_to_execution_commands(self) -> None:
        self.assertEqual(build_execution_command_topics(), ("deepdive.execution.commands",))

    def test_execution_worker_settings_load_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
                "EXECUTION_WORKER_GROUP": "execution-group",
                "EXECUTION_WORKER_MAX_MESSAGES": "4",
                "MINIO_ENDPOINT": "localhost:9000",
                "MINIO_ACCESS_KEY": "deepdive",
                "MINIO_SECRET_KEY": "deepdive-secret",
                "MINIO_BUCKET": "deepdive-objects-custom",
                "MINIO_SECURE": "false",
                "CACHE_ROOT_DIR": "D:/cache/deepdive",
                "EXECUTION_TOOL_HEARTBEAT_INTERVAL_SECONDS": "11",
            },
            clear=True,
        ):
            settings = load_execution_worker_settings()

        self.assertEqual(
            settings,
            ExecutionWorkerSettings(
                database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                kafka_bootstrap_servers="localhost:9092",
                consumer_group="execution-group",
                max_messages=4,
                minio_endpoint="localhost:9000",
                minio_access_key="deepdive",
                minio_secret_key="deepdive-secret",
                minio_bucket="deepdive-objects-custom",
                minio_secure=False,
                cache_root_dir="D:/cache/deepdive",
                run_forever=True,
                tool_heartbeat_interval_seconds=11,
            ),
        )

    def test_execution_worker_defaults_to_run_forever_for_runtime_service(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPDIVE_ENV_FILE": "D:/path/that/does/not/exist/.env",
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
            },
            clear=True,
        ):
            settings = load_execution_worker_settings()

        self.assertTrue(settings.run_forever)
        self.assertEqual(settings.minio_bucket, "deepdive-objects")

    def test_execution_worker_repositories_are_not_bound_to_consumer_transaction(self) -> None:
        import backend.workers.execution_runtime as runtime

        captured_snapshot_targets = []
        captured_tool_targets = []

        class FakeSnapshotRepository:
            def __init__(self, target) -> None:
                captured_snapshot_targets.append(target)

        class FakeToolCallRepository:
            def __init__(self, target) -> None:
                captured_tool_targets.append(target)

        class FakeHandler:
            def __init__(self, **kwargs) -> None:
                del kwargs

            async def __call__(self, event):
                del event

        event = EventEnvelope.new(
            event_type=EventType.TOOL_CALL_REQUESTED,
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
            snapshot_id=new_uuid7(),
            payload={"tool_call_id": str(new_uuid7())},
        )
        database = FakeDatabase()
        consumer = FakeConsumer([ConsumedKafkaMessage(topic="deepdive.execution.commands", key=b"k", value=event.to_json().encode())])

        async def run_test() -> None:
            with (
                patch.object(runtime, "create_database", return_value=database),
                patch.object(runtime, "AiokafkaEventConsumer", return_value=consumer),
                patch.object(runtime, "AiokafkaEventProducer", return_value=FakeProducer()),
                patch.object(runtime, "PostgresSnapshotToolRepository", FakeSnapshotRepository),
                patch.object(runtime, "PostgresToolCallRepository", FakeToolCallRepository),
                patch.object(runtime, "MinioObjectStorage"),
                patch.object(runtime, "SourceToolExecutor"),
                patch.object(runtime, "ExecutionCommandHandler", FakeHandler),
            ):
                await runtime.consume_once(
                    ExecutionWorkerSettings(
                        database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                        kafka_bootstrap_servers="localhost:9092",
                        max_messages=1,
                    )
                )

        asyncio.run(run_test())

        self.assertEqual(captured_snapshot_targets, [database])
        self.assertEqual(captured_tool_targets, [database])

    def test_execution_worker_uses_app_config_for_tool_executor(self) -> None:
        import backend.workers.execution_runtime as runtime

        captured_executor_kwargs = []
        captured_handler_kwargs = []

        class FakeSnapshotRepository:
            def __init__(self, target) -> None:
                del target

        class FakeToolCallRepository:
            def __init__(self, target) -> None:
                del target

        class FakeExecutor:
            def __init__(self, **kwargs) -> None:
                captured_executor_kwargs.append(kwargs)

        class FakeHandler:
            def __init__(self, **kwargs) -> None:
                captured_handler_kwargs.append(kwargs)

            async def __call__(self, event):
                del event

        event = EventEnvelope.new(
            event_type=EventType.TOOL_CALL_REQUESTED,
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
            snapshot_id=new_uuid7(),
            payload={"tool_call_id": str(new_uuid7())},
        )
        database = FakeDatabase()
        consumer = FakeConsumer([ConsumedKafkaMessage(topic="deepdive.execution.commands", key=b"k", value=event.to_json().encode())])

        async def run_test() -> None:
            with (
                patch.dict(
                    os.environ,
                    {
                        "DEEPDIVE_ENV_FILE": str(PathLikeMissingEnv()),
                        "TOOL_READ_FILE_DEFAULT_LINES": "7",
                        "TOOL_READ_FILE_MAX_LINES": "9",
                        "TOOL_READ_FILE_MAX_BYTES": "111",
                        "TOOL_SEARCH_TEXT_MAX_RESULTS": "13",
                        "TOOL_SEARCH_TEXT_TIMEOUT_SECONDS": "17",
                        "TOOL_SEARCH_TEXT_MAX_OUTPUT_BYTES": "222",
                        "CACHE_ROOT_DIR": "D:/cache/deepdive",
                        "CACHE_MAX_PREFIX_BYTES": "333",
                    },
                    clear=True,
                ),
                patch.object(runtime, "create_database", return_value=database),
                patch.object(runtime, "AiokafkaEventConsumer", return_value=consumer),
                patch.object(runtime, "AiokafkaEventProducer", return_value=FakeProducer()),
                patch.object(runtime, "PostgresSnapshotToolRepository", FakeSnapshotRepository),
                patch.object(runtime, "PostgresToolCallRepository", FakeToolCallRepository),
                patch.object(runtime, "MinioObjectStorage"),
                patch.object(runtime, "SourceToolExecutor", FakeExecutor),
                patch.object(runtime, "ExecutionCommandHandler", FakeHandler),
            ):
                await runtime.consume_once(
                    ExecutionWorkerSettings(
                        database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                        kafka_bootstrap_servers="localhost:9092",
                        max_messages=1,
                        tool_heartbeat_interval_seconds=23,
                    )
                )

        asyncio.run(run_test())

        self.assertEqual(captured_executor_kwargs[0]["read_config"].default_lines, 7)
        self.assertEqual(captured_executor_kwargs[0]["read_config"].max_lines, 9)
        self.assertEqual(captured_executor_kwargs[0]["read_config"].max_bytes, 111)
        self.assertEqual(captured_executor_kwargs[0]["search_config"].max_results, 13)
        self.assertEqual(captured_executor_kwargs[0]["search_config"].timeout_seconds, 17)
        self.assertEqual(captured_executor_kwargs[0]["search_config"].max_output_bytes, 222)
        self.assertEqual(captured_executor_kwargs[0]["cache_config"].root_dir, "D:/cache/deepdive")
        self.assertEqual(captured_executor_kwargs[0]["cache_config"].max_prefix_bytes, 333)
        self.assertEqual(captured_handler_kwargs[0]["heartbeat_interval_seconds"], 23)


if __name__ == "__main__":
    unittest.main()


class PathLikeMissingEnv:
    def __str__(self) -> str:
        return "D:/path/that/does/not/exist/.env"


class FakeDatabase:
    def __init__(self) -> None:
        self.connection = FakeConnection()
        self.disposed = False

    def begin(self):
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


class FakeConnection:
    async def scalar(self, statement, params=None):
        del statement, params
        return False

    async def execute(self, statement, params=None):
        del statement, params
        return FakeResult([{"event_id": new_uuid7()}])


class FakeResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None


class FakeConsumer:
    def __init__(self, messages) -> None:
        self._messages = messages
        self._index = 0
        self.commits = 0

    async def start(self):
        return None

    async def stop(self):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        message = self._messages[self._index]
        self._index += 1
        return message

    async def commit(self):
        self.commits += 1


class FakeProducer:
    async def start(self):
        return None

    async def stop(self):
        return None

    async def send_and_wait(self, topic, *, key, value):
        del topic, key, value

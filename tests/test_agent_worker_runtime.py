from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from backend.events import EventEnvelope, EventType
from backend.events.kafka import ConsumedKafkaMessage
from backend.ids import new_uuid7
from backend.workers.agent_runtime import AgentWorkerSettings, build_agent_command_topics, load_agent_worker_settings


class AgentWorkerRuntimeTest(unittest.TestCase):
    def test_agent_worker_subscribes_only_to_agent_commands(self) -> None:
        self.assertEqual(
            build_agent_command_topics(),
            ("deepdive.agent.commands",),
        )

    def test_agent_worker_settings_load_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
                "AGENT_WORKER_GROUP": "agent-group",
                "AGENT_WORKER_MAX_MESSAGES": "3",
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://api.example.test/v1",
                "MINIO_ENDPOINT": "localhost:9000",
                "MINIO_ACCESS_KEY": "deepdive",
                "MINIO_SECRET_KEY": "deepdive-secret",
                "MINIO_BUCKET": "deepdive-objects-custom",
                "MINIO_SECURE": "false",
                "OPENAI_TIMEOUT_SECONDS": "12",
                "OPENAI_TOTAL_TIMEOUT_SECONDS": "34",
                "OPENAI_USER_AGENT": "DeepDive/custom",
                "OPENAI_TRANSPORT": "websocket_v2",
                "AGENT_WORKER_MAX_ATTEMPTS": "5",
            },
            clear=True,
        ):
            settings = load_agent_worker_settings()

        self.assertEqual(
            settings,
            AgentWorkerSettings(
                database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                kafka_bootstrap_servers="localhost:9092",
                consumer_group="agent-group",
                max_messages=3,
                openai_api_key="test-key",
                openai_base_url="https://api.example.test/v1",
                openai_user_agent="DeepDive/custom",
                openai_transport="websocket_v2",
                minio_endpoint="localhost:9000",
                minio_access_key="deepdive",
                minio_secret_key="deepdive-secret",
                minio_bucket="deepdive-objects-custom",
                minio_secure=False,
                openai_timeout_seconds=12,
                openai_total_timeout_seconds=34,
                run_forever=True,
                max_attempts=5,
            ),
        )

    def test_agent_worker_defaults_to_run_forever_for_runtime_service(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPDIVE_ENV_FILE": "D:/path/that/does/not/exist/.env",
                "DATABASE_URL": "postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                "KAFKA_BOOTSTRAP_SERVERS": "localhost:9092",
                "OPENAI_API_KEY": "test-key",
            },
            clear=True,
        ):
            settings = load_agent_worker_settings()

        self.assertTrue(settings.run_forever)
        self.assertEqual(settings.minio_bucket, "deepdive-objects")

    def test_agent_worker_repository_is_not_bound_to_consumer_transaction(self) -> None:
        import backend.workers.agent_runtime as runtime

        captured_repositories = []
        captured_runner_kwargs = []
        captured_producers = []

        class FakeRepository:
            def __init__(self, target) -> None:
                captured_repositories.append(target)

        captured_handler_kwargs = []

        class FakeHandler:
            def __init__(self, **kwargs) -> None:
                captured_handler_kwargs.append(kwargs)

            async def __call__(self, event):
                del event

        event = EventEnvelope.new(
            event_type=EventType.SNAPSHOT_READY,
            analysis_id=new_uuid7(),
            agent_id=new_uuid7(),
            snapshot_id=new_uuid7(),
        )
        database = FakeDatabase()
        consumer = FakeConsumer(
            [ConsumedKafkaMessage(topic="deepdive.agent.commands", key=b"k", value=event.to_json().encode())]
        )

        def fake_producer(*, bootstrap_servers):
            producer = FakeProducer(bootstrap_servers=bootstrap_servers)
            captured_producers.append(producer)
            return producer

        def fake_runner_factory(**kwargs):
            captured_runner_kwargs.append(kwargs)
            return object()

        async def run_test():
            with (
                patch.object(runtime, "create_database", return_value=database),
                patch.object(runtime, "AiokafkaEventConsumer", return_value=consumer),
                patch.object(runtime, "AiokafkaEventProducer", side_effect=fake_producer),
                patch.object(runtime, "PostgresAgentRepository", FakeRepository),
                patch.object(runtime, "ContextAssembler"),
                patch.object(runtime, "create_openai_responses_runner", side_effect=fake_runner_factory),
                patch.object(runtime, "MinioObjectStorage"),
                patch.object(runtime, "AgentCommandHandler", FakeHandler),
            ):
                await runtime.consume_once(
                    AgentWorkerSettings(
                        database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                        kafka_bootstrap_servers="localhost:9092",
                        openai_api_key="test-key",
                        openai_user_agent="DeepDive/custom",
                        openai_transport="websocket_v2",
                        max_messages=1,
                        max_attempts=7,
                    )
                )

        import asyncio

        asyncio.run(run_test())

        self.assertEqual(captured_repositories, [database])
        self.assertEqual(captured_handler_kwargs[0]["model_retry_attempts"], 7)
        self.assertNotIn("live_stream_publisher", captured_handler_kwargs[0])
        self.assertEqual(captured_runner_kwargs[0]["user_agent"], "DeepDive/custom")
        self.assertEqual(captured_runner_kwargs[0]["transport"], "websocket_v2")
        self.assertEqual(len(captured_producers), 1)
        self.assertEqual([producer.starts for producer in captured_producers], [1])
        self.assertEqual([producer.stops for producer in captured_producers], [1])


if __name__ == "__main__":
    unittest.main()


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
    def __init__(self, *, bootstrap_servers="localhost:9092") -> None:
        self.bootstrap_servers = bootstrap_servers
        self.starts = 0
        self.stops = 0
        self.sent = []

    async def start(self):
        self.starts += 1
        return None

    async def stop(self):
        self.stops += 1
        return None

    async def send_and_wait(self, topic, *, key, value):
        self.sent.append((topic, key, value))

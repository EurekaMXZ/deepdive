from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.config import AppConfig
from backend.events import EventEnvelope, EventType
from backend.ids import new_uuid7
from backend.workers.local_pipeline import LocalPipelineSettings, _dispatch_agent_event, _dispatch_event


class LocalPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def test_tool_failure_events_are_dispatched_to_agent_handler(self) -> None:
        handled_events: list[EventEnvelope] = []
        captured_runner_kwargs = []

        class FakeAgentHandler:
            def __init__(self, **kwargs) -> None:
                del kwargs

            async def __call__(self, event: EventEnvelope) -> None:
                handled_events.append(event)

        class FakeResponsesRunner:
            def __init__(self, **kwargs) -> None:
                captured_runner_kwargs.append(kwargs)

        with (
            patch("backend.workers.local_pipeline.PostgresAgentRepository"),
            patch("backend.workers.local_pipeline.ContextAssembler"),
            patch("backend.workers.local_pipeline.OpenAIResponsesRunner", FakeResponsesRunner),
            patch("backend.workers.local_pipeline.load_app_config_from_env"),
            patch("backend.workers.local_pipeline.AgentCommandHandler", FakeAgentHandler),
        ):
            event = EventEnvelope.new(
                event_type=EventType.TOOL_CALL_FAILED,
                analysis_id=new_uuid7(),
                agent_id=new_uuid7(),
                snapshot_id=new_uuid7(),
                payload={"tool_call_id": str(new_uuid7()), "error": {"code": "TOOL_FAILED"}},
            )

            await _dispatch_agent_event(
                event,
                database=FakeDatabase(),
                storage=object(),
                settings=LocalPipelineSettings(
                    database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                    openai_api_key="test-key",
                    openai_base_url="https://api.example.test/v1",
                    openai_user_agent="DeepDive/custom",
                    minio_endpoint="localhost:9000",
                    minio_access_key="deepdive",
                    minio_secret_key="deepdive-secret",
                    minio_bucket="deepdive-objects-custom",
                    minio_secure=False,
                    cache_root_dir="D:/cache/deepdive",
                    max_events=1,
                ),
            )

        self.assertEqual([event.event_type for event in handled_events], [EventType.TOOL_CALL_FAILED])
        self.assertEqual(captured_runner_kwargs[0]["user_agent"], "DeepDive/custom")

    async def test_execution_events_use_local_pipeline_app_config(self) -> None:
        captured_executor_kwargs = []

        class FakeExecutor:
            def __init__(self, **kwargs) -> None:
                captured_executor_kwargs.append(kwargs)

        class FakeHandler:
            def __init__(self, **kwargs) -> None:
                del kwargs

            async def __call__(self, event: EventEnvelope) -> None:
                del event

        config = AppConfig.default()
        with (
            patch("backend.workers.local_pipeline.PostgresSnapshotToolRepository"),
            patch("backend.workers.local_pipeline.PostgresToolCallRepository"),
            patch("backend.workers.local_pipeline.SourceToolExecutor", FakeExecutor),
            patch("backend.workers.local_pipeline.ExecutionCommandHandler", FakeHandler),
            patch("backend.workers.local_pipeline.load_app_config_from_env", return_value=config),
        ):
            await _dispatch_event(
                FakeConnection(),
                EventEnvelope.new(
                    event_type=EventType.TOOL_CALL_REQUESTED,
                    analysis_id=new_uuid7(),
                    agent_id=new_uuid7(),
                    snapshot_id=new_uuid7(),
                    payload={"tool_call_id": str(new_uuid7())},
                ),
                storage=object(),
                settings=LocalPipelineSettings(
                    database_url="postgresql+psycopg://deepdive:deepdive@localhost:5432/deepdive",
                    openai_api_key="test-key",
                    openai_base_url="https://api.example.test/v1",
                    minio_endpoint="localhost:9000",
                    minio_access_key="deepdive",
                    minio_secret_key="deepdive-secret",
                    minio_bucket="deepdive-objects-custom",
                    minio_secure=False,
                    cache_root_dir="D:/cache/deepdive",
                    max_events=1,
                ),
            )

        self.assertIs(captured_executor_kwargs[0]["read_config"], config.tools.read_file)
        self.assertIs(captured_executor_kwargs[0]["search_config"], config.tools.search_text)
        self.assertIs(captured_executor_kwargs[0]["cache_config"], config.cache)


class FakeConnection:
    pass


class FakeDatabase:
    pass


if __name__ == "__main__":
    unittest.main()

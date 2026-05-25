from __future__ import annotations

import os
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.agent import AgentCommandHandler, ContextAssembler
from backend.agent.openai_runner import create_openai_responses_runner
from backend.agent.repository import PostgresAgentRepository
from backend.cache import LocalSourceCache
from backend.config import load_app_config_from_env, load_dotenv_if_exists
from backend.db.connections import AsyncDbConnection, DbRow
from backend.db.runtime import Database, create_database
from backend.document import DocumentService
from backend.document.repository import PostgresDocumentRepository
from backend.events import EventEnvelope, EventType
from backend.execution import PermissionEngine, SourceToolExecutor
from backend.execution.repository import PostgresSnapshotToolRepository, PostgresToolCallRepository
from backend.snapshot.service import SnapshotService
from backend.storage import DEFAULT_OBJECT_BUCKET, MinioObjectStorage
from backend.workers.analysis import AnalysisCommandHandler
from backend.workers.asyncio_compat import run_async_worker
from backend.workers.batch_scheduler import AnalysisBatchSchedulerHandler
from backend.workers.execution import ExecutionCommandHandler


@dataclass(frozen=True)
class LocalPipelineSettings:
    database_url: str
    openai_api_key: str
    openai_base_url: str
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool
    cache_root_dir: str
    max_events: int = 100
    openai_user_agent: str = "DeepDive/1.0"
    openai_transport: str = "http"


def load_local_pipeline_settings() -> LocalPipelineSettings:
    load_dotenv_if_exists()
    return LocalPipelineSettings(
        database_url=os.environ["DATABASE_URL"],
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_user_agent=os.environ.get("OPENAI_USER_AGENT", "DeepDive/1.0"),
        openai_transport=os.environ.get("OPENAI_TRANSPORT", "http"),
        minio_endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
        minio_access_key=os.environ.get("MINIO_ACCESS_KEY", os.environ.get("MINIO_ROOT_USER", "deepdive")),
        minio_secret_key=os.environ.get("MINIO_SECRET_KEY", os.environ.get("MINIO_ROOT_PASSWORD", "deepdive-secret")),
        minio_bucket=os.environ.get("MINIO_BUCKET", DEFAULT_OBJECT_BUCKET),
        minio_secure=_bool_env(os.environ.get("MINIO_SECURE", "false")),
        cache_root_dir=os.environ.get("CACHE_ROOT_DIR", "/cache/deepdive"),
        max_events=int(os.environ.get("LOCAL_PIPELINE_MAX_EVENTS", "100")),
    )


async def run_local_pipeline(settings: LocalPipelineSettings) -> int:
    database = create_database(settings.database_url)
    storage = MinioObjectStorage(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )
    processed = 0
    try:
        while processed < settings.max_events:
            async with database.begin() as connection:
                row = await _fetch_next_outbox(connection)
                if row is None:
                    return processed
                event = EventEnvelope.from_json_value(row["payload_json"])
                if _is_agent_event(event):
                    agent_event = event
                    outbox_id = row["id"]
                else:
                    agent_event = None
                    outbox_id = None
                    await _dispatch_event(connection, event, storage=storage, settings=settings)
                    await _mark_outbox_published(connection, row["id"])
            if agent_event is not None and outbox_id is not None:
                await _dispatch_agent_event(agent_event, database=database, storage=storage, settings=settings)
                async with database.begin() as connection:
                    await _mark_outbox_published(connection, outbox_id)
                processed += 1
            else:
                processed += 1
    finally:
        await database.dispose()
    return processed


async def _fetch_next_outbox(connection: AsyncDbConnection) -> DbRow | None:
    result = await connection.execute(
        text(
            """
            SELECT id, payload_json
            FROM outbox_events
            WHERE published_at IS NULL
            ORDER BY created_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """
        )
    )
    return result.mappings().first()


async def _mark_outbox_published(connection: AsyncDbConnection, outbox_id: UUID) -> None:
    await connection.execute(
        text("UPDATE outbox_events SET published_at = now() WHERE id = :id"),
        {"id": outbox_id},
    )


def _is_agent_event(event: EventEnvelope) -> bool:
    return event.event_type in {
        EventType.SNAPSHOT_READY,
        EventType.AGENT_CONTINUE_REQUESTED,
        EventType.TOOL_CALL_COMPLETED,
        EventType.TOOL_CALL_FAILED,
        EventType.TOOL_CALL_DENIED,
    }


async def _dispatch_event(
    connection: AsyncDbConnection, event: EventEnvelope, *, storage: MinioObjectStorage, settings: LocalPipelineSettings
) -> None:
    if event.event_type in {EventType.ANALYSIS_REQUESTED, EventType.ANALYSIS_CANCEL_REQUESTED}:
        await AnalysisCommandHandler(connection)(event)
        return
    if event.event_type in {
        EventType.ANALYSIS_BATCH_SUBMITTED,
        EventType.ANALYSIS_BATCH_SLOT_AVAILABLE,
        EventType.ANALYSIS_COMPLETED,
        EventType.ANALYSIS_FAILED,
        EventType.ANALYSIS_CANCELLED,
    }:
        await AnalysisBatchSchedulerHandler(connection)(event)
        return
    if event.event_type == EventType.SNAPSHOT_REQUESTED:
        await SnapshotService(
            database=_SingleConnectionDatabase(connection), storage=storage
        ).handle_snapshot_requested(event)
        return
    if _is_agent_event(event):
        raise ValueError("Agent events must be dispatched outside the outbox transaction")
    if event.event_type == EventType.TOOL_CALL_REQUESTED:
        app_config = load_app_config_from_env()
        snapshot_repository = PostgresSnapshotToolRepository(connection)
        tool_calls = PostgresToolCallRepository(connection)
        await ExecutionCommandHandler(
            tool_calls=tool_calls,
            executor=SourceToolExecutor(
                repository=snapshot_repository,
                storage=storage,
                cache=LocalSourceCache(root_dir=settings.cache_root_dir),
                permission_engine=PermissionEngine(),
                read_config=app_config.tools.read_file,
                search_config=app_config.tools.search_text,
                web_search_config=app_config.tools.web_search,
                cache_config=app_config.cache,
                tavily_api_key=os.environ.get("TAVILY_API_KEY", ""),
                document_service=DocumentService(repository=PostgresDocumentRepository(connection), storage=storage),
            ),
        )(event)
        return


async def _dispatch_agent_event(
    event: EventEnvelope, *, database: Database, storage: MinioObjectStorage, settings: LocalPipelineSettings
) -> None:
    repository = PostgresAgentRepository(database)
    await AgentCommandHandler(
        repository=repository,
        context_assembler=ContextAssembler(repository=repository, storage=storage),
        responses_runner=_openai_runner(settings),
        config=load_app_config_from_env(),
    )(event)


def _openai_runner(settings: LocalPipelineSettings) -> Any:
    return create_openai_responses_runner(
        transport=settings.openai_transport,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        user_agent=settings.openai_user_agent,
    )


class _SingleConnectionDatabase:
    def __init__(self, connection: AsyncDbConnection) -> None:
        self._connection = connection

    def begin(self) -> AbstractAsyncContextManager[AsyncDbConnection]:
        return _SingleConnectionContext(self._connection)


class _SingleConnectionContext:
    def __init__(self, connection: AsyncDbConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> AsyncDbConnection:
        return self._connection

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


async def main_async() -> None:
    processed = await run_local_pipeline(load_local_pipeline_settings())
    print(f"processed {processed} events")


def main() -> None:
    run_async_worker(main_async())


if __name__ == "__main__":
    main()

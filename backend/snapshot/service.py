from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import text

from backend.config import SnapshotConfig, app_config_from_json
from backend.db.connections import AsyncDbConnection
from backend.events import EventEnvelope, EventType
from backend.ids import new_uuid7
from backend.snapshot.builder import GitSnapshotBuilder
from backend.snapshot.models import (
    SnapshotBuilder,
    SnapshotBuildError,
    SnapshotBuildRequest,
    SnapshotBuildResult,
    SnapshotPolicy,
)
from backend.snapshot.repository import ExistingSnapshot, SnapshotRepository
from backend.storage import InMemoryObjectStorage, ObjectStorage


class SnapshotDatabase(Protocol):
    def begin(self) -> AbstractAsyncContextManager[AsyncDbConnection]: ...


class SnapshotService:
    def __init__(
        self,
        *,
        database: SnapshotDatabase,
        builder: SnapshotBuilder | None = None,
        storage: ObjectStorage | None = None,
        snapshot_config: SnapshotConfig | None = None,
        git_timeout_seconds: int = 300,
    ) -> None:
        self._database = database
        self._builder = builder or GitSnapshotBuilder()
        self._storage = storage or InMemoryObjectStorage()
        self._policy = SnapshotPolicy.from_config(snapshot_config or SnapshotConfig())
        self._git_timeout_seconds = git_timeout_seconds

    async def handle_snapshot_requested(self, event: EventEnvelope) -> None:
        if event.analysis_id is None or event.agent_id is None:
            raise ValueError("SnapshotRequested requires analysis_id and agent_id")

        repository_url = event.payload.get("repository_url")
        requested_ref = event.payload.get("requested_ref")
        if not repository_url or not requested_ref:
            raise ValueError("SnapshotRequested requires repository_url and requested_ref")
        repository_url = str(repository_url)
        requested_ref = str(requested_ref)

        snapshot_id = new_uuid7()
        started = await self._mark_started(event, snapshot_id=snapshot_id)
        if not started:
            return
        try:
            policy = await self._policy_for_event(event)
        except SnapshotConfigError as exc:
            await self._mark_failed(event, error_code=exc.code, error_message=exc.message)
            return
        try:
            result = await asyncio.to_thread(
                self._builder.build,
                SnapshotBuildRequest(
                    snapshot_id=snapshot_id,
                    repository_url=repository_url,
                    requested_ref=requested_ref,
                    policy=policy,
                    storage=self._storage,
                    timeout_seconds=self._git_timeout_seconds,
                ),
            )
        except SnapshotBuildError as exc:
            await self._mark_failed(event, error_code=exc.code, error_message=exc.message)
            return
        except Exception as exc:
            await self._mark_failed(event, error_code="SnapshotBuildFailed", error_message=str(exc))
            return

        await self._mark_ready(event, result)

    async def _policy_for_event(self, event: EventEnvelope) -> SnapshotPolicy:
        config_snapshot_id = event.payload.get("config_snapshot_id")
        if not config_snapshot_id:
            raise SnapshotConfigError(
                "CONFIG_SNAPSHOT_REQUIRED", "SnapshotRequested event is missing config_snapshot_id."
            )
        async with self._database.begin() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT config_json
                    FROM config_snapshots
                    WHERE id = :config_snapshot_id
                    """
                ),
                {"config_snapshot_id": config_snapshot_id},
            )
            row = result.mappings().first()
        if row is None:
            raise SnapshotConfigError(
                "CONFIG_SNAPSHOT_NOT_FOUND", f"Config snapshot does not exist: {config_snapshot_id}"
            )
        return SnapshotPolicy.from_config(app_config_from_json(cast(dict[str, Any], row["config_json"])).snapshot)

    async def _mark_started(self, event: EventEnvelope, *, snapshot_id: UUID) -> bool:
        if event.analysis_id is None or event.agent_id is None:
            raise ValueError("SnapshotStarted requires analysis_id and agent_id")
        now = datetime.now(UTC)
        async with self._database.begin() as connection:
            repository = SnapshotRepository(connection)
            marked = await repository.mark_analysis_snapshotting(
                analysis_id=event.analysis_id, agent_id=event.agent_id, now=now
            )
            if not marked:
                return False
            await repository.add_outbox(
                EventEnvelope.new(
                    event_type=EventType.SNAPSHOT_STARTED,
                    analysis_id=event.analysis_id,
                    agent_id=event.agent_id,
                    snapshot_id=snapshot_id,
                    correlation_id=event.correlation_id,
                    causation_id=event.event_id,
                    payload={
                        "repository_url_hash": None,
                        "requested_ref": event.payload.get("requested_ref"),
                    },
                )
            )
        return True

    async def _mark_ready(self, event: EventEnvelope, result: SnapshotBuildResult) -> None:
        now = datetime.now(UTC)
        async with self._database.begin() as connection:
            repository = SnapshotRepository(connection)
            existing = await repository.find_ready_snapshot(result)
            if existing is not None:
                await self._reuse_existing(repository, event=event, existing=existing, now=now)
                return

            inserted = await repository.insert_snapshot(result, now=now)
            if not inserted:
                existing = await repository.find_ready_snapshot(result)
                if existing is not None:
                    await self._reuse_existing(repository, event=event, existing=existing, now=now)
                    return

            await repository.insert_snapshot_files(result, now=now)
            await repository.insert_instruction_files(result, now=now)
            associated = await repository.associate_snapshot(event=event, snapshot_id=result.snapshot_id, now=now)
            if not associated:
                return
            await self._emit_ready(
                repository,
                event=event,
                snapshot_id=result.snapshot_id,
                resolved_commit_sha=result.resolved_commit_sha,
                tree_sha=result.tree_sha,
                manifest_key=result.manifest_key,
                git_bundle_key=result.git_bundle_key,
                file_count=result.file_count,
                reused_existing_snapshot=False,
            )

    async def _reuse_existing(
        self, repository: SnapshotRepository, *, event: EventEnvelope, existing: ExistingSnapshot, now: datetime
    ) -> None:
        associated = await repository.associate_snapshot(event=event, snapshot_id=existing.id, now=now)
        if not associated:
            return
        await self._emit_ready(
            repository,
            event=event,
            snapshot_id=existing.id,
            resolved_commit_sha=existing.resolved_commit_sha,
            tree_sha=existing.tree_sha,
            manifest_key=existing.manifest_key,
            git_bundle_key=existing.git_bundle_key,
            file_count=existing.file_count,
            reused_existing_snapshot=True,
        )

    async def _emit_ready(
        self,
        repository: SnapshotRepository,
        *,
        event: EventEnvelope,
        snapshot_id: UUID,
        resolved_commit_sha: str,
        tree_sha: str,
        manifest_key: str | None,
        git_bundle_key: str | None,
        file_count: int | None,
        reused_existing_snapshot: bool,
    ) -> None:
        await repository.add_outbox(
            EventEnvelope.new(
                event_type=EventType.SNAPSHOT_READY,
                analysis_id=event.analysis_id,
                agent_id=event.agent_id,
                snapshot_id=snapshot_id,
                correlation_id=event.correlation_id,
                causation_id=event.event_id,
                payload={
                    "resolved_commit_sha": resolved_commit_sha,
                    "tree_sha": tree_sha,
                    "manifest_key": manifest_key,
                    "git_bundle_key": git_bundle_key,
                    "file_count": file_count,
                    "reused_existing_snapshot": reused_existing_snapshot,
                },
            )
        )

    async def _mark_failed(self, event: EventEnvelope, *, error_code: str, error_message: str) -> None:
        now = datetime.now(UTC)
        async with self._database.begin() as connection:
            repository = SnapshotRepository(connection)
            marked = await repository.mark_failed(
                event=event, error_code=error_code, error_message=error_message, now=now
            )
            if not marked:
                return
            await repository.add_outbox(
                EventEnvelope.new(
                    event_type=EventType.SNAPSHOT_FAILED,
                    analysis_id=event.analysis_id,
                    agent_id=event.agent_id,
                    correlation_id=event.correlation_id,
                    causation_id=event.event_id,
                    payload={
                        "error_code": error_code,
                        "error_message": error_message[:4096],
                    },
                )
            )


class SnapshotConfigError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

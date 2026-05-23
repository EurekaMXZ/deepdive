from __future__ import annotations

from backend.config import SnapshotConfig
from backend.events import EventEnvelope, EventType
from backend.snapshot import SnapshotBuilder
from backend.snapshot.service import SnapshotService
from backend.storage import InMemoryObjectStorage, ObjectStorage


class SnapshotCommandHandler:
    def __init__(
        self,
        *,
        database,
        builder: SnapshotBuilder | None = None,
        storage: ObjectStorage | None = None,
        snapshot_config: SnapshotConfig | None = None,
        git_timeout_seconds: int = 300,
    ) -> None:
        self._service = SnapshotService(
            database=database,
            builder=builder,
            storage=storage or InMemoryObjectStorage(),
            snapshot_config=snapshot_config,
            git_timeout_seconds=git_timeout_seconds,
        )

    async def __call__(self, event: EventEnvelope) -> None:
        if event.event_type != EventType.SNAPSHOT_REQUESTED:
            raise ValueError(f"Unsupported snapshot command event: {event.event_type}")
        await self._service.handle_snapshot_requested(event)

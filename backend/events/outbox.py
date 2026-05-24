from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from backend.events import EventEnvelope
from backend.events.publisher import EventPublisher


@dataclass(frozen=True)
class OutboxEvent:
    id: UUID
    event: EventEnvelope


class OutboxRepository(Protocol):
    async def fetch_unpublished(self, *, limit: int) -> list[OutboxEvent]: ...

    async def mark_published(self, outbox_id: UUID) -> None: ...


class OutboxPublisher:
    def __init__(self, outbox: OutboxRepository, publisher: EventPublisher) -> None:
        self._outbox = outbox
        self._publisher = publisher

    async def publish_batch(self, *, limit: int) -> int:
        rows = await self._outbox.fetch_unpublished(limit=limit)
        published = 0
        for row in rows:
            await self._publisher.publish(row.event)
            await self._outbox.mark_published(row.id)
            published += 1
        return published

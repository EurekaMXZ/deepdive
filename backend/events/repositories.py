from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from backend.db.connections import AsyncDbConnection, ConnectionSource, connection_from
from backend.events import EventEnvelope
from backend.events.kafka import OutboxEvent
from backend.ids import new_uuid7


class DbOutboxSink:
    def __init__(self, connection: AsyncDbConnection) -> None:
        self._connection = connection

    async def add(self, event: EventEnvelope) -> None:
        await self._connection.execute(
            text(
                """
                INSERT INTO outbox_events (id, event_type, payload_json, created_at)
                VALUES (:id, :event_type, :payload_json, :created_at)
                """
            ).bindparams(bindparam("payload_json", type_=JSONB)),
            {
                "id": new_uuid7(),
                "event_type": event.event_type.value,
                "payload_json": event.to_dict(),
                "created_at": datetime.now(UTC),
            },
        )


class SqlOutboxRepository:
    def __init__(self, connection: AsyncDbConnection) -> None:
        self._connection = connection

    async def fetch_unpublished(self, *, limit: int) -> list[OutboxEvent]:
        result = await self._connection.execute(
            text(
                """
                SELECT id, payload_json
                FROM outbox_events
                WHERE published_at IS NULL
                ORDER BY created_at
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"limit": limit},
        )
        rows: Any = result.mappings().all()
        return [OutboxEvent(id=row["id"], event=EventEnvelope.from_json_value(row["payload_json"])) for row in rows]

    async def mark_published(self, outbox_id: UUID) -> None:
        await self._connection.execute(
            text(
                """
                UPDATE outbox_events
                SET published_at = :published_at
                WHERE id = :id
                """
            ),
            {"id": outbox_id, "published_at": datetime.now(UTC)},
        )


class SqlProcessedEventRepository:
    claim_ttl_seconds = 900

    def __init__(self, connection_or_database: ConnectionSource) -> None:
        self._connection_or_database = connection_or_database

    def _connection(self):
        return connection_from(self._connection_or_database)

    async def is_processed(self, event_id: UUID, consumer_name: str) -> bool:
        async with self._connection() as connection:
            value = await connection.scalar(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM processed_events
                        WHERE event_id = :event_id
                          AND consumer_name = :consumer_name
                    )
                    """
                ),
                {"event_id": event_id, "consumer_name": consumer_name},
            )
        return bool(value)

    async def mark_processed(self, event_id: UUID, consumer_name: str, claim_owner: str | None = None) -> bool:
        now = datetime.now(UTC)
        async with self._connection() as connection:
            if claim_owner is None:
                result = await connection.execute(
                    text(
                        """
                        INSERT INTO processed_events (event_id, consumer_name, processed_at)
                        VALUES (:event_id, :consumer_name, :processed_at)
                        ON CONFLICT (event_id, consumer_name) DO NOTHING
                        RETURNING event_id
                        """
                    ),
                    {
                        "event_id": event_id,
                        "consumer_name": consumer_name,
                        "processed_at": now,
                    },
                )
            else:
                result = await connection.execute(
                    text(
                        """
                        INSERT INTO processed_events (event_id, consumer_name, processed_at)
                        SELECT :event_id, :consumer_name, :processed_at
                        FROM event_processing_claims
                        WHERE event_id = :event_id
                          AND consumer_name = :consumer_name
                          AND claim_owner = :claim_owner
                        ON CONFLICT (event_id, consumer_name) DO NOTHING
                        RETURNING event_id
                        """
                    ),
                    {
                        "event_id": event_id,
                        "consumer_name": consumer_name,
                        "claim_owner": claim_owner,
                        "processed_at": now,
                    },
                )
            if result.mappings().first() is None:
                if claim_owner is None:
                    return False
                already_processed = await connection.scalar(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM processed_events
                            WHERE event_id = :event_id
                              AND consumer_name = :consumer_name
                        )
                        """
                    ),
                    {"event_id": event_id, "consumer_name": consumer_name},
                )
                if not already_processed:
                    return False
            await self._release_processing_claim(connection, event_id, consumer_name, claim_owner)
        return True

    async def claim_processing(self, event_id: UUID, consumer_name: str) -> str | None:
        if await self.is_processed(event_id, consumer_name):
            return None
        now = datetime.now(UTC)
        claim_expires_at = now + timedelta(seconds=self.claim_ttl_seconds)
        claim_owner = secrets.token_urlsafe(24)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    INSERT INTO event_processing_claims (
                        event_id, consumer_name, claimed_at, claim_expires_at, claim_owner
                    )
                    VALUES (:event_id, :consumer_name, :claimed_at, :claim_expires_at, :claim_owner)
                    ON CONFLICT (event_id, consumer_name) DO UPDATE
                    SET claimed_at = EXCLUDED.claimed_at,
                        claim_expires_at = EXCLUDED.claim_expires_at,
                        claim_owner = EXCLUDED.claim_owner
                    WHERE event_processing_claims.claim_expires_at < :now
                    RETURNING event_id
                    """
                ),
                {
                    "event_id": event_id,
                    "consumer_name": consumer_name,
                    "claimed_at": now,
                    "claim_expires_at": claim_expires_at,
                    "claim_owner": claim_owner,
                    "now": now,
                },
            )
        return claim_owner if result.mappings().first() is not None else None

    async def renew_processing_claim(self, event_id: UUID, consumer_name: str, claim_owner: str) -> bool:
        now = datetime.now(UTC)
        claim_expires_at = now + timedelta(seconds=self.claim_ttl_seconds)
        async with self._connection() as connection:
            result = await connection.execute(
                text(
                    """
                    UPDATE event_processing_claims
                    SET claimed_at = :claimed_at,
                        claim_expires_at = :claim_expires_at
                    WHERE event_id = :event_id
                      AND consumer_name = :consumer_name
                      AND claim_owner = :claim_owner
                    RETURNING event_id
                    """
                ),
                {
                    "event_id": event_id,
                    "consumer_name": consumer_name,
                    "claim_owner": claim_owner,
                    "claimed_at": now,
                    "claim_expires_at": claim_expires_at,
                },
            )
        return result.mappings().first() is not None

    async def release_processing_claim(
        self, event_id: UUID, consumer_name: str, claim_owner: str | None = None
    ) -> None:
        async with self._connection() as connection:
            await self._release_processing_claim(connection, event_id, consumer_name, claim_owner)

    async def _release_processing_claim(
        self,
        connection: AsyncDbConnection,
        event_id: UUID,
        consumer_name: str,
        claim_owner: str | None = None,
    ) -> None:
        owner_clause = "AND claim_owner = :claim_owner" if claim_owner is not None else ""
        await connection.execute(
            text(
                f"""
                DELETE FROM event_processing_claims
                WHERE event_id = :event_id
                  AND consumer_name = :consumer_name
                  {owner_clause}
                """
            ),
            {"event_id": event_id, "consumer_name": consumer_name, "claim_owner": claim_owner},
        )

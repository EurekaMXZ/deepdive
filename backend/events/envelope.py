from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from backend.events.types import EventType
from backend.ids import new_uuid7


def _empty_payload() -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class EventEnvelope:
    event_id: UUID
    schema_version: int
    event_type: EventType
    occurred_at: datetime
    correlation_id: UUID
    causation_id: UUID | None = None
    analysis_id: UUID | None = None
    agent_id: UUID | None = None
    snapshot_id: UUID | None = None
    attempt: int = 1
    payload: dict[str, Any] = field(default_factory=_empty_payload)

    @classmethod
    def new(
        cls,
        *,
        event_type: EventType | str,
        analysis_id: UUID | None = None,
        agent_id: UUID | None = None,
        snapshot_id: UUID | None = None,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
        payload: dict[str, Any] | None = None,
    ) -> EventEnvelope:
        resolved_event_type = EventType(event_type)
        resolved_correlation_id = correlation_id or analysis_id or new_uuid7()
        return cls(
            event_id=new_uuid7(),
            schema_version=1,
            event_type=resolved_event_type,
            occurred_at=datetime.now(UTC),
            correlation_id=resolved_correlation_id,
            causation_id=causation_id,
            analysis_id=analysis_id,
            agent_id=agent_id,
            snapshot_id=snapshot_id,
            payload={} if payload is None else dict(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "schema_version": self.schema_version,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "correlation_id": str(self.correlation_id),
            "causation_id": str(self.causation_id) if self.causation_id else None,
            "analysis_id": str(self.analysis_id) if self.analysis_id else None,
            "agent_id": str(self.agent_id) if self.agent_id else None,
            "snapshot_id": str(self.snapshot_id) if self.snapshot_id else None,
            "attempt": self.attempt,
            "payload": self.payload,
        }

    def with_attempt(self, attempt: int) -> EventEnvelope:
        return replace(self, attempt=attempt)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> EventEnvelope:
        data = json.loads(value)
        if not isinstance(data, dict):
            raise ValueError("EventEnvelope JSON must decode to an object")
        return cls.from_dict(cast(dict[str, Any], data))

    @classmethod
    def from_json_value(cls, value: str | dict[str, Any]) -> EventEnvelope:
        if isinstance(value, str):
            return cls.from_json(value)
        return cls.from_dict(value)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EventEnvelope:
        return cls(
            event_id=UUID(data["event_id"]),
            schema_version=data["schema_version"],
            event_type=EventType(data["event_type"]),
            occurred_at=datetime.fromisoformat(data["occurred_at"]),
            correlation_id=UUID(data["correlation_id"]),
            causation_id=_optional_uuid(data.get("causation_id")),
            analysis_id=_optional_uuid(data.get("analysis_id")),
            agent_id=_optional_uuid(data.get("agent_id")),
            snapshot_id=_optional_uuid(data.get("snapshot_id")),
            attempt=data["attempt"],
            payload=cast(dict[str, Any], data["payload"]) if isinstance(data["payload"], dict) else {},
        )


def _optional_uuid(value: str | None) -> UUID | None:
    return UUID(value) if value else None

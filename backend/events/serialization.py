from __future__ import annotations

from backend.events.envelope import EventEnvelope


def outbox_payload(event: EventEnvelope) -> dict[str, object]:
    return {
        "event_type": event.event_type.value,
        "payload_json": event.to_dict(),
    }

from __future__ import annotations

from typing import Protocol

from backend.events import EventEnvelope, event_key, event_topic


class KafkaProducerClient(Protocol):
    async def send_and_wait(self, topic: str, *, key: bytes, value: bytes) -> object:
        ...


class EventPublisher:
    def __init__(self, producer: KafkaProducerClient) -> None:
        self._producer = producer

    async def publish(self, event: EventEnvelope, *, topic_override: str | None = None) -> None:
        topic = topic_override or event_topic(event)
        await self._producer.send_and_wait(
            topic,
            key=event_key(event).encode(),
            value=event.to_json().encode(),
        )

from __future__ import annotations

from backend.events.adapters import AiokafkaEventConsumer, AiokafkaEventProducer
from backend.events.consumer import (
    EventConsumerRunner,
    EventHandler,
    MessageHandleResult,
    ProcessedEventRepository,
    consume_messages,
)
from backend.events.messages import ConsumedKafkaMessage
from backend.events.outbox import OutboxEvent, OutboxPublisher, OutboxRepository
from backend.events.publisher import EventPublisher, KafkaProducerClient

__all__ = [
    "AiokafkaEventConsumer",
    "AiokafkaEventProducer",
    "ConsumedKafkaMessage",
    "EventConsumerRunner",
    "EventHandler",
    "EventPublisher",
    "KafkaProducerClient",
    "MessageHandleResult",
    "OutboxEvent",
    "OutboxPublisher",
    "OutboxRepository",
    "ProcessedEventRepository",
    "consume_messages",
]

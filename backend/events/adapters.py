from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, cast

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from backend.events.messages import ConsumedKafkaMessage


class KafkaConsumerRecord(Protocol):
    topic: str
    key: bytes | None
    value: bytes | None
    partition: int
    offset: int


KafkaSendAndWait = Callable[..., Awaitable[object]]
KafkaCommit = Callable[[], Awaitable[None]]
KafkaNextMessage = Callable[[], Awaitable[KafkaConsumerRecord]]


class AiokafkaEventProducer:
    def __init__(self, *, bootstrap_servers: str) -> None:
        self._producer: Any = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def send_and_wait(self, topic: str, *, key: bytes, value: bytes) -> object:
        send_and_wait = cast(KafkaSendAndWait, self._producer.send_and_wait)
        return await send_and_wait(topic, value=value, key=key)


class AiokafkaEventConsumer:
    def __init__(
        self,
        *topics: str,
        bootstrap_servers: str,
        group_id: str,
        enable_auto_commit: bool = False,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._consumer: Any = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=enable_auto_commit,
            auto_offset_reset=auto_offset_reset,
        )

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

    async def commit(self) -> None:
        commit = cast(KafkaCommit, self._consumer.commit)
        await commit()

    async def defer(self, message: ConsumedKafkaMessage) -> None:
        if message.partition is None or message.offset is None:
            return
        from aiokafka import TopicPartition

        seek = cast(Callable[[Any, int], None], self._consumer.seek)
        seek(TopicPartition(message.topic, message.partition), message.offset)

    def __aiter__(self) -> AiokafkaEventConsumer:
        return self

    async def __anext__(self) -> ConsumedKafkaMessage:
        next_message = cast(KafkaNextMessage, self._consumer.__anext__)
        message = await next_message()
        return ConsumedKafkaMessage(
            topic=message.topic,
            key=message.key,
            value=message.value or b"",
            partition=message.partition,
            offset=message.offset,
        )

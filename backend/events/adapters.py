from __future__ import annotations

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from backend.events.messages import ConsumedKafkaMessage


class AiokafkaEventProducer:
    def __init__(self, *, bootstrap_servers: str) -> None:
        self._producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def send_and_wait(self, topic: str, *, key: bytes, value: bytes) -> object:
        return await self._producer.send_and_wait(topic, value=value, key=key)


class AiokafkaEventConsumer:
    def __init__(
        self,
        *topics: str,
        bootstrap_servers: str,
        group_id: str,
        enable_auto_commit: bool = False,
        auto_offset_reset: str = "earliest",
    ) -> None:
        self._consumer = AIOKafkaConsumer(
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
        await self._consumer.commit()

    async def defer(self, message: ConsumedKafkaMessage) -> None:
        if message.partition is None or message.offset is None:
            return
        from aiokafka import TopicPartition

        self._consumer.seek(TopicPartition(message.topic, message.partition), message.offset)

    def __aiter__(self) -> "AiokafkaEventConsumer":
        return self

    async def __anext__(self) -> ConsumedKafkaMessage:
        message = await self._consumer.__anext__()
        return ConsumedKafkaMessage(
            topic=message.topic,
            key=message.key,
            value=message.value,
            partition=message.partition,
            offset=message.offset,
        )

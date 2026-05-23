from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from dataclasses import dataclass
import socket
from uuid import uuid4
from typing import DefaultDict
from uuid import UUID

from backend.events.live_stream import LIVE_MODEL_STREAM_TOPIC, LiveModelStreamEvent


class LiveStreamHub:
    def __init__(self, *, queue_size: int = 1000) -> None:
        self._queue_size = max(1, int(queue_size))
        self._subscriptions: DefaultDict[UUID, set[asyncio.Queue[LiveModelStreamEvent]]] = defaultdict(set)

    def subscribe(self, analysis_id: UUID) -> "LiveStreamSubscription":
        queue: asyncio.Queue[LiveModelStreamEvent] = asyncio.Queue(maxsize=self._queue_size)
        self._subscriptions[analysis_id].add(queue)
        return LiveStreamSubscription(hub=self, analysis_id=analysis_id, queue=queue)

    async def publish(self, event: LiveModelStreamEvent) -> None:
        for queue in tuple(self._subscriptions.get(event.analysis_id, ())):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def unsubscribe(self, analysis_id: UUID, queue: asyncio.Queue[LiveModelStreamEvent]) -> None:
        subscriptions = self._subscriptions.get(analysis_id)
        if not subscriptions:
            return
        subscriptions.discard(queue)
        if not subscriptions:
            self._subscriptions.pop(analysis_id, None)


@dataclass
class LiveStreamSubscription:
    hub: LiveStreamHub
    analysis_id: UUID
    queue: asyncio.Queue[LiveModelStreamEvent]
    closed: bool = False

    async def get(self) -> LiveModelStreamEvent:
        return await self.queue.get()

    def get_nowait(self) -> LiveModelStreamEvent:
        return self.queue.get_nowait()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.hub.unsubscribe(self.analysis_id, self.queue)


class KafkaLiveStreamSubscriber:
    def __init__(self, consumer, hub: LiveStreamHub) -> None:
        self._consumer = consumer
        self._hub = hub
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await self._consumer.start()
        self._task = asyncio.create_task(self._consume())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._consumer.stop()

    async def _consume(self) -> None:
        async for message in self._consumer:
            event = LiveModelStreamEvent.from_json(message.value)
            await self._hub.publish(event)


def unique_api_live_group_id(prefix: str = "deepdive-api-live") -> str:
    return f"{prefix}-{socket.gethostname()}-{uuid4()}"


def live_stream_topic() -> str:
    return LIVE_MODEL_STREAM_TOPIC
